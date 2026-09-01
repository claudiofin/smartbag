/* The PMIC, through Nordic's own driver rather than through invented registers.
 *
 * ⛔ THE TEMPTATION HERE IS A REGISTER MAP FROM MEMORY. Write `i2c_write(0x6b,
 * 0x0303, 0x01)` and the charger appears to come on; get one offset wrong and it
 * comes on with the wrong current limit, into a cell whose datasheet says 1.0 C.
 * This project spent a long time removing exactly that kind of invention from
 * its bill of materials, and it would be a strange place to reintroduce it.
 *
 * ⭐ SO THE THRESHOLDS ARE DEVICETREE AND THE ACTIONS ARE THE DRIVER'S. The JEITA
 * bands, the termination voltage and the 1.0 C charge current are in
 * boards/smartbag.overlay, which hardware/generate_pinmap.py writes from the
 * cell's own datasheet; what is left for C is turning sb_charge_decide()'s
 * answer into two calls.
 *
 * ⚠️ IT IS A SENSOR DRIVER, NOT A CHARGER DRIVER, AND THAT WAS WORTH FINDING OUT
 * BY COMPILING. This file first used Zephyr's charger API — charger_set_prop(),
 * CHARGER_PROP_CONSTANT_CHARGE_CURRENT_UA — which reads correctly and does not
 * link: in this tree nordic,npm1300-charger is a binding under
 * dts/bindings/sensor, and it is driven with sensor_attr_set().
 *
 * ⭐ THE MAPPING IS BETTER THAN THE ONE IT REPLACED, TOO. The attribute that sets
 * a current is the VBUS INPUT limit, not the charge current — and the input is
 * exactly what the policy constrains. thermal/budget.py's closed-bag figure is
 * watts arriving at the coil; the charge current into the cell is the cell's own
 * business and stays in devicetree where its datasheet put it.
 */
#include <zephyr/kernel.h>
#include <zephyr/device.h>
#include <zephyr/drivers/sensor.h>
#include <zephyr/logging/log.h>

#include "sb_power.h"

LOG_MODULE_REGISTER(npm1300, CONFIG_LOG_DEFAULT_LEVEL);

static const struct device *const charger =
	DEVICE_DT_GET(DT_NODELABEL(npm1300_charger));

/* VBUS is nominally 5 V out of the Qi receiver, so the policy's milliwatts
 * become milliamps by dividing by five. ⚠️ The driver snaps this to the nearest
 * limit the hardware actually has, which is a short list. */
#define VBUS_MV 5000

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
	 * it. That branch is one of the 276 host assertions.
	 */
	if (t.val1 < -30 || t.val1 > 90) {
		LOG_WRN("cell NTC reads %d C — treating as disconnected", t.val1);
		return 0;
	}
	*valid = true;
	return (int16_t)t.val1;
}

void sb_pmic_apply(const sb_charge_decision *d)
{
	struct sensor_value v;

	if (!device_is_ready(charger)) {
		return;
	}

	if (d->mode == SB_CHG_OFF) {
		v.val1 = 0;
		v.val2 = 0;
		sensor_attr_set(charger, SENSOR_CHAN_GAUGE_DESIRED_CHARGING_CURRENT,
				SENSOR_ATTR_CONFIGURATION, &v);
		return;
	}

	/* How much may arrive, in amps and microamps. */
	const uint32_t ua = (uint32_t)d->limit_mw * 1000U / VBUS_MV * 1000U;

	v.val1 = (int32_t)(ua / 1000000U);
	v.val2 = (int32_t)(ua % 1000000U);
	sensor_attr_set(charger, SENSOR_CHAN_CURRENT, SENSOR_ATTR_UPPER_THRESH, &v);

	v.val1 = 1;
	v.val2 = 0;
	sensor_attr_set(charger, SENSOR_CHAN_GAUGE_DESIRED_CHARGING_CURRENT,
			SENSOR_ATTR_CONFIGURATION, &v);
}

/* ⛔ STATE OF CHARGE IS NOT A THING THIS PMIC MEASURES. The nPM1300 reports
 * cell VOLTAGE, current and temperature; turning those into a percentage is a
 * model of the cell, and Nordic ship one as a separate library rather than in
 * the driver.
 *
 * ⭐ SO THE MODEL LIVES IN ../sb_power.c WHERE IT CAN BE TESTED, and this
 * function is two sensor reads and a call. What it used to be was a straight
 * line from 3.0 V to 4.2 V, which reads the cell's own stated 30% delivery
 * state as 64% — see the comment on SOC_CURVE for the four datasheet points
 * that replaced it, and test_sb_power.c for the assertions that hold it there.
 *
 * ⚠️ AND THE CURRENT MATTERS AS MUCH AS THE VOLTAGE. 180 mOhm of pack impedance
 * against a 1 A charge is 180 mV of lift; reading the terminal voltage while
 * charging and calling it state of charge is how a gauge jumps twenty points
 * when a bag is put on its pad. If the current cannot be read the correction is
 * zero, which is the old behaviour and is right for a resting cell.
 */
uint8_t sb_pmic_battery_pct(void)
{
	struct sensor_value v;

	if (!device_is_ready(charger) || sensor_sample_fetch(charger) != 0) {
		return 0;
	}
	if (sensor_channel_get(charger, SENSOR_CHAN_GAUGE_VOLTAGE, &v) != 0) {
		return 0;
	}
	const int mv = v.val1 * 1000 + v.val2 / 1000;

	int ma = 0;
	struct sensor_value i;
	if (sensor_channel_get(charger, SENSOR_CHAN_GAUGE_AVG_CURRENT, &i) == 0) {
		ma = i.val1 * 1000 + i.val2 / 1000;
	}
	if (mv < 0 || mv > 0xFFFF) {
		return 0;
	}
	return sb_soc_from_ocv_mv(sb_soc_ocv_mv((uint16_t)mv, (int16_t)ma));
}
