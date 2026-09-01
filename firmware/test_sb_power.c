/* Host tests for the charge policy.
 *
 * ⭐ WHAT IS WORTH TESTING is not that an enum comes back. It is that the one
 * finding this project never closed — a cell at 60 °C in a shut bag — cannot
 * happen through any combination of inputs, including the ones nobody thought
 * of: a thermistor that has fallen off, a bag that closes mid-charge, a cell
 * that is cold rather than hot.
 */
#include "sb_power.h"

#include <stdio.h>

static int failures, checks;

#define CHECK(cond, ...)                                                       \
    do {                                                                       \
        checks++;                                                              \
        if (!(cond)) {                                                         \
            failures++;                                                        \
            printf("  FAIL  %s:%d  ", __func__, __LINE__);                     \
            printf(__VA_ARGS__);                                               \
            printf("\n");                                                      \
        }                                                                      \
    } while (0)

static sb_charge_decision decide(bool vbus, bool open, int c, bool ntc)
{
    sb_charge_input in = {.vbus_present = vbus, .bag_open = open,
                          .cell_c = (int16_t)c, .ntc_valid = ntc};
    return sb_charge_decide(&in);
}

static void test_no_source_is_off(void)
{
    CHECK(decide(false, true, 25, true).mode == SB_CHG_OFF, "charging with no pad");
}

static void test_the_closed_bag_never_gets_full_current(void)
{
    /* ⛔ THE FINDING, AS AN ASSERTION. Sweep every plausible cell temperature
     * with the bag shut: not one of them may return full current, because a
     * closed bag cannot dissipate the loss at any temperature the cell happens
     * to start from. */
    for (int c = -10; c <= 60; c++) {
        sb_charge_decision d = decide(true, false, c, true);
        CHECK(d.mode != SB_CHG_FULL,
              "closed bag charged at full current at %d C", c);
        CHECK(d.limit_mw <= SB_CHG_SLOW_MW,
              "closed bag allowed %u mW at %d C", d.limit_mw, c);
    }
}

static void test_open_bag_at_room_temperature_charges_properly(void)
{
    sb_charge_decision d = decide(true, true, 25, true);
    CHECK(d.mode == SB_CHG_FULL, "mode %d", d.mode);
    CHECK(d.why == SB_CHG_OK, "why %d", d.why);
    CHECK(d.limit_mw == SB_CHG_FULL_MW, "%u mW", d.limit_mw);
}

static void test_the_hot_cell_stops_charging_entirely(void)
{
    /* Not throttled — stopped. Above the JEITA ceiling there is no safe
     * current, and the difference between "slower" and "none" is the whole
     * point of having a limit.
     *
     * ⚠️ The ceiling is SB_CELL_ABS_MAX_C and not SB_CELL_LIMIT_C. Those were
     * the same number while the cell was a generic one; the real cell derates
     * between 45 and 55 rather than stopping, so starting this loop at 45 was
     * testing that the firmware refuses a current its own cell permits. */
    for (int c = SB_CELL_ABS_MAX_C; c <= 70; c++) {
        sb_charge_decision d = decide(true, true, c, true);
        CHECK(d.mode == SB_CHG_OFF, "charging at %d C", c);
        CHECK(d.why == SB_CHG_CELL_TOO_HOT, "why %d at %d C", d.why, c);
    }
}

static void test_the_warm_cell_derates_rather_than_stopping(void)
{
    /* ⭐ +45 to +55 C is a REAL BAND, straight off the LP523450JU datasheet:
     * 0.5 C, not zero. A bag left on a sunny table is in it, and a charger that
     * simply gave up there would look broken rather than careful. */
    for (int c = SB_CELL_LIMIT_C; c < SB_CELL_ABS_MAX_C; c++) {
        sb_charge_decision d = decide(true, true, c, true);
        CHECK(d.mode == SB_CHG_SLOW, "mode %d at %d C", d.mode, c);
        CHECK(d.why == SB_CHG_CELL_MARGINAL, "why %d at %d C", d.why, c);
    }
}

static void test_the_cold_cell_stops_too(void)
{
    /* ⚠️ Charging a lithium cell below 0 °C plates lithium metal on the anode.
     * It is a slower failure than overheating and a more permanent one. */
    for (int c = -20; c < SB_JEITA_COLD_C; c++) {
        CHECK(decide(true, true, c, true).mode == SB_CHG_OFF,
              "charging a cell at %d C", c);
    }
}

static void test_a_missing_thermistor_stops_charging(void)
{
    /* ⛔ The case that makes a temperature loop real. An NTC that has come
     * unstuck reads as an extreme, and which extreme depends on how the divider
     * failed — so it cannot be inferred, only detected. */
    for (int c = -40; c <= 80; c += 10) {
        sb_charge_decision d = decide(true, true, c, false);
        CHECK(d.mode == SB_CHG_OFF, "charged with no sensor, reading %d C", c);
        CHECK(d.why == SB_CHG_SENSOR_LOST, "why %d", d.why);
    }
}

static void test_jeita_bands_reduce_rather_than_stop(void)
{
    for (int c = SB_JEITA_COLD_C; c < SB_JEITA_COOL_C; c++) {
        CHECK(decide(true, true, c, true).mode == SB_CHG_SLOW,
              "cool band at %d C gave the wrong mode", c);
    }
    for (int c = SB_JEITA_WARM_C; c < SB_JEITA_HOT_C; c++) {
        CHECK(decide(true, true, c, true).mode == SB_CHG_SLOW,
              "warm band at %d C gave the wrong mode", c);
    }
}

static void test_the_tighter_limit_wins(void)
{
    /* A cool cell in a closed bag is limited by the bag, not offered the
     * cool-band allowance as if the two were alternatives. */
    sb_charge_decision d = decide(true, false, 5, true);
    CHECK(d.mode == SB_CHG_SLOW, "mode %d", d.mode);
    CHECK(d.why == SB_CHG_BAG_CLOSED, "why %d — the bag should win", d.why);
}

static void test_the_profile_matches_the_thermal_model(void)
{
    sb_jeita_profile p = sb_charge_profile();
    /* ⚠️ These numbers moved when BT1 stopped being a shape and became a part.
     * The ceiling is the cell's own absolute charge limit and the bands are its
     * own; the closed-bag figure is what thermal/budget.py now inverts its model
     * to, which changed because the coil moved out from under the cell. */
    CHECK(p.cool_c == 15, "JEITA cool band %d", p.cool_c);
    CHECK(p.warm_c == 45, "JEITA warm band %d", p.warm_c);
    CHECK(p.hot_c == 55, "JEITA ceiling %d", p.hot_c);
    CHECK(p.slow_mw == 2900, "closed-bag ceiling %u mW", p.slow_mw);
    CHECK(p.full_mw == 5000, "full rate %u mW", p.full_mw);
    printf("  note  closed bag capped at %u mW; thermal/budget.py inverts its "
           "own model to 2.9 W\n", p.slow_mw);
}

int main(void)
{
    printf("sb_power: the charge policy\n");
    test_no_source_is_off();
    test_the_closed_bag_never_gets_full_current();
    test_open_bag_at_room_temperature_charges_properly();
    test_the_hot_cell_stops_charging_entirely();
    test_the_warm_cell_derates_rather_than_stopping();
    test_the_cold_cell_stops_too();
    test_a_missing_thermistor_stops_charging();
    test_jeita_bands_reduce_rather_than_stop();
    test_the_tighter_limit_wins();
    test_the_profile_matches_the_thermal_model();
    printf("%d checks, %d failures\n", checks, failures);
    return failures ? 1 : 0;
}
