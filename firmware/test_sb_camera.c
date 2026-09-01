/* The camera driver, against a simulated Arducam Mega.
 *
 * ⭐ THE FAKE BELOW IS THE PROTOCOL, NOT THE DRIVER. It decodes bit 7 of the
 * address byte into read or write, keeps a register file, answers reads on the
 * third byte the way the application note says, and fills its FIFO only after
 * it has been told to capture. So the test fails if the driver sets the wrong
 * bit, reads the wrong byte, or asks for pixels before the frame exists — which
 * are the three ways an SPI camera driver is wrong while looking right.
 *
 * ⛔ AND IT MODELS THE MODULE THAT NEVER ANSWERS, because Arducam's own SDK
 * spins forever on that and this driver must not.
 */
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "sb_camera.h"

static int checks, failures;
#define CHECK(c, ...) do { checks++; if (!(c)) { failures++; \
    printf("  FAIL  %s:%d  ", __func__, __LINE__); printf(__VA_ARGS__); \
    printf("\n"); } } while (0)

typedef struct {
    uint32_t ms;
    uint8_t reg[256];
    uint8_t fifo[SB_CAM_WIRE_BYTES + 16];
    uint32_t fifo_len;
    bool ever_idle;              /* false: the module that came off its flex  */
    bool alive;
    uint32_t capture_ms;         /* how long a frame takes to appear          */
    uint32_t capture_started;
    bool capturing;
    uint8_t last_res_written;
    uint8_t last_fmt_written;
    int burst_reads;
    bool burst_before_done;      /* pixels asked for while still exposing     */
    bool force_short;            /* the module writes a partial frame         */
} mega;

static uint32_t f_now(void *c) { return ((mega *)c)->ms; }
static void f_delay(void *c, uint32_t us) { ((mega *)c)->ms += (us + 999) / 1000; }

static void fifo_fill(mega *m)
{
    /* A recognisable ramp, so the burst read's dummy-byte handling shows up as
     * a shifted picture rather than as nothing. */
    for (size_t i = 0; i < sizeof(m->fifo); i++) {
        m->fifo[i] = (uint8_t)(i & 0xFF);
    }
    m->fifo_len = SB_CAM_WIRE_BYTES;
}

static bool f_spi(void *c, sb_cs cs, const uint8_t *tx, uint8_t *rx, size_t n)
{
    mega *m = c;
    if (cs != SB_CS_CAMERA || !m->alive) {
        return false;
    }
    memset(rx, 0, n);
    const uint8_t addr = tx[0] & 0x7F;

    if (tx[0] & 0x80) {                       /* write */
        m->reg[addr] = tx[1];
        if (addr == 0x21) { m->last_res_written = tx[1]; }
        if (addr == 0x20) { m->last_fmt_written = tx[1]; }
        if (addr == 0x04 && (tx[1] & 0x02)) {  /* start capture */
            m->capturing = true;
            m->capture_started = m->ms;
            m->fifo_len = 0;
        }
        if (addr == 0x04 && (tx[1] & 0x01)) {  /* clear the done flag */
            m->reg[0x44] &= (uint8_t)~0x04;
        }
        return true;
    }

    /* read: the answer belongs on the third byte */
    uint8_t val = 0;
    if (addr == 0x44) {
        /* low two bits: the I2C state machine. bit 2: capture done. */
        val = m->ever_idle ? 0x02 : 0x00;
        if (m->capturing && m->ms >= m->capture_started + m->capture_ms) {
            m->capturing = false;
            fifo_fill(m);
            if (m->force_short) {
                m->fifo_len = SB_CAM_WIRE_BYTES / 2;
            }
            m->reg[0x44] |= 0x04;
        }
        val |= (uint8_t)(m->reg[0x44] & 0x04);
    } else if (addr == 0x45) {
        val = (uint8_t)(m->fifo_len & 0xFF);
    } else if (addr == 0x46) {
        val = (uint8_t)((m->fifo_len >> 8) & 0xFF);
    } else if (addr == 0x47) {
        val = (uint8_t)((m->fifo_len >> 16) & 0xFF);
    } else {
        val = m->reg[addr];
    }
    if (n >= 3) {
        rx[2] = val;
    }
    return true;
}

static bool f_burst(void *c, sb_cs cs, const uint8_t *cmd, size_t cmd_len,
                    uint8_t *rx, size_t rx_len)
{
    mega *m = c;
    if (cs != SB_CS_CAMERA || !m->alive || cmd[0] != 0x3C) {
        return false;
    }
    m->burst_reads++;
    if (!(m->reg[0x44] & 0x04)) {
        m->burst_before_done = true;
    }
    /* ⚠️ The data phase begins with one preparation byte that is NOT pixel
     * data — 0xA5 here so a driver that keeps it is caught rather than merely
     * shifted. cmd_len counts the 0x3C plus whatever dummies the driver chose
     * to clock, so a driver that sends none starts on the 0xA5. */
    for (size_t i = 0; i < rx_len; i++) {
        const size_t at = (cmd_len - 1) + i;
        rx[i] = at == 0 ? 0xA5 : m->fifo[at - 1];
    }
    return true;
}

