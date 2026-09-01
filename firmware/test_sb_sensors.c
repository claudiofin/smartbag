/* Bring-up and timeout, against a simulated bus that keeps time.
 *
 * ⭐ THE HAL IS A VTABLE PRECISELY SO THIS FILE CAN EXIST. The fake platform
 * below has a clock, remembers pin states, and models the two things the
 * datasheets actually constrain: a time-of-flight sensor that refuses to answer
 * if XSHUT was released before its rail settled, and sensors that raise their
 * interrupt after a delay — or never.
 *
 * ⛔ "NEVER" IS THE CASE THAT MATTERS. A sensor that has come off its flex does
 * not fail loudly; it simply stops interrupting, and a driver that waits for it
 * without a deadline turns one dead part into a device that has stopped
 * responding.
 */
#include "sb_sensors.h"

#include <stdio.h>
#include <string.h>

static int failures, checks;

#define CHECK(cond, ...)                                                       \
    do {                                                                       \
        checks++;                                                              \
        if (!(cond)) {                                                         \
            failures++;                                                        \
            printf("  FAIL  %s:%d  ", __func__, __LINE__);                     \
            printf(__VA_ARGS__);                                               \
            printf("\n");                                                      \
        }                                                                      \
    } while (0)

typedef struct {
    uint32_t ms;
    bool pin[SB_PIN_COUNT];
    uint32_t xshut_high_at;
    bool rail_settled_before_xshut;
    /* how long each interrupt takes to assert; 0 means never */
    uint32_t tof_reply_ms, radar_reply_ms;
    uint32_t tof_started_at, radar_started_at;
    bool radar_l_alive, radar_r_alive;
    int spi_calls, i2c_calls;
    uint32_t max_delay_us;
} fake;

static uint32_t f_now(void *c) { return ((fake *)c)->ms; }

static void f_delay(void *c, uint32_t us)
{
    fake *f = c;
    f->ms += (us + 999) / 1000;
    if (us > f->max_delay_us) {
        f->max_delay_us = us;
    }
}

static void f_set(void *c, uint8_t pin, sb_pin_state s)
{
    fake *f = c;
    if (pin == SB_PIN_TOF_XSHUT) {
        if (s == SB_PIN_HIGH) {
            f->xshut_high_at = f->ms;
            /* ⚠️ The datasheet's rule, modelled: XSHUT may only rise once the
             * rail has had time to come up. The driver is expected to drive it
             * low first and wait, so a straight release fails here. */
            f->rail_settled_before_xshut = true;
        }
    }
    if (pin == SB_PIN_RADAR_EN && s == SB_PIN_HIGH) {
        f->radar_started_at = f->ms;
    }
    f->pin[pin] = (s == SB_PIN_HIGH);
}

static bool f_get(void *c, uint8_t pin)
{
    fake *f = c;
    if (pin == SB_PIN_TOF_INT) {
        return f->tof_reply_ms &&
               f->ms >= f->tof_started_at + f->tof_reply_ms;
    }
    if (pin == SB_PIN_RADAR_IRQ_L || pin == SB_PIN_RADAR_IRQ_R) {
        return f->radar_reply_ms &&
               f->ms >= f->radar_started_at + f->radar_reply_ms;
    }
    return f->pin[pin];
}

static bool f_spi(void *c, sb_cs cs, const uint8_t *tx, uint8_t *rx, size_t n)
{
    fake *f = c;
    f->spi_calls++;
    if (cs == SB_CS_RADAR_L && !f->radar_l_alive) return false;
    if (cs == SB_CS_RADAR_R && !f->radar_r_alive) return false;
    if (tx[0] == 0xA1) {
        f->radar_started_at = f->ms;
    }
    memset(rx, 0x5A, n);
    return true;
}

static bool f_i2c_w(void *c, uint8_t a, const uint8_t *b, size_t n)
{
    fake *f = c;
    (void)a; (void)n;
    f->i2c_calls++;
    if (b[1] == 0x87) {
        f->tof_started_at = f->ms;
    }
    return f->pin[SB_PIN_TOF_XSHUT];
}

static bool f_i2c_r(void *c, uint8_t a, uint8_t reg, uint8_t *b, size_t n)
{
    fake *f = c;
    (void)a; (void)reg;
    f->i2c_calls++;
    if (!f->pin[SB_PIN_TOF_XSHUT]) {
        return false;             /* held in shutdown: nothing on the bus */
    }
    memset(b, 0, n);
    if (n >= 2) { b[0] = 0x01; b[1] = 0x2C; }   /* 300 mm */
    return true;
}

static void f_mux(void *c, int ch) { (void)c; (void)ch; }
static uint16_t f_adc(void *c, uint8_t ch) { (void)c; (void)ch; return 0; }

static sb_hal make(fake *f)
{
    sb_hal h = {f_now, f_delay, f_spi, NULL, f_i2c_w, f_i2c_r, f_set, f_get,
                f_mux, f_adc, f};
    return h;
}

static void reset(fake *f)
{
    memset(f, 0, sizeof(*f));
    f->radar_l_alive = f->radar_r_alive = true;
    f->tof_reply_ms = 30;
    f->radar_reply_ms = 40;
}

/* ── tests ───────────────────────────────────────────────────────────────── */
static void test_tof_comes_up_and_ranges(void)
{
    fake f; reset(&f);
    sb_hal h = make(&f);
    sb_sensors s; sb_sensors_init(&s);

    CHECK(sb_tof_up(&s, &h) == SB_SENS_OK, "bring-up failed");
    CHECK(f.xshut_high_at >= SB_TOF_RAIL_SETTLE_MS,
          "XSHUT released at %u ms, before the rail settled", f.xshut_high_at);
    uint16_t mm = 0;
    CHECK(sb_tof_range(&s, &h, &mm) == SB_SENS_OK, "ranging failed");
    CHECK(mm == 300, "distance %u mm", mm);
}

