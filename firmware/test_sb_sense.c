/* The sensing loop, against a simulated bag.
 *
 * ⭐ THE POINT OF TESTING THIS ON A LAPTOP is that sequencing bugs are the ones
 * you otherwise find with a scope. "The illuminators stayed on", "the beam
 * triggered on the hand as well as the object", "a chattering zip counted as
 * four openings" — all of those are wrong ORDER or wrong TIMING, and none of
 * them needs silicon to reproduce. What needs silicon is whether the numbers
 * coming back are right, and no test here pretends otherwise.
 *
 * ⚠️ The bag below is a fixture, not a model of anything: a Hall pin, a range
 * the test sets, a sweep the test fills. It answers instantly, which is the one
 * way it is unlike the real thing — sb_sensors.c's own tests cover the waiting.
 */
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "sb_sense.h"

static int checks, failures;
#define CHECK(c, ...) do { checks++; if (!(c)) { failures++; \
    printf("  FAIL  %s:%d  ", __func__, __LINE__); printf(__VA_ARGS__); \
    printf("\n"); } } while (0)

/* ── the fixture ───────────────────────────────────────────────────────────── */
typedef struct {
    uint32_t ms;
    bool pin[SB_PIN_COUNT];
    uint16_t range_mm;
    uint16_t sweep[SB_RADAR_BINS];
    bool radar_alive;
    /* ⚠️ The sensors answer by raising an interrupt some milliseconds after
     * they are told to go, exactly as in test_sb_sensors.c — a fixture that
     * answers instantly would let a driver with no deadline pass. */
    uint32_t tof_reply_ms, radar_reply_ms;
    uint32_t tof_started_at, radar_started_at;
    uint32_t led_on_ms;          /* how long the illuminators were held on */
    uint32_t led_since;
    bool led_ever_on;

    /* ⚠️ A camera, because the loop now takes real frames. Enough of the
     * Arducam protocol to answer a probe and hand over a ramp; the whole of it
     * is exercised by test_sb_camera.c against its own fixture. */
    uint8_t creg[256];
    bool cam_alive;
    bool cam_capturing;
    uint32_t cam_started, cam_ms;
    uint32_t cam_len;
    uint32_t led_on_during_burst;
    int bursts;
} bag;

static uint32_t f_now(void *c) { return ((bag *)c)->ms; }

/* ⛔ ROUND UP, ALWAYS. A fake clock in whole milliseconds that truncates a
 * 200 µs delay to zero never advances, and every poll-with-a-deadline in
 * sb_sensors.c becomes an infinite loop. The first run of this file hung. */
static void f_delay(void *c, uint32_t us) { ((bag *)c)->ms += (us + 999) / 1000; }

static void f_set(void *c, uint8_t pin, sb_pin_state s)
{
    bag *b = c;
    if (pin == SB_PIN_IR_LED_EN) {
        if (s == SB_PIN_HIGH) {
            b->led_since = b->ms ? b->ms : 1;
            b->led_ever_on = true;
        } else if (b->led_since) {
            b->led_on_ms += b->ms - (b->led_since == 1 ? 0 : b->led_since);
            b->led_since = 0;
        }
    }
    if (pin == SB_PIN_RADAR_EN && s == SB_PIN_HIGH) {
        b->radar_started_at = b->ms;
    }
    b->pin[pin] = (s == SB_PIN_HIGH);
}

static bool f_get(void *c, uint8_t pin)
{
    bag *b = c;
    if (pin == SB_PIN_TOF_INT) {
        return b->tof_reply_ms && b->ms >= b->tof_started_at + b->tof_reply_ms;
    }
    if (pin == SB_PIN_RADAR_IRQ_L || pin == SB_PIN_RADAR_IRQ_R) {
        return b->radar_reply_ms &&
               b->ms >= b->radar_started_at + b->radar_reply_ms;
    }
    return b->pin[pin];
}

