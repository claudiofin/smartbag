#include "sb_power.h"

sb_jeita_profile sb_charge_profile(void)
{
    sb_jeita_profile p = {
        .cold_c = SB_JEITA_COLD_C,
        .cool_c = SB_JEITA_COOL_C,
        .warm_c = SB_JEITA_WARM_C,
        .hot_c = SB_JEITA_HOT_C,
        .full_mw = SB_CHG_FULL_MW,
        .slow_mw = SB_CHG_SLOW_MW,
    };
    return p;
}

sb_charge_decision sb_charge_decide(const sb_charge_input *in)
{
    sb_charge_decision d = {SB_CHG_OFF, SB_CHG_NO_SOURCE, 0};

    if (!in->vbus_present) {
        return d;
    }

    /* ⛔ A THERMISTOR THAT READS OPEN IS NOT A COLD CELL. An unplugged or
     * cracked NTC looks like an extreme temperature, and which extreme depends
     * on which way the divider fails — so it must be its own case and it must
     * stop charging. Treating a missing sensor as "probably fine" is how a
     * temperature loop becomes decoration. */
    if (!in->ntc_valid) {
        d.why = SB_CHG_SENSOR_LOST;
        return d;
    }
    if (in->cell_c < SB_JEITA_COLD_C) {
        d.why = SB_CHG_CELL_TOO_COLD;
        return d;
    }
    if (in->cell_c >= SB_JEITA_HOT_C) {
        d.why = SB_CHG_CELL_TOO_HOT;
        return d;
    }

    /* ⭐ THE INTERLOCK. thermal/budget.py: a watt of charger loss inside a
     * closed bag has nowhere to go — 3 mm of microfibre and foam over the coil,
     * then leather — and the cell sits on top of the coil. Open, the same watt
     * is a rounding error. This single test is the cheapest of the three fixes
     * the analysis proposed and the firmware already had the input for. */
    if (!in->bag_open) {
        d.mode = SB_CHG_SLOW;
        d.why = SB_CHG_BAG_CLOSED;
        d.limit_mw = SB_CHG_SLOW_MW;
        return d;
    }

    /* JEITA's reduced-current bands. ⚠️ Note these are checked AFTER the bag
     * interlock, so a cool cell in a closed bag is still capped by the closed
     * bag: the two limits are not alternatives, the tighter one wins. */
    if (in->cell_c < SB_JEITA_COOL_C || in->cell_c >= SB_JEITA_WARM_C) {
        d.mode = SB_CHG_SLOW;
        d.why = SB_CHG_CELL_MARGINAL;
        d.limit_mw = SB_CHG_SLOW_MW;
        return d;
    }

    d.mode = SB_CHG_FULL;
    d.why = SB_CHG_OK;
    d.limit_mw = SB_CHG_FULL_MW;
    return d;
}

/* ── state of charge ─────────────────────────────────────────────────────────*/

/* ⭐ FOUR POINTS, AND EVERY ONE OF THEM IS ON THE LP523450JU'S OWN DATASHEET.
 * Two are the ends — 3.0 V cut-off, 4.2 V max charge — and two come from a line
 * nobody reads as curve data: "Delivery State of Charge: Max. 30% (3.75-3.79V);
 * Optional 60% (3.85-3.95V)". A cell shipped at a stated percentage and a
 * stated voltage is a cell telling you where those two meet, and the midpoint
 * of each band is the number it is telling you.
 *
 * ⚠️ WHAT THIS STILL DOES NOT KNOW is the shape between 3.0 and 3.77 V, which
 * on a lithium cell is the long flat middle and most of the capacity. Straight
 * lines between the points are the honest reading of a datasheet that gives
 * four; a product ships either a characterised table or Nordic's fuel-gauge
 * library, and both of those need the cell on a bench.
 */
static const struct { uint16_t mv; uint8_t pct; } SOC_CURVE[] = {
    { SB_CELL_EMPTY_MV, 0 },
    { 3770, 30 },        /* midpoint of the 3.75-3.79 V delivery band */
    { 3900, 60 },        /* midpoint of the 3.85-3.95 V delivery band */
    { SB_CELL_FULL_MV, 100 },
};

uint8_t sb_soc_from_ocv_mv(uint16_t mv)
{
    if (mv <= SOC_CURVE[0].mv) {
        return 0;
    }
    const int n = (int)(sizeof(SOC_CURVE) / sizeof(SOC_CURVE[0]));
    if (mv >= SOC_CURVE[n - 1].mv) {
        return 100;
    }
    for (int i = 1; i < n; i++) {
        if (mv < SOC_CURVE[i].mv) {
            const int32_t dv = SOC_CURVE[i].mv - SOC_CURVE[i - 1].mv;
            const int32_t dp = SOC_CURVE[i].pct - SOC_CURVE[i - 1].pct;
            return (uint8_t)(SOC_CURVE[i - 1].pct +
                             (int32_t)(mv - SOC_CURVE[i - 1].mv) * dp / dv);
        }
    }
    return 100;
}

uint16_t sb_soc_ocv_mv(uint16_t terminal_mv, int16_t current_ma)
{
    /* ⛔ THE SIGN IS THE WHOLE POINT. Charging pushes the terminal ABOVE the
     * open-circuit voltage and discharging pulls it below, so the correction is
     * subtracted when charging and added when discharging. Getting it backwards
     * doubles the error instead of removing it — and at 1 A into 180 mOhm that
     * is 360 mV, which is a quarter of this cell's entire range. */
    const int32_t drop_mv = (int32_t)current_ma * SB_CELL_IMPEDANCE_MOHM / 1000;
    int32_t ocv = (int32_t)terminal_mv - drop_mv;
    if (ocv < 0) {
        ocv = 0;
    }
    if (ocv > 0xFFFF) {
        ocv = 0xFFFF;
    }
    return (uint16_t)ocv;
}
