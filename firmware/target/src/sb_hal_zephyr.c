/* The nine functions sb_hal.h declares, on an nRF54L15 under Zephyr.
 *
 * ⛔ THIS IS THE FILE THAT DID NOT EXIST. sb_hal.h has said so since it was
 * written — "everything below is a function pointer and none of it is
 * implemented here" — and that was the honest size of the remaining silicon
 * work: nine functions, plus a stack. Everything above them was already written
 * and under 276 host assertions against a simulated bus.
 *
 * ⭐ NOTHING ABOVE THIS LINE CHANGES TO SUIT IT. The vtable is filled in here
 * and handed down; sb_sensors.c and sb_fsr.c are compiled from the same source
 * the host tests build, unmodified. That is the entire argument for having had
 * a HAL in the first place, and it is only worth anything if the target build
 * does not fork them.
 *
 * ⚠️ THIS HAS NOT BEEN COMPILED. There is no nRF Connect SDK and no ARM
 * toolchain on the machine it was written on, so it has been written against
 * the Zephyr API rather than against a compiler. Treat every line as a first
 * draft that has never met silicon — the arrangement is sound, the spelling of
 * the API calls is where the bugs will be. firmware/target/README.md says what
 * to run to find out.
 */
#include <zephyr/kernel.h>
#include <zephyr/device.h>
#include <zephyr/drivers/gpio.h>
#include <zephyr/drivers/spi.h>
#include <zephyr/drivers/i2c.h>
#include <zephyr/drivers/adc.h>
#include <zephyr/logging/log.h>

#include "sb_hal.h"
#include "sb_pinmap.h"

LOG_MODULE_REGISTER(sb_hal, CONFIG_LOG_DEFAULT_LEVEL);

/* ── the three GPIO ports, by devicetree label ───────────────────────────── */
static const struct device *const ports[3] = {
    DEVICE_DT_GET(DT_NODELABEL(gpio0)),
    DEVICE_DT_GET(DT_NODELABEL(gpio1)),
    DEVICE_DT_GET(DT_NODELABEL(gpio2)),
};

static const struct device *const spi_bus = DEVICE_DT_GET(DT_NODELABEL(spi00));
static const struct device *const i2c_bus = DEVICE_DT_GET(DT_NODELABEL(i2c20));
static const struct device *const saadc = DEVICE_DT_GET(DT_NODELABEL(adc));

/* ⚠️ Chip select is a plain GPIO and not the SPI driver's cs field, because
 * there are three devices and one CSN pin. The driver would drive its own line
 * on every transfer and the radar would never see its select go low. */
static struct spi_config spi_cfg = {
    /* A121 datasheet section 8: SPI mode 0, up to 50 MHz. The SoC's SPIM00 does
     * 32 MHz, which is the reason SPI_SCK/MOSI/MISO are not allowed to move off
     * P2.01/02/04 — see the comment in hardware/netlist.py. */
    .frequency = 32000000,
    .operation = SPI_WORD_SET(8) | SPI_TRANSFER_MSB | SPI_OP_MODE_MASTER,
    .slave = 0,
    .cs = { 0 },
};

static int cfg_out(uint8_t port, uint8_t pin, int flags)
{
    if (port >= ARRAY_SIZE(ports) || !device_is_ready(ports[port])) {
        return -ENODEV;
    }
    return gpio_pin_configure(ports[port], pin, flags);
}

/* ── time ────────────────────────────────────────────────────────────────── */
static uint32_t hal_now_ms(void *ctx)
{
    ARG_UNUSED(ctx);
    return (uint32_t)k_uptime_get_32();
}

static void hal_delay_us(void *ctx, uint32_t us)
{
    ARG_UNUSED(ctx);
    /* ⚠️ Busy-wait, not k_sleep. The callers are bring-up sequences with
     * microsecond settling times out of a datasheet; handing those to the
     * scheduler turns a 10 us wait into a tick. */
    k_busy_wait(us);
}