static bool cam_spi(bag *b, const uint8_t *tx, uint8_t *rx, size_t n)
{
    if (!b->cam_alive) {
        return false;
    }
    memset(rx, 0, n);
    const uint8_t addr = tx[0] & 0x7F;
    if (tx[0] & 0x80) {
        b->creg[addr] = tx[1];
        if (addr == 0x04 && (tx[1] & 0x02)) {
            b->cam_capturing = true;
            b->cam_started = b->ms;
            b->cam_len = 0;
        }
        if (addr == 0x04 && (tx[1] & 0x01)) {
            b->creg[0x44] &= (uint8_t)~0x04;
        }
        return true;
    }
    uint8_t val;
    if (addr == 0x44) {
        val = 0x02;                             /* always idle */
        if (b->cam_capturing && b->ms >= b->cam_started + b->cam_ms) {
            b->cam_capturing = false;
            b->cam_len = SB_CAM_WIRE_BYTES;
            b->creg[0x44] |= 0x04;
        }
        val |= (uint8_t)(b->creg[0x44] & 0x04);
    } else if (addr == 0x45) {
        val = (uint8_t)(b->cam_len & 0xFF);
    } else if (addr == 0x46) {
        val = (uint8_t)((b->cam_len >> 8) & 0xFF);
    } else if (addr == 0x47) {
        val = (uint8_t)((b->cam_len >> 16) & 0xFF);
    } else {
        val = b->creg[addr];
    }
    if (n >= 3) {
        rx[2] = val;
    }
    return true;
}

static bool f_burst(void *c, sb_cs cs, const uint8_t *cmd, size_t cmd_len,
                    uint8_t *rx, size_t rx_len)
{
    bag *b = c;
    if (cs != SB_CS_CAMERA || !b->cam_alive || cmd[0] != 0x3C) {
        return false;
    }
    b->bursts++;
    /* ⛔ THE ONE THING THIS FIXTURE WATCHES THAT THE CAMERA'S OWN DOES NOT:
     * whether the illuminators are still burning while 18 kB crosses the bus. */
    if (b->pin[SB_PIN_IR_LED_EN]) {
        b->led_on_during_burst++;
    }
    (void)cmd_len;
    for (size_t i = 0; i < rx_len; i++) {
        rx[i] = (uint8_t)(i & 0xFF);
    }
    return true;
}

static bool f_spi(void *c, sb_cs cs, const uint8_t *tx, uint8_t *rx, size_t n)
{
    bag *b = c;
    if (cs == SB_CS_CAMERA) {
        return cam_spi(b, tx, rx, n);
    }
    if (!b->radar_alive) {
        return false;
    }
    if (tx[0] == 0xA1) {                 /* start a sweep */
        b->radar_started_at = b->ms;
    }
    if (rx) {
        memset(rx, 0, n);
        if (tx[0] == 0xB0 && n >= 2) {   /* read range bin tx[1] */
            const uint16_t v = b->sweep[tx[1] % SB_RADAR_BINS];
            rx[0] = (uint8_t)(v >> 8);
            rx[1] = (uint8_t)(v & 0xFF);
        }
    }
    return true;
}

static bool f_i2c_w(void *c, uint8_t a, const uint8_t *d, size_t n)
{
    (void)a; (void)n;
    bag *b = c;
    if (n >= 2 && d[1] == 0x87) {        /* start ranging */
        b->tof_started_at = b->ms;
    }
    return b->pin[SB_PIN_TOF_XSHUT];
}

static bool f_i2c_r(void *c, uint8_t a, uint8_t reg, uint8_t *d, size_t n)
{
    (void)a; (void)reg;
    bag *b = c;
    if (!b->pin[SB_PIN_TOF_XSHUT]) {
        return false;
    }
    memset(d, 0, n);
    if (n >= 2) { d[0] = (uint8_t)(b->range_mm >> 8); d[1] = (uint8_t)b->range_mm; }
    return true;
}

static void f_mux(void *c, int ch) { (void)c; (void)ch; }
static uint16_t f_adc(void *c, uint8_t ch) { (void)c; (void)ch; return 0; }

