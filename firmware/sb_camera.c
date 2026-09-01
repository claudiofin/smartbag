#include <string.h>

#include "sb_camera.h"

/* ── the register map, from Arducam's own two documents ───────────────────────
 *
 * Addresses and bit meanings: "Arducam Mega SPI Camera Series Application Note",
 * Table 1 (registers 0x00-0x35). The read-side registers below 0x49 are not in
 * that table; they are Arducam's SDK, src/Arducam/ArducamCamera.c, at the head
 * of the file. Both are quoted here rather than paraphrased.
 */
#define CAM_FIFO_CTRL 0x04     /* bit0 clear the done flag, bit1 start        */
#define CAM_FIFO_CLEAR_ID 0x01
#define CAM_FIFO_START 0x02
#define CAM_POWER_CONTROL 0x02 /* bit2 power_en, bit1 pwdn, bit0 rst_n        */
#define CAM_SENSOR_RESET 0x07  /* bit6 resets the FPGA                        */
#define CAM_RESET_ENABLE (1 << 6)
#define CAM_FORMAT 0x20        /* 1 JPEG, 2 RGB, 3 YUV — and no grey          */
#define CAM_FORMAT_RGB 0x02
#define CAM_CAPTURE_RESOLUTION 0x21 /* bit7 clear = still, bit6:0 resolution  */
#define CAM_MODE_STILL (0 << 7)
#define CAM_BURST_FIFO_READ 0x3C
#define CAM_SENSOR_ID 0x40
#define CAM_TRIG 0x44          /* bit0 vsync, bit1 shutter, bit2 capture done */
#define CAM_CAP_DONE 0x04
#define CAM_FIFO_SIZE1 0x45    /* length[7:0]                                 */
#define CAM_FIFO_SIZE2 0x46    /* length[15:8]                                */
#define CAM_FIFO_SIZE3 0x47    /* length[18:16]                               */
/* ⚠️ 0x44 TWICE IS NOT A TYPO. Arducam's SDK names the same address both
 * ARDUCHIP_TRIG, whose bit 2 is "capture done", and CAM_REG_SENSOR_STATE, whose
 * low two bits are the I2C state machine. Both names are kept because both
 * meanings are used below and collapsing them into one would make the next
 * reader check the datasheet again. */
#define CAM_SENSOR_STATE 0x44  /* &0x03 == 0x02 means the I2C side is idle    */
#define CAM_STATE_IDLE (1 << 1)

/* ⚠️ 96x96 has two encodings and the SDK picks by sensor ID. The application
 * note's table gives 10 for the MEGA-3MP's register 0x21; the SDK's mode enum
 * gives 0 and maps it to 10 only for parts reporting below 0x85. Both are here
 * and sb_cam_probe decides which applies. */
#define CAM_RES_96X96_ENUM 0x00
#define CAM_RES_96X96_LEGACY 0x0A
#define CAM_ID_LEGACY_BELOW 0x85

/* ⛔ A WRITE IS THE ADDRESS WITH BIT 7 SET, A READ IS THE ADDRESS WITH IT
 * CLEAR, and the difference is one bit that turns "tell me the sensor ID" into
 * "reset the FPGA". SDK cameraWriteReg/cameraReadReg. */
static bool wr(const sb_hal *hal, uint8_t addr, uint8_t val)
{
    const uint8_t tx[2] = { (uint8_t)(addr | 0x80), val };
    uint8_t rx[2];
    return hal->spi_xfer(hal->ctx, SB_CS_CAMERA, tx, rx, sizeof(tx));
}

/* ⚠️ THE ANSWER IS THE THIRD BYTE, NOT THE SECOND. The application note calls
 * the second byte "dummy data, used to provide a delay area... to prepare data
 * for the camera"; the SDK's cameraBusRead transfers twice and keeps the second
 * result. Taking rx[1] reads whatever was on MISO while the camera was still
 * fetching, which on a quiet bus is 0x00 — an ID of zero, a state of "not
 * idle", and a driver that hangs on a working camera. */
static bool rd(const sb_hal *hal, uint8_t addr, uint8_t *val)
{
    const uint8_t tx[3] = { (uint8_t)(addr & 0x7F), 0x00, 0x00 };
    uint8_t rx[3] = { 0 };
    if (!hal->spi_xfer(hal->ctx, SB_CS_CAMERA, tx, rx, sizeof(tx))) {
        return false;
    }
    *val = rx[2];
    return true;
}