/* ── SPI ─────────────────────────────────────────────────────────────────── */
static bool hal_spi_xfer(void *ctx, sb_cs cs, const uint8_t *tx, uint8_t *rx,
                         size_t len)
{
    ARG_UNUSED(ctx);
    if (cs >= SB_CS_COUNT || !device_is_ready(spi_bus)) {
        return false;
    }
    const struct spi_buf tx_buf = { .buf = (void *)tx, .len = len };
    const struct spi_buf rx_buf = { .buf = rx, .len = len };
    const struct spi_buf_set tx_set = { .buffers = &tx_buf, .count = tx ? 1 : 0 };
    const struct spi_buf_set rx_set = { .buffers = &rx_buf, .count = rx ? 1 : 0 };

    const uint8_t port = sb_cs_pins[cs].port, pin = sb_cs_pins[cs].pin;
    gpio_pin_set_raw(ports[port], pin, 0);          /* select: active low */
    int err = spi_transceive(spi_bus, &spi_cfg, tx ? &tx_set : NULL,
                             rx ? &rx_set : NULL);
    gpio_pin_set_raw(ports[port], pin, 1);
    if (err) {
        LOG_WRN("spi cs=%d len=%u err=%d", (int)cs, (unsigned)len, err);
    }
    return err == 0;
}

/* ── I2C ─────────────────────────────────────────────────────────────────── */
static bool hal_i2c_write(void *ctx, uint8_t addr, const uint8_t *buf,
                          size_t len)
{
    ARG_UNUSED(ctx);
    if (!device_is_ready(i2c_bus)) {
        return false;
    }
    return i2c_write(i2c_bus, buf, len, addr) == 0;
}

static bool hal_i2c_read(void *ctx, uint8_t addr, uint8_t reg, uint8_t *buf,
                         size_t len)
{
    ARG_UNUSED(ctx);
    if (!device_is_ready(i2c_bus)) {
        return false;
    }
    return i2c_write_read(i2c_bus, addr, &reg, 1, buf, len) == 0;
}

/* ── GPIO ────────────────────────────────────────────────────────────────── */
static void hal_gpio_set(void *ctx, uint8_t pin_id, sb_pin_state s)
{
    ARG_UNUSED(ctx);
    if (pin_id >= SB_PIN_COUNT) {
        return;
    }
    gpio_pin_set_raw(ports[sb_pinmap[pin_id].port], sb_pinmap[pin_id].pin,
                     s == SB_PIN_HIGH);
}

static bool hal_gpio_get(void *ctx, uint8_t pin_id)
{
    ARG_UNUSED(ctx);
    if (pin_id >= SB_PIN_COUNT) {
        return false;
    }
    return gpio_pin_get_raw(ports[sb_pinmap[pin_id].port],
                            sb_pinmap[pin_id].pin) == 1;
}

/* ── the FSR multiplexer ─────────────────────────────────────────────────── */
static void hal_mux_select(void *ctx, int channel)
{
    ARG_UNUSED(ctx);
    /* ⛔ DISABLE FIRST, THEN ADDRESS. The CD74HC4067's four select lines do not
     * change together, so an enabled multiplexer walks through intermediate
     * channels on its way to the one asked for — connecting column 7 to a row
     * amplifier for a few nanoseconds on the way from 6 to 8. sb_fsr.c's whole
     * model of the matrix assumes one column is driven at a time. */
    gpio_pin_set_raw(ports[SB_MUX_EN_PORT], SB_MUX_EN_PIN, 1);   /* EN is low-true */
    if (channel < 0) {
        return;
    }
    for (int i = 0; i < 4; i++) {
        gpio_pin_set_raw(ports[sb_mux_sel[i].port], sb_mux_sel[i].pin,
                         (channel >> i) & 1);
    }
    gpio_pin_set_raw(ports[SB_MUX_EN_PORT], SB_MUX_EN_PIN, 0);
}