static void fsr_drive(void *c, uint8_t col, sb_fsr_drive m)
{ (void)c; (void)col; (void)m; }
static uint16_t fsr_read(void *c, uint8_t row) { (void)c; (void)row; return 0; }
static void fsr_settle(void *c, uint32_t us) { (void)c; (void)us; }

/* ── events the loop produced ──────────────────────────────────────────────── */
static sb_event log_[64];
static int log_n;
static void collect(void *ctx, const sb_event *ev)
{
    (void)ctx;
    if (log_n < (int)(sizeof(log_) / sizeof(log_[0]))) {
        log_[log_n++] = *ev;
    }
}

static int count(sb_event_kind k)
{
    int n = 0;
    for (int i = 0; i < log_n; i++) {
        if (log_[i].kind == k) {
            n++;
        }
    }
    return n;
}

static void run(bag *b, sb_sense *s, sb_hal *h, sb_sensors *sn,
                sb_fsr_hal *fsr, uint32_t for_ms)
{
    const uint32_t until = b->ms + for_ms;
    while (b->ms < until) {
        const uint32_t wait = sb_sense_step(s, h, sn, fsr, b->ms, collect, NULL);
        b->ms += wait ? wait : 1;
    }
}

static void setup(bag *b, sb_sense *s, sb_hal *h, sb_sensors *sn,
                  sb_fsr_hal *fsr)
{
    memset(b, 0, sizeof(*b));
    b->range_mm = 300;                 /* nothing in the mouth */
    b->radar_alive = true;
    b->cam_alive = true;
    b->creg[0x40] = 0x86;              /* Arducam Mega 3MP */
    b->creg[0x02] = 0x05;
    b->cam_ms = 40;
    b->tof_reply_ms = 30;              /* VL53L1X long-distance period */
    b->radar_reply_ms = 40;
    for (int i = 0; i < SB_RADAR_BINS; i++) {
        b->sweep[i] = 100;             /* an empty bag is a flat sweep */
    }
    log_n = 0;
    *h = (sb_hal){f_now, f_delay, f_spi, f_burst, f_i2c_w, f_i2c_r, f_set, f_get,
                  f_mux, f_adc, b};
    *fsr = (sb_fsr_hal){fsr_drive, fsr_read, fsr_settle, b};
    sb_sensors_init(sn);
    sb_sense_init(s, 0);
}

/* ── the tests ─────────────────────────────────────────────────────────────── */
static void test_a_shut_bag_does_nothing(void)
{
    bag b; sb_sense s; sb_hal h; sb_sensors sn; sb_fsr_hal fsr;
    setup(&b, &s, &h, &sn, &fsr);
    run(&b, &s, &h, &sn, &fsr, 10000);
    CHECK(log_n == 0, "%d events from a bag nobody touched", log_n);
    CHECK(s.state == SB_SENSE_ASLEEP, "state %d", s.state);
    CHECK(s.maps_done == 0, "%u maps", s.maps_done);
}

static void test_the_zip_wakes_it(void)
{
    bag b; sb_sense s; sb_hal h; sb_sensors sn; sb_fsr_hal fsr;
    setup(&b, &s, &h, &sn, &fsr);
    b.pin[SB_PIN_HALL] = true;                 /* opened */
    run(&b, &s, &h, &sn, &fsr, 1000);
    CHECK(count(SB_EV_CLOSURE_OPENED) == 1, "%d open events",
          count(SB_EV_CLOSURE_OPENED));
    CHECK(s.state == SB_SENSE_AWAKE, "state %d", s.state);
    /* ⭐ And the time-of-flight sensor is now powered, which it was not before:
     * that is the whole reason the chain starts with a magnet. */
    CHECK(b.pin[SB_PIN_TOF_XSHUT], "ToF still held in shutdown");
}