static bool f_i2c_w(void *c, uint8_t a, const uint8_t *d, size_t n)
{ (void)c; (void)a; (void)d; (void)n; return false; }
static bool f_i2c_r(void *c, uint8_t a, uint8_t r, uint8_t *d, size_t n)
{ (void)c; (void)a; (void)r; (void)d; (void)n; return false; }
static void f_set(void *c, uint8_t p, sb_pin_state s) { (void)c; (void)p; (void)s; }
static bool f_get(void *c, uint8_t p) { (void)c; (void)p; return false; }
static void f_mux(void *c, int ch) { (void)c; (void)ch; }
static uint16_t f_adc(void *c, uint8_t ch) { (void)c; (void)ch; return 0; }

static sb_hal make(mega *m)
{
    sb_hal h = { f_now, f_delay, f_spi, f_burst, f_i2c_w, f_i2c_r, f_set,
                 f_get, f_mux, f_adc, m };
    return h;
}

static void reset(mega *m, uint8_t id)
{
    memset(m, 0, sizeof(*m));
    m->alive = true;
    m->ever_idle = true;
    m->capture_ms = 40;
    m->reg[0x40] = id;
    m->reg[0x02] = 0x05;
}

/* ── the tests ─────────────────────────────────────────────────────────────── */
static void test_it_identifies_the_part_it_was_bought_as(void)
{
    mega m; reset(&m, 0x86);                 /* SENSOR_3MP */
    sb_hal h = make(&m);
    sb_camera c;
    CHECK(sb_cam_probe(&c, &h) == SB_CAM_OK, "probe failed on a 3MP");
    CHECK(c.id == 0x86, "id 0x%02X", c.id);
    CHECK(!c.legacy, "0x86 is at or above 0x85, so not the legacy encoding");
    CHECK(m.last_fmt_written == 0x02, "format 0x%02X, wanted RGB",
          m.last_fmt_written);
    /* ⭐ THE RESOLUTION IS THE WHOLE POINT OF READING THE ID FIRST. */
    CHECK(m.last_res_written == 0x00, "resolution 0x%02X for a non-legacy part",
          m.last_res_written);
    CHECK((m.last_res_written & 0x80) == 0, "asked for video, not a still");
}

static void test_the_older_3mp_needs_the_other_encoding(void)
{
    /* ⛔ 0x82 and 0x84 are also sold as "Mega 3MP" and they take 10, not 0, for
     * 96x96. Writing 0 to one of those asks for a resolution its table does not
     * list, and nothing anywhere returns an error. */
    mega m; reset(&m, 0x84);
    sb_hal h = make(&m);
    sb_camera c;
    CHECK(sb_cam_probe(&c, &h) == SB_CAM_OK, "probe failed on a 0x84");
    CHECK(c.legacy, "0x84 is below 0x85 and needs the legacy map");
    CHECK(m.last_res_written == 0x0A, "resolution 0x%02X for a legacy part",
          m.last_res_written);
}

static void test_something_that_is_not_a_mega_is_refused(void)
{
    mega m; reset(&m, 0x00);
    sb_hal h = make(&m);
    sb_camera c;
    CHECK(sb_cam_probe(&c, &h) == SB_CAM_BAD_ID, "accepted an ID of zero");
    CHECK(!c.ready, "marked ready after a bad ID");
}

static void test_a_module_that_never_answers_times_out(void)
{
    /* ⛔ This is the case Arducam's own waitI2cIdle cannot survive. */
    mega m; reset(&m, 0x86);
    m.ever_idle = false;
    sb_hal h = make(&m);
    sb_camera c;
    const uint32_t before = m.ms;
    CHECK(sb_cam_probe(&c, &h) == SB_CAM_TIMEOUT, "did not time out");
    CHECK(m.ms - before >= SB_CAM_READY_TIMEOUT_MS, "gave up too early");
    CHECK(m.ms - before < 4 * SB_CAM_READY_TIMEOUT_MS, "waited far too long");
}

static void test_a_frame_comes_back_and_the_first_byte_is_a_pixel(void)
{
    mega m; reset(&m, 0x86);
    sb_hal h = make(&m);
    sb_camera c;
    CHECK(sb_cam_probe(&c, &h) == SB_CAM_OK, "probe");

    static uint8_t wire[SB_CAM_WIRE_BYTES];
    static uint8_t grey[SB_CAM_PIXELS];
    CHECK(sb_cam_capture(&c, &h, wire, sizeof(wire), grey) == SB_CAM_OK,
          "capture failed");
    CHECK(c.frames == 1, "%u frames", c.frames);
    CHECK(!m.burst_before_done, "read the FIFO before the capture finished");
    /* ⛔ THE DUMMY BYTE. The FIFO holds 0,1,2,3..., and the module sends one
     * preparation byte before the data. A driver that keeps it returns a frame
     * shifted by one byte — which for RGB565 swaps the halves of every pixel
     * and turns a picture into plausible-looking rubbish. */
    CHECK(wire[0] == 0x00 && wire[1] == 0x01 && wire[2] == 0x02,
          "frame starts %02X %02X %02X — off by the preparation byte",
          wire[0], wire[1], wire[2]);
}

