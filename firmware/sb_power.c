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