static void test_a_chattering_slider_is_one_opening(void)
{
    /* ⛔ A zip slider crossing the magnet bounces. Four edges inside the debounce
     * window are one opening, and the rejected ones are counted rather than
     * acted on — a bag that logged four openings for one pull would make the
     * ledger's sequence number meaningless. */
    bag b; sb_sense s; sb_hal h; sb_sensors sn; sb_fsr_hal fsr;
    setup(&b, &s, &h, &sn, &fsr);
    for (int i = 0; i < 4; i++) {
        b.pin[SB_PIN_HALL] = true;
        sb_sense_step(&s, &h, &sn, &fsr, b.ms, collect, NULL);
        b.ms += 5;
        b.pin[SB_PIN_HALL] = false;
        sb_sense_step(&s, &h, &sn, &fsr, b.ms, collect, NULL);
        b.ms += 5;
    }
    b.pin[SB_PIN_HALL] = true;
    run(&b, &s, &h, &sn, &fsr, 500);
    CHECK(count(SB_EV_CLOSURE_OPENED) == 1, "%d openings from one pull",
          count(SB_EV_CLOSURE_OPENED));
    CHECK(s.hall_bounces > 0, "no bounces counted");
}

static void test_an_object_crossing_the_mouth_starts_a_burst(void)
{
    bag b; sb_sense s; sb_hal h; sb_sensors sn; sb_fsr_hal fsr;
    setup(&b, &s, &h, &sn, &fsr);
    b.pin[SB_PIN_HALL] = true;
    run(&b, &s, &h, &sn, &fsr, 300);
    b.range_mm = 60;                            /* something in the beam */
    run(&b, &s, &h, &sn, &fsr, 300);
    CHECK(count(SB_EV_TOF_CROSSED) == 1, "%d crossings",
          count(SB_EV_TOF_CROSSED));
    CHECK(count(SB_EV_FRAME_READY) == 3, "%d frames, wanted 3",
          count(SB_EV_FRAME_READY));
    CHECK(s.captures == 1, "%u captures", s.captures);
}

static void test_the_illuminators_are_on_only_for_the_exposure(void)
{
    /* ⛔ 600 mW. thermal/budget.py charges the IR LEDs 10 ms an event and gets
     * 2.8 µW average out of it; held on through a burst they would be the
     * largest term in the whole budget and the cell would last weeks. */
    bag b; sb_sense s; sb_hal h; sb_sensors sn; sb_fsr_hal fsr;
    setup(&b, &s, &h, &sn, &fsr);
    b.pin[SB_PIN_HALL] = true;
    run(&b, &s, &h, &sn, &fsr, 300);
    b.range_mm = 60;
    run(&b, &s, &h, &sn, &fsr, 500);
    CHECK(!b.pin[SB_PIN_IR_LED_EN], "illuminators left on");
    CHECK(b.led_ever_on, "never turned them on at all");
    /* ⛔ THE ASSERTION THAT MATTERS IS THIS ONE. How long the module exposes is
     * the module's business — the datasheet does not promise a number and the
     * fixture's 40 ms is a stand-in. What is ours is that 18 kB of already-taken
     * picture does not cross the bus under 600 mW of illumination, which would
     * add 18 ms a frame to a term the budget charges at 15. */
    CHECK(b.bursts == 3, "%d bursts for three frames", b.bursts);
    CHECK(b.led_on_during_burst == 0,
          "%u of %d frame transfers happened with the illuminators lit",
          b.led_on_during_burst, b.bursts);
    /* And the frames are real: the fixture hands back a ramp, so a loop that
     * emitted SB_EV_FRAME_READY without fetching anything leaves this zero. */
    CHECK(s.frames_captured == 3, "%u frames captured", s.frames_captured);
    CHECK(s.frame_failures == 0, "%u frames failed", s.frame_failures);
}

