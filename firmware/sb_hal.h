/* The line between this firmware and silicon, drawn explicitly.
 *
 * ⛔ EVERYTHING BELOW IS A FUNCTION POINTER AND NONE OF IT IS IMPLEMENTED HERE.
 * That is the point. A HAL written as `#include <nrfx_spim.h>` welds the design
 * to one vendor and makes the interesting parts — sequencing, timeouts, what
 * happens when a sensor does not answer — untestable without silicon. Written
 * as a vtable, the same code runs against a simulated bus on a laptop, which is
 * how firmware/test_sb_fsr.c already solves a resistive network instead of
 * mocking one.
 *
 * ⭐ WHAT THE PLATFORM OWES, AND NOTHING MORE. Ten functions. The nRF54L15's
 * SPIM, TWIM, SAADC, GPIOTE and RTC drivers go behind them, and none of that
 * appears in any file this project tests.
 *
 * ⚠️ THIS IS THE HONEST SIZE OF THE REMAINING SILICON WORK. Not "no drivers" —
 * these ten, plus a vendor BLE stack bound to sb_ble.c's buffers. Everything
 * above them is written and tested.
 */
#ifndef SB_HAL_H
#define SB_HAL_H

#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>

typedef enum { SB_PIN_LOW = 0, SB_PIN_HIGH = 1 } sb_pin_state;

/* Chip selects, named rather than numbered, so a driver cannot address the
 * wrong device by getting an index wrong. */
typedef enum {
    SB_CS_RADAR_L = 0,
    SB_CS_RADAR_R,
    SB_CS_CAMERA,
    SB_CS_COUNT,
} sb_cs;

typedef struct {
    /* ── time ────────────────────────────────────────────────────────────── */
    uint32_t (*now_ms)(void *ctx);
    void (*delay_us)(void *ctx, uint32_t us);

    /* ── SPI, shared by both radars and the camera ───────────────────────── */
    /* ⚠️ One transfer, chip select asserted for its duration. The A121 runs to
     * 50 MHz and the camera tops out at 8; the platform is expected to change
     * clock with the chip select, which is why the select is a parameter here
     * and not a separate call. */
    bool (*spi_xfer)(void *ctx, sb_cs cs, const uint8_t *tx, uint8_t *rx,
                     size_t len);

    /* ⛔ AND A SECOND ONE, BECAUSE A BURST READ IS NOT A TRANSFER. The camera
     * hands over a frame as a short command followed by kilobytes of data under
     * a single chip select — Arducam's application note calls it burst read
     * timing — and spi_xfer's one length cannot say that without a transmit
     * buffer as large as the frame. 18 kB of zeros to clock out 18 kB of pixels
     * is 7% of the nRF54L15's RAM spent saying nothing.
     *
     * cmd_len bytes go out with whatever comes back discarded, then rx_len
     * bytes are clocked in with zeros on MOSI, all inside one assertion. That
     * is two descriptors to nrfx_spim and two spi_buf entries to Zephyr, which
     * is how every SPI peripheral already works. */
    bool (*spi_burst_read)(void *ctx, sb_cs cs, const uint8_t *cmd,
                           size_t cmd_len, uint8_t *rx, size_t rx_len);

    /* ── I2C, shared by the IMU, the PMIC and the time-of-flight sensor ──── */
    bool (*i2c_write)(void *ctx, uint8_t addr, const uint8_t *buf, size_t len);
    bool (*i2c_read)(void *ctx, uint8_t addr, uint8_t reg, uint8_t *buf,
                     size_t len);

    /* ── the few pins that are not on a bus ──────────────────────────────── */
    void (*gpio_set)(void *ctx, uint8_t pin, sb_pin_state s);
    bool (*gpio_get)(void *ctx, uint8_t pin);

    /* ── the taxel front end ─────────────────────────────────────────────── */
    /* The multiplexer select lines and the six amplifier outputs. */
    void (*mux_select)(void *ctx, int channel);     /* -1 disables it        */
    uint16_t (*adc_read)(void *ctx, uint8_t channel);

    void *ctx;
} sb_hal;

/* Pin names, so nothing in a driver carries a bare number. ⚠️ These are indices
 * into whatever the platform layer's pin table is, NOT nRF54L15 pin numbers —
 * the mapping lives with the port, next to the datasheet it came from. */
enum {
    SB_PIN_RADAR_EN = 0,
    SB_PIN_RADAR_IRQ_L,
    SB_PIN_RADAR_IRQ_R,
    SB_PIN_TOF_XSHUT,
    SB_PIN_TOF_INT,
    SB_PIN_IMU_INT1,
    SB_PIN_HALL,
    SB_PIN_PMIC_IRQ,
    SB_PIN_IR_LED_EN,
    SB_PIN_COUNT,
};

#endif /* SB_HAL_H */