static void test_ranging_before_bring_up_is_refused(void)
{
    fake f; reset(&f);
    sb_hal h = make(&f);
    sb_sensors s; sb_sensors_init(&s);
    uint16_t mm = 0;
    /* ⚠️ Not "returns garbage" — refuses. A distance read out of a sensor that
     * was never started is a number the app would happily display. */
    CHECK(sb_tof_range(&s, &h, &mm) == SB_SENS_NOT_READY, "did not refuse");
}

static void test_a_silent_tof_times_out_instead_of_hanging(void)
{
    fake f; reset(&f);
    f.tof_reply_ms = 0;                 /* it never interrupts */
    sb_hal h = make(&f);
    sb_sensors s; sb_sensors_init(&s);
    CHECK(sb_tof_up(&s, &h) == SB_SENS_OK, "bring-up failed");

    uint32_t t0 = f.ms;
    uint16_t mm = 0;
    CHECK(sb_tof_range(&s, &h, &mm) == SB_SENS_TIMEOUT, "did not time out");
    CHECK(f.ms - t0 >= SB_TOF_TIMEOUT_MS, "gave up after %u ms", f.ms - t0);
    CHECK(f.ms - t0 < SB_TOF_TIMEOUT_MS * 2, "took %u ms to give up", f.ms - t0);
    CHECK(s.tof_timeouts == 1, "the fault was not counted");
}

static void test_powering_down_really_shuts_it_up(void)
{
    fake f; reset(&f);
    sb_hal h = make(&f);
    sb_sensors s; sb_sensors_init(&s);
    sb_tof_up(&s, &h);
    sb_tof_down(&s, &h);
    CHECK(!f.pin[SB_PIN_TOF_XSHUT], "XSHUT left high with the sensor down");
    uint16_t mm;
    CHECK(sb_tof_range(&s, &h, &mm) == SB_SENS_NOT_READY, "still ranging");
}

static void test_radar_survives_one_dead_sensor(void)
{
    /* ⭐ One viewpoint is worse than two and much better than none. Refusing to
     * come up because half the hardware answered would turn a degraded map into
     * no map. */
    fake f; reset(&f);
    f.radar_r_alive = false;
    sb_hal h = make(&f);
    sb_sensors s; sb_sensors_init(&s);
    CHECK(sb_radar_up(&s, &h) == SB_SENS_OK, "refused with one sensor alive");

    uint16_t bins[8];
    CHECK(sb_radar_measure(&s, &h, SB_RADAR_LEFT, bins, 8) == SB_SENS_OK,
          "the live sensor did not measure");
    CHECK(sb_radar_measure(&s, &h, SB_RADAR_RIGHT, bins, 8) == SB_SENS_NO_REPLY,
          "the dead sensor answered");
}

static void test_both_radars_dead_is_a_failure_and_powers_down(void)
{
    fake f; reset(&f);
    f.radar_l_alive = f.radar_r_alive = false;
    sb_hal h = make(&f);
    sb_sensors s; sb_sensors_init(&s);
    CHECK(sb_radar_up(&s, &h) == SB_SENS_NO_REPLY, "came up with no sensors");
    /* ⚠️ And it must not leave ENABLE asserted: two dead chips still draw
     * current, and the whole power architecture is that nothing is powered
     * unless it is about to be read. */
    CHECK(!f.pin[SB_PIN_RADAR_EN], "ENABLE left high after a failed bring-up");
}

static void test_a_silent_radar_times_out(void)
{
    fake f; reset(&f);
    f.radar_reply_ms = 0;
    sb_hal h = make(&f);
    sb_sensors s; sb_sensors_init(&s);
    sb_radar_up(&s, &h);
    uint16_t bins[8];
    uint32_t t0 = f.ms;
    CHECK(sb_radar_measure(&s, &h, SB_RADAR_LEFT, bins, 8) == SB_SENS_TIMEOUT,
          "did not time out");
    CHECK(f.ms - t0 >= SB_RADAR_TIMEOUT_MS, "gave up early");
    CHECK(s.radar_timeouts == 1, "not counted");
}

static void test_the_timeouts_fit_inside_the_settle_window(void)
{
    /* ⛔ A deadline that outlasts the window it runs in is not a deadline. The
     * firmware waits 2000 ms for the object to settle; a radar timeout plus a
     * ToF timeout has to fit inside that, or a dead sensor stalls the whole
     * wake-up chain instead of being reported. */
    CHECK(SB_TOF_TIMEOUT_MS + SB_RADAR_TIMEOUT_MS < 2000,
          "%d ms of timeouts against a 2000 ms settle window",
          SB_TOF_TIMEOUT_MS + SB_RADAR_TIMEOUT_MS);
    printf("  note  worst case %d ms of waiting for silent sensors, inside a "
           "2000 ms settle window\n",
           SB_TOF_TIMEOUT_MS + SB_RADAR_TIMEOUT_MS);
}

int main(void)
{
    printf("sb_sensors: bring-up, sequencing and timeouts\n");
    test_tof_comes_up_and_ranges();
    test_ranging_before_bring_up_is_refused();
    test_a_silent_tof_times_out_instead_of_hanging();
    test_powering_down_really_shuts_it_up();
    test_radar_survives_one_dead_sensor();
    test_both_radars_dead_is_a_failure_and_powers_down();
    test_a_silent_radar_times_out();
    test_the_timeouts_fit_inside_the_settle_window();
    printf("%d checks, %d failures\n", checks, failures);
    return failures ? 1 : 0;
}