/* ⛔ THE SDK SPINS HERE WITH NO DEADLINE. cameraWaitI2cIdle is a bare while
 * loop on a register, which on a module that has come off its connector is a
 * device that stops responding rather than a device that reports a fault — the
 * same failure sb_sensors.c already refuses to have. */
static bool wait_idle(const sb_hal *hal, uint32_t deadline_ms)
{
    const uint32_t start = hal->now_ms(hal->ctx);
    for (;;) {
        uint8_t st = 0;
        if (!rd(hal, CAM_SENSOR_STATE, &st)) {
            return false;
        }
        if ((st & 0x03) == CAM_STATE_IDLE) {
            return true;
        }
        if (hal->now_ms(hal->ctx) - start >= deadline_ms) {
            return false;
        }
        hal->delay_us(hal->ctx, 500);
    }
}

static bool wr_wait(const sb_hal *hal, uint8_t addr, uint8_t val)
{
    return wr(hal, addr, val) && wait_idle(hal, SB_CAM_READY_TIMEOUT_MS);
}

sb_cam_status sb_cam_probe(sb_camera *c, const sb_hal *hal)
{
    memset(c, 0, sizeof(*c));

    if (!wr(hal, CAM_SENSOR_RESET, CAM_RESET_ENABLE)) {
        return SB_CAM_NO_REPLY;
    }
    if (!wait_idle(hal, SB_CAM_READY_TIMEOUT_MS)) {
        return SB_CAM_TIMEOUT;
    }
    if (!rd(hal, CAM_SENSOR_ID, &c->id)) {
        return SB_CAM_NO_REPLY;
    }
    /* ⚠️ 0x82, 0x84 and 0x86 are the three parts Arducam ships as "3MP"; 0x85
     * and 0x87 are the 5MP and the 2MP. Anything else is not a Mega, and an
     * unrecognised ID has to be a refusal rather than a default, because the
     * resolution encoding below depends on knowing which family answered. */
    if (c->id < 0x82 || c->id > 0x87) {
        return SB_CAM_BAD_ID;
    }
    c->legacy = c->id < CAM_ID_LEGACY_BELOW;

    if (!wr_wait(hal, CAM_FORMAT, CAM_FORMAT_RGB)) {
        return SB_CAM_TIMEOUT;
    }
    const uint8_t res = c->legacy ? CAM_RES_96X96_LEGACY : CAM_RES_96X96_ENUM;
    if (!wr_wait(hal, CAM_CAPTURE_RESOLUTION, (uint8_t)(CAM_MODE_STILL | res))) {
        return SB_CAM_TIMEOUT;
    }
    c->ready = true;
    return SB_CAM_OK;
}

void sb_cam_sleep(sb_camera *c, const sb_hal *hal)
{
    /* Register 0x02 defaults to 0x05: power_en set, pwdn clear, rst_n set.
     * Sleep is that with bit 1 raised. */
    (void)c;
    wr(hal, CAM_POWER_CONTROL, 0x05 | 0x02);
}

void sb_cam_wake(sb_camera *c, const sb_hal *hal)
{
    (void)c;
    wr(hal, CAM_POWER_CONTROL, 0x05);
}

void sb_cam_rgb565_to_grey(const uint8_t *wire, size_t pixels, uint8_t *grey)
{
    /* ⚠️ BT.601 luma with integer weights, and the channel order is the one
     * thing here that cannot be checked by reading a datasheet: RGB565 arrives
     * high byte first, so red is the top five bits of wire[0]. The five- and
     * six-bit fields are expanded by replicating their high bits, which is the
     * standard widening and keeps white at 255 rather than 248. */
    for (size_t i = 0; i < pixels; i++) {
        const uint16_t px = (uint16_t)((wire[2 * i] << 8) | wire[2 * i + 1]);
        const uint8_t r5 = (uint8_t)((px >> 11) & 0x1F);
        const uint8_t g6 = (uint8_t)((px >> 5) & 0x3F);
        const uint8_t b5 = (uint8_t)(px & 0x1F);
        const uint32_t r = (uint32_t)((r5 << 3) | (r5 >> 2));
        const uint32_t g = (uint32_t)((g6 << 2) | (g6 >> 4));
        const uint32_t b = (uint32_t)((b5 << 3) | (b5 >> 2));
        grey[i] = (uint8_t)((77 * r + 150 * g + 29 * b) >> 8);
    }
}