static void test_closing_the_bag_maps_it_after_the_settle(void)
{
    bag b; sb_sense s; sb_hal h; sb_sensors sn; sb_fsr_hal fsr;
    setup(&b, &s, &h, &sn, &fsr);
    b.pin[SB_PIN_HALL] = true;
    /* ⚠️ 600 ms, not 200: asleep the loop only looks every 250 ms, so a bag
     * opened at t=0 is not known to be open until the second poll. That is the
     * design — the zip is the one thing that can change while the bag is shut,
     * and a hand opening one takes half a second. */
    run(&b, &s, &h, &sn, &fsr, 600);
    CHECK(s.state == SB_SENSE_AWAKE, "state %d, never woke", s.state);
    b.pin[SB_PIN_HALL] = false;                 /* shut again */
    run(&b, &s, &h, &sn, &fsr, 200);
    CHECK(s.maps_done == 0, "mapped before the bag stopped moving");
    run(&b, &s, &h, &sn, &fsr, SB_SETTLE_MS + 500);
    CHECK(s.maps_done == 1, "%u maps after the settle window", s.maps_done);
    CHECK(count(SB_EV_STILL) == 1, "%d still events", count(SB_EV_STILL));
    /* ⭐ And everything is off again afterwards, which is the state the bag is
     * in for all but a few seconds of its life. */
    CHECK(s.state == SB_SENSE_ASLEEP, "state %d after mapping", s.state);
    CHECK(!b.pin[SB_PIN_TOF_XSHUT], "ToF left powered with the bag shut");
}

/* ── the heuristics ────────────────────────────────────────────────────────── */
static void test_a_flat_sweep_is_an_empty_bag(void)
{
    /* ⛔ The largest sample of a flat sweep is noise, and reporting it gives a
     * bag that always contains exactly one thing, always in the same place. */
    uint16_t sweep[SB_RADAR_BINS];
    for (int i = 0; i < SB_RADAR_BINS; i++) {
        sweep[i] = (uint16_t)(100 + (i % 7));
    }
    CHECK(sb_sense_peak_mm(sweep, SB_RADAR_BINS) == 0, "found an object in noise");
}

static void test_the_sensor_does_not_see_itself(void)
{
    /* ⛔ Transmit leakage sits in the first bins on every pulsed radar ever
     * built. A plain maximum finds it, at the same distance, every time. */
    uint16_t sweep[SB_RADAR_BINS];
    for (int i = 0; i < SB_RADAR_BINS; i++) {
        sweep[i] = 100;
    }
    sweep[2] = 60000;                            /* the sensor's own package */
    sweep[40] = 4000;                            /* something real */
    const uint16_t mm = sb_sense_peak_mm(sweep, SB_RADAR_BINS);
    CHECK(mm == 40 * SB_RADAR_BIN_MM, "%u mm, expected the object not the case",
          mm);
}

static void test_two_radars_that_disagree_report_nothing(void)
{
    /* ⭐ Two distances that cannot belong to one point mean the radars are
     * looking at two different objects. That is the common case with a full bag
     * and it is exactly when inventing a point would be worst. */
    int16_t x = -1, y = -1;
    CHECK(!sb_sense_triangulate(10, 10, &x, &y), "invented a point from 10/10");
    CHECK(sb_sense_triangulate(100, 120, &x, &y), "no point from a real pair");
    CHECK(x > 0 && x < 225, "x %d outside the floor", x);
    CHECK(y >= 0 && y <= 78, "y %d outside the floor", y);
}

int main(void)
{
    printf("sb_sense: the loop that reads the bag\n");
    test_a_shut_bag_does_nothing();
    test_the_zip_wakes_it();
    test_a_chattering_slider_is_one_opening();
    test_an_object_crossing_the_mouth_starts_a_burst();
    test_the_illuminators_are_on_only_for_the_exposure();
    test_closing_the_bag_maps_it_after_the_settle();
    test_a_flat_sweep_is_an_empty_bag();
    test_the_sensor_does_not_see_itself();
    test_two_radars_that_disagree_report_nothing();
    printf("%d checks, %d failures\n", checks, failures);
    return failures ? 1 : 0;
}