static void test_a_camera_that_never_finishes_exposing_times_out(void)
{
    mega m; reset(&m, 0x86);
    m.capture_ms = 0xFFFFFFF;                 /* never */
    sb_hal h = make(&m);
    sb_camera c;
    sb_cam_probe(&c, &h);
    static uint8_t wire[SB_CAM_WIRE_BYTES];
    CHECK(sb_cam_capture(&c, &h, wire, sizeof(wire), NULL) == SB_CAM_TIMEOUT,
          "did not time out on a frame that never arrives");
    CHECK(c.timeouts == 1, "%u timeouts", c.timeouts);
    CHECK(c.frames == 0, "counted a frame it never got");
}

static void test_a_short_fifo_is_refused_rather_than_padded(void)
{
    mega m; reset(&m, 0x86);
    sb_hal h = make(&m);
    sb_camera c;
    sb_cam_probe(&c, &h);
    /* The module reports the frame ready but with half the bytes: a partial
     * write, which is what a marginal supply looks like from up here. */
    m.force_short = true;
    static uint8_t wire[SB_CAM_WIRE_BYTES];
    memset(wire, 0xEE, sizeof(wire));
    CHECK(sb_cam_capture(&c, &h, wire, sizeof(wire), NULL) == SB_CAM_SHORT,
          "accepted half a frame");
    CHECK(c.short_frames == 1, "%u short frames", c.short_frames);
    CHECK(c.frames == 0, "counted a frame that was half the previous one");
    CHECK(wire[0] == 0xEE, "wrote pixels into the caller's buffer anyway");
    CHECK(m.burst_reads == 0, "read the FIFO despite knowing it was short");
}

static void test_a_buffer_that_is_too_small_is_refused(void)
{
    mega m; reset(&m, 0x86);
    sb_hal h = make(&m);
    sb_camera c;
    sb_cam_probe(&c, &h);
    uint8_t small[16];
    CHECK(sb_cam_capture(&c, &h, small, sizeof(small), NULL) == SB_CAM_NO_ROOM,
          "wrote a frame into 16 bytes");
}

static void test_luma_is_luma(void)
{
    /* ⚠️ Three primaries and a white. If red and blue were swapped the two
     * middle values would trade places and every other test would still pass. */
    const uint16_t px[4] = { 0xF800, 0x07E0, 0x001F, 0xFFFF };
    uint8_t wire[8], grey[4];
    for (int i = 0; i < 4; i++) {
        wire[2 * i] = (uint8_t)(px[i] >> 8);
        wire[2 * i + 1] = (uint8_t)px[i];
    }
    sb_cam_rgb565_to_grey(wire, 4, grey);
    CHECK(grey[0] > 70 && grey[0] < 82, "red luma %u, expected ~77", grey[0]);
    CHECK(grey[1] > 143 && grey[1] < 157, "green luma %u, expected ~150", grey[1]);
    CHECK(grey[2] > 22 && grey[2] < 36, "blue luma %u, expected ~29", grey[2]);
    CHECK(grey[3] >= 253, "white luma %u, expected 255", grey[3]);
    CHECK(grey[1] > grey[0] && grey[0] > grey[2],
          "green %u red %u blue %u — the channels are in the wrong order",
          grey[1], grey[0], grey[2]);
}

static void test_it_can_be_put_to_sleep(void)
{
    /* ⛔ 56-136 mA. thermal/budget.py's whole camera term assumes this happens. */
    mega m; reset(&m, 0x86);
    sb_hal h = make(&m);
    sb_camera c;
    sb_cam_probe(&c, &h);
    sb_cam_sleep(&c, &h);
    CHECK(m.reg[0x02] & 0x02, "pwdn not set: the sensor is still running");
    sb_cam_wake(&c, &h);
    CHECK(!(m.reg[0x02] & 0x02), "pwdn left set: no frame will ever arrive");
    CHECK(m.reg[0x02] & 0x04, "power_en cleared by the wake");
}

int main(void)
{
    printf("sb_camera: the Arducam Mega, by its own two documents\n");
    test_it_identifies_the_part_it_was_bought_as();
    test_the_older_3mp_needs_the_other_encoding();
    test_something_that_is_not_a_mega_is_refused();
    test_a_module_that_never_answers_times_out();
    test_a_frame_comes_back_and_the_first_byte_is_a_pixel();
    test_a_camera_that_never_finishes_exposing_times_out();
    test_a_short_fifo_is_refused_rather_than_padded();
    test_a_buffer_that_is_too_small_is_refused();
    test_luma_is_luma();
    test_it_can_be_put_to_sleep();
    printf("%d checks, %d failures\n", checks, failures);
    return failures ? 1 : 0;
}
