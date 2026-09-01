/* The PMIC, through Nordic's own driver rather than through invented registers.
 *
 * ⛔ THE TEMPTATION HERE IS A REGISTER MAP FROM MEMORY. Write `i2c_write(0x6b,
 * 0x0303, 0x01)` and the charger appears to come on; get one offset wrong and it
 * comes on with the wrong current limit, into a cell whose datasheet says 1.0 C.
 * This project spent a long time removing exactly that kind of invention from
 * its bill of materials, and it would be a strange place to reintroduce it.
 *
 * ⭐ SO THE THRESHOLDS ARE DEVICETREE AND THE ACTIONS ARE THE CHARGER API. The
 * JEITA bands and the termination voltage are in boards/smartbag.overlay, which
 * hardware/generate_pinmap.py writes from the cell's own datasheet; what is left
 * for C is turning sb_charge_decide()'s answer into a current limit.
 *
 * ⚠️ NOT COMPILED — see README.md.
 */
#include <zephyr/kernel.h>
#include <zephyr/device.h>
#include <zephyr/drivers/charger.h>
#include <zephyr/drivers/sensor.h>
#include <zephyr/logging/log.h>

#include "sb_power.h"

LOG_MODULE_REGISTER(npm1300, CONFIG_LOG_DEFAULT_LEVEL);

static const struct device *const charger =
    DEVICE_DT_GET(DT_NODELABEL(npm1300_charger));

bool sb_pmic_ready(void)
{
    return device_is_ready(charger);
}

/* ⚠️ Returns the CELL's temperature, not the die's. They are different numbers
 * and the policy is about the first: the thermistor is in the pack, on pin 3 of
 * the harness, which is the entire reason J2 has three ways. */
int16_t sb_pmic_cell_temp_c(bool *valid)
{
    struct sensor_value t;
    *valid = false;
    if (!device_is_ready(charger)) {
        return 0;
    }
    if (sensor_sample_fetch(charger) != 0) {
        return 0;
    }
    if (sensor_channel_get(charger, SENSOR_CHAN_GAUGE_TEMP, &t) != 0) {
        return 0;
    }
    /* ⛔ AN OPEN THERMISTOR READS AS A PLAUSIBLE TEMPERATURE. A disconnected NTC
     * pulls the divider to one rail, which the PMIC converts into a number at
     * the end of its range rather than into an error — so "very cold" and "not
     * plugged in" look the same. Anything outside what a bag can physically be
     * is treated as a lost sensor, and sb_charge_decide() refuses to charge on
     * it. That branch is one of the 276 host assertions. */
    if (t.val1 < -30 || t.val1 > 90) {
        LOG_WRN("cell NTC reads %d C — treating as disconnected", t.val1);
        return 0;
    }
    *valid = true;
    return (int16_t)t.val1;
}

void sb_pmic_apply(const sb_charge_decision *d)
{
    if (!device_is_ready(charger)) {
        return;
    }
    const union charger_propval off = { .status = CHARGER_STATUS_NOT_CHARGING };
    const union charger_propval on = { .status = CHARGER_STATUS_CHARGING };

    if (d->mode == SB_CHG_OFF) {
        charger_set_prop(charger, CHARGER_PROP_STATUS, &off);
        return;
    }
    /* mW at the pad into mA into the cell: the rectifier and the buck are about
     * 80% together (thermal/budget.py's QI_EFFICIENCY) and the cell charges at
     * roughly 3.9 V through the constant-current phase. ⚠️ Clamped to the cell's
     * own 1.0 C whatever the pad offers — a 15 W pad does not make this cell
     * charge faster, it makes it fail IEC62133 differently. */
    uint32_t ua = (uint32_t)d->limit_mw * 800 / 3900;   /* mW -> mA, x1000 */
    if (ua > SB_CELL_FULL_MA * 1000u) {
        ua = SB_CELL_FULL_MA * 1000u;
    }
    const union charger_propval cur = { .const_charge_current_ua = ua };
    charger_set_prop(charger, CHARGER_PROP_CONSTANT_CHARGE_CURRENT_UA, &cur);
    charger_set_prop(charger, CHARGER_PROP_STATUS, &on);
}
