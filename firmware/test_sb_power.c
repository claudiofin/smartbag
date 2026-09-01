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


/* ── the fuel gauge ────────────────────────────────────────────────────────── */
static void test_the_curve_ends_where_the_cell_does(void)
{
    CHECK(sb_soc_from_ocv_mv(3000) == 0, "%u%% at the discharge cut-off",
          sb_soc_from_ocv_mv(3000));
    CHECK(sb_soc_from_ocv_mv(2500) == 0, "reported charge below cut-off");
    CHECK(sb_soc_from_ocv_mv(4200) == 100, "%u%% at max charge voltage",
          sb_soc_from_ocv_mv(4200));
    CHECK(sb_soc_from_ocv_mv(4500) == 100, "went above 100%%");
}

static void test_the_two_delivery_states_are_where_the_cell_says(void)
{
    /* ⭐ THIS IS THE TEST THE LINEAR MAP FAILED. The datasheet ships this cell
     * at 30% and 3.75-3.79 V, and at 60% and 3.85-3.95 V. Anything calling
     * itself a gauge has to agree with the cell about its own delivery state. */
    for (uint16_t mv = 3750; mv <= 3790; mv += 10) {
        const uint8_t p = sb_soc_from_ocv_mv(mv);
        CHECK(p >= 25 && p <= 35, "%u mV reads %u%%, cell says ~30%%", mv, p);
    }
    /* ⚠️ THE SECOND BAND IS 100 mV WIDE AND THAT IS THE DATASHEET'S TOLERANCE,
     * NOT A CLAIM THAT EVERY VOLTAGE IN IT IS 60%. A cell shipped at 60% will
     * measure somewhere inside it; what has to hold is that the middle reads
     * 60 and the edges stay near it. Asserting the whole band at 60 was this
     * test being wrong about the datasheet rather than the curve being wrong. */
    CHECK(sb_soc_from_ocv_mv(3900) == 60, "the band's midpoint reads %u%%",
          sb_soc_from_ocv_mv(3900));
    for (uint16_t mv = 3850; mv <= 3950; mv += 10) {
        const uint8_t p = sb_soc_from_ocv_mv(mv);
        CHECK(p >= 45 && p <= 78, "%u mV reads %u%%, outside the 60%% band", mv, p);
    }
    /* And the old linear map is shown to be wrong, here, rather than described
     * as approximate: 3770 mV across 3000..4200 is 64%. */
    const int linear = (3770 - 3000) * 100 / (4200 - 3000);
    CHECK(linear > 60, "the linear map was not actually wrong (%d%%)", linear);
    CHECK(sb_soc_from_ocv_mv(3770) < linear - 20,
          "the curve did not move away from the linear map");
}

static void test_it_never_goes_backwards(void)
{
    uint8_t last = 0;
    for (uint16_t mv = 3000; mv <= 4200; mv += 5) {
        const uint8_t p = sb_soc_from_ocv_mv(mv);
        CHECK(p >= last, "%u mV reads %u%% after %u%%", mv, p, last);
        last = p;
    }
}

static void test_the_load_is_taken_off_the_reading(void)
{
    /* ⛔ 180 mOhm is the pack impedance, PCM included, and it is on the
     * datasheet. Discharging 136 mA (the camera burst) sags the terminal by
     * 24 mV; charging at 1 A lifts it by 180 mV. */
    CHECK(sb_soc_ocv_mv(3746, -136) == 3746 + 24,
          "discharge sag not added back: %u", sb_soc_ocv_mv(3746, -136));
    CHECK(sb_soc_ocv_mv(3950, 1000) == 3950 - 180,
          "charge lift not removed: %u", sb_soc_ocv_mv(3950, 1000));
    CHECK(sb_soc_ocv_mv(3900, 0) == 3900, "changed a rested reading");

    /* ⚠️ AND THIS IS WHY IT MATTERS: at 1 A the uncorrected reading is a
     * different answer, not a slightly different one. */
    const uint8_t raw = sb_soc_from_ocv_mv(3950);
    const uint8_t fixed = sb_soc_from_ocv_mv(sb_soc_ocv_mv(3950, 1000));
    CHECK(raw > fixed + 15, "correction moved the gauge by only %d points",
          (int)raw - (int)fixed);
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
    test_the_curve_ends_where_the_cell_does();
    test_the_two_delivery_states_are_where_the_cell_says();
    test_it_never_goes_backwards();
    test_the_load_is_taken_off_the_reading();
    printf("%d checks, %d failures\n", checks, failures);
    return failures ? 1 : 0;
}