/* ── SAADC ───────────────────────────────────────────────────────────────── */
static uint16_t hal_adc_read(void *ctx, uint8_t channel)
{
    ARG_UNUSED(ctx);
    if (channel >= ARRAY_SIZE(sb_adc_rows) || !device_is_ready(saadc)) {
        return 0;
    }
    int16_t sample = 0;
    const struct adc_sequence seq = {
        .channels = BIT(channel),
        .buffer = &sample,
        .buffer_size = sizeof(sample),
        .resolution = 12,
        .oversampling = 2,       /* 4x: the front end is quiet, the bag is not */
    };
    if (adc_read(saadc, &seq) != 0) {
        return 0;
    }
    return sample < 0 ? 0 : (uint16_t)sample;
}

/* ── bring the ports up and hand over the vtable ─────────────────────────── */
int sb_hal_zephyr_init(sb_hal *hal)
{
    for (size_t i = 0; i < ARRAY_SIZE(ports); i++) {
        if (!device_is_ready(ports[i])) {
            LOG_ERR("gpio%u not ready", (unsigned)i);
            return -ENODEV;
        }
    }

    /* Outputs the logic drives. ⚠️ Chip selects come up HIGH — a select line
     * that floats or starts low puts two radars on the bus at once. */
    for (int i = 0; i < SB_CS_COUNT; i++) {
        cfg_out(sb_cs_pins[i].port, sb_cs_pins[i].pin,
                GPIO_OUTPUT_HIGH);
    }
    for (int i = 0; i < 4; i++) {
        cfg_out(sb_mux_sel[i].port, sb_mux_sel[i].pin, GPIO_OUTPUT_LOW);
    }
    cfg_out(SB_MUX_EN_PORT, SB_MUX_EN_PIN, GPIO_OUTPUT_HIGH);  /* disabled */
    cfg_out(sb_pinmap[SB_PIN_RADAR_EN].port, sb_pinmap[SB_PIN_RADAR_EN].pin,
            GPIO_OUTPUT_LOW);
    cfg_out(sb_pinmap[SB_PIN_IR_LED_EN].port, sb_pinmap[SB_PIN_IR_LED_EN].pin,
            GPIO_OUTPUT_LOW);
    cfg_out(sb_pinmap[SB_PIN_TOF_XSHUT].port, sb_pinmap[SB_PIN_TOF_XSHUT].pin,
            GPIO_OUTPUT_LOW);   /* the ToF is held in reset until asked for */

    /* Inputs. ⚠️ The Hall sensor is open-drain (DRV5032 datasheet 8.3.2) and
     * needs the pull-up; the interrupt lines have their own on the board. */
    cfg_out(sb_pinmap[SB_PIN_HALL].port, sb_pinmap[SB_PIN_HALL].pin,
            GPIO_INPUT | GPIO_PULL_UP);
    static const int inputs[] = { SB_PIN_RADAR_IRQ_L, SB_PIN_RADAR_IRQ_R,
                                  SB_PIN_TOF_INT, SB_PIN_IMU_INT1,
                                  SB_PIN_PMIC_IRQ };
    for (size_t i = 0; i < ARRAY_SIZE(inputs); i++) {
        cfg_out(sb_pinmap[inputs[i]].port, sb_pinmap[inputs[i]].pin, GPIO_INPUT);
    }

    *hal = (sb_hal){
        .now_ms = hal_now_ms,
        .delay_us = hal_delay_us,
        .spi_xfer = hal_spi_xfer,
        .i2c_write = hal_i2c_write,
        .i2c_read = hal_i2c_read,
        .gpio_set = hal_gpio_set,
        .gpio_get = hal_gpio_get,
        .mux_select = hal_mux_select,
        .adc_read = hal_adc_read,
        .ctx = NULL,
    };
    return 0;
}