sb_cam_status sb_cam_expose(sb_camera *c, const sb_hal *hal)
{
    if (!c->ready) {
        return SB_CAM_NO_REPLY;
    }
    /* Clear the done flag before starting, or the poll below sees the previous
     * frame's flag and reads a FIFO that is still filling. SDK cameraSetCapture. */
    if (!wr(hal, CAM_FIFO_CTRL, CAM_FIFO_CLEAR_ID) ||
        !wr(hal, CAM_FIFO_CTRL, CAM_FIFO_START)) {
        return SB_CAM_NO_REPLY;
    }

    const uint32_t start = hal->now_ms(hal->ctx);
    for (;;) {
        uint8_t trig = 0;
        if (!rd(hal, CAM_TRIG, &trig)) {
            return SB_CAM_NO_REPLY;
        }
        if (trig & CAM_CAP_DONE) {
            break;
        }
        if (hal->now_ms(hal->ctx) - start >= SB_CAM_CAPTURE_TIMEOUT_MS) {
            c->timeouts++;
            return SB_CAM_TIMEOUT;
        }
        hal->delay_us(hal->ctx, 500);
    }
    return SB_CAM_OK;
}

sb_cam_status sb_cam_fetch(sb_camera *c, const sb_hal *hal, uint8_t *wire,
                           size_t wire_cap, uint8_t *grey)
{
    if (!c->ready) {
        return SB_CAM_NO_REPLY;
    }
    if (wire_cap < SB_CAM_WIRE_BYTES) {
        return SB_CAM_NO_ROOM;
    }
    uint8_t l1 = 0, l2 = 0, l3 = 0;
    if (!rd(hal, CAM_FIFO_SIZE1, &l1) || !rd(hal, CAM_FIFO_SIZE2, &l2) ||
        !rd(hal, CAM_FIFO_SIZE3, &l3)) {
        return SB_CAM_NO_REPLY;
    }
    const uint32_t len =
        (uint32_t)(((uint32_t)l3 << 16) | ((uint32_t)l2 << 8) | l1) & 0xFFFFFFu;

    /* ⛔ A SHORT FIFO IS A WRONG FRAME, NOT A SMALL ONE. Reading whatever is
     * there and handing 96x96 of it to the recogniser gives a picture that is
     * partly the previous capture, which classifies confidently and wrongly. */
    if (len < SB_CAM_WIRE_BYTES) {
        c->short_frames++;
        return SB_CAM_SHORT;
    }

    /* ⚠️ The first byte after the burst command is dummy — "allow enough time
     * for data preparation" — so it is read into a scratch byte and thrown
     * away rather than becoming the first half of the first pixel. Arducam's
     * SDK does this only on the first burst after a capture and keeps a flag;
     * doing it every time costs one byte and removes the flag. */
    const uint8_t cmd[2] = { CAM_BURST_FIFO_READ, 0x00 };
    if (!hal->spi_burst_read(hal->ctx, SB_CS_CAMERA, cmd, sizeof(cmd), wire,
                             SB_CAM_WIRE_BYTES)) {
        return SB_CAM_NO_REPLY;
    }

    if (grey) {
        sb_cam_rgb565_to_grey(wire, SB_CAM_PIXELS, grey);
    }
    c->frames++;
    return SB_CAM_OK;
}

sb_cam_status sb_cam_capture(sb_camera *c, const sb_hal *hal, uint8_t *wire,
                             size_t wire_cap, uint8_t *grey)
{
    /* ⚠️ The room check comes first even though fetch repeats it: exposing and
     * then discovering there is nowhere to put the frame spends the whole
     * capture, and on this design that is the largest current in the product. */
    if (wire_cap < SB_CAM_WIRE_BYTES) {
        return SB_CAM_NO_ROOM;
    }
    const sb_cam_status st = sb_cam_expose(c, hal);
    if (st != SB_CAM_OK) {
        return st;
    }
    return sb_cam_fetch(c, hal, wire, wire_cap, grey);
}
