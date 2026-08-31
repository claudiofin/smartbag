#include "sb_sensors.h"

#include <string.h>

void sb_sensors_init(sb_sensors *s)
{
    memset(s, 0, sizeof(*s));
}

/* ── time-of-flight ──────────────────────────────────────────────────────── */
sb_sens_status sb_tof_up(sb_sensors *s, const sb_hal *hal)
{
    /* ⛔ ORDER MATTERS AND IT IS NOT THE OBVIOUS ONE. XSHUT is driven LOW first
     * even though the part is already off: the rail may still be decaying from
     * a previous burst, and releasing a shutdown pin into a half-powered part
     * is exactly the case the datasheet warns about. Low, rail, settle, high. */
    hal->gpio_set(hal->ctx, SB_PIN_TOF_XSHUT, SB_PIN_LOW);
    hal->delay_us(hal->ctx, SB_TOF_RAIL_SETTLE_MS * 1000);
    hal->gpio_set(hal->ctx, SB_PIN_TOF_XSHUT, SB_PIN_HIGH);
    hal->delay_us(hal->ctx, SB_TOF_BOOT_MS * 1000);

    /* Identify it before believing anything else it says. */
    uint8_t id[2] = {0, 0};
    if (!hal->i2c_read(hal->ctx, SB_TOF_I2C_ADDR, 0x01, id, 2)) {
        return SB_SENS_NO_REPLY;
    }
    s->tof_up = true;
    return SB_SENS_OK;
}

void sb_tof_down(sb_sensors *s, const sb_hal *hal)
{
    hal->gpio_set(hal->ctx, SB_PIN_TOF_XSHUT, SB_PIN_LOW);
    s->tof_up = false;
}

sb_sens_status sb_tof_range(sb_sensors *s, const sb_hal *hal, uint16_t *mm)
{
    if (!s->tof_up) {
        return SB_SENS_NOT_READY;
    }
    uint8_t go[3] = {0x00, 0x87, 0x40};        /* start ranging */
    if (!hal->i2c_write(hal->ctx, SB_TOF_I2C_ADDR, go, sizeof(go))) {
        return SB_SENS_NO_REPLY;
    }

    /* ⛔ A BOUNDED WAIT, NOT A SPIN. A sensor that has come off its flex never
     * raises its interrupt, and a loop with no deadline turns that into a
     * device that stops responding rather than one that reports a fault. The
     * counter exists so the failure is visible over BLE instead of silent. */
    uint32_t start = hal->now_ms(hal->ctx);
    while (!hal->gpio_get(hal->ctx, SB_PIN_TOF_INT)) {
        if (hal->now_ms(hal->ctx) - start >= SB_TOF_TIMEOUT_MS) {
            s->tof_timeouts++;
            return SB_SENS_TIMEOUT;
        }
        hal->delay_us(hal->ctx, 500);
    }

    uint8_t d[2];
    if (!hal->i2c_read(hal->ctx, SB_TOF_I2C_ADDR, 0x96, d, 2)) {
        return SB_SENS_NO_REPLY;
    }
    *mm = (uint16_t)((d[0] << 8) | d[1]);
    return SB_SENS_OK;
}

/* ── radar ───────────────────────────────────────────────────────────────── */
sb_sens_status sb_radar_up(sb_sensors *s, const sb_hal *hal)
{
    hal->gpio_set(hal->ctx, SB_PIN_RADAR_EN, SB_PIN_HIGH);
    hal->delay_us(hal->ctx, SB_RADAR_ENABLE_MS * 1000);

    /* ⚠️ BOTH sensors are probed, because ENABLE is shared: if one of them is
     * dead the other is still usable, and the map is then built from one
     * viewpoint instead of two. Refusing to come up at all because half the
     * hardware answered would be worse than a degraded map. */
    int alive = 0;
    for (int i = 0; i < 2; i++) {
        uint8_t tx[4] = {0xF0, 0, 0, 0}, rx[4] = {0};
        if (hal->spi_xfer(hal->ctx, i ? SB_CS_RADAR_R : SB_CS_RADAR_L,
                          tx, rx, sizeof(tx))) {
            alive++;
        }
    }
    if (alive == 0) {
        hal->gpio_set(hal->ctx, SB_PIN_RADAR_EN, SB_PIN_LOW);
        return SB_SENS_NO_REPLY;
    }
    s->radar_up = true;
    return SB_SENS_OK;
}

void sb_radar_down(sb_sensors *s, const sb_hal *hal)
{
    hal->gpio_set(hal->ctx, SB_PIN_RADAR_EN, SB_PIN_LOW);
    s->radar_up = false;
}

sb_sens_status sb_radar_measure(sb_sensors *s, const sb_hal *hal,
                                sb_radar_side side, uint16_t *bins, int n)
{
    if (!s->radar_up) {
        return SB_SENS_NOT_READY;
    }
    sb_cs cs = (side == SB_RADAR_LEFT) ? SB_CS_RADAR_L : SB_CS_RADAR_R;
    uint8_t pin = (side == SB_RADAR_LEFT) ? SB_PIN_RADAR_IRQ_L
                                          : SB_PIN_RADAR_IRQ_R;

    uint8_t go[2] = {0xA1, 0x01};
    uint8_t junk[2];
    if (!hal->spi_xfer(hal->ctx, cs, go, junk, sizeof(go))) {
        return SB_SENS_NO_REPLY;
    }

    uint32_t start = hal->now_ms(hal->ctx);
    while (!hal->gpio_get(hal->ctx, pin)) {
        if (hal->now_ms(hal->ctx) - start >= SB_RADAR_TIMEOUT_MS) {
            s->radar_timeouts++;
            return SB_SENS_TIMEOUT;
        }
        hal->delay_us(hal->ctx, 200);
    }

    for (int i = 0; i < n; i++) {
        uint8_t tx[2] = {0xB0, (uint8_t)i}, rx[2] = {0};
        if (!hal->spi_xfer(hal->ctx, cs, tx, rx, sizeof(rx))) {
            return SB_SENS_NO_REPLY;
        }
        bins[i] = (uint16_t)((rx[0] << 8) | rx[1]);
    }
    return SB_SENS_OK;
}
