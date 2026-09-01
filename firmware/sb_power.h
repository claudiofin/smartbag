/* The charge policy: the cell's own temperature bands, and a closed-bag limit.
 *
 * ⛔ THIS IS THE ONLY OPEN FINDING IN THE PROJECT, IN CODE. thermal/budget.py
 * has printed the same red line on every run for a long time: 5 W into a Qi coil
 * that sits under a lithium cell, inside a soft insulating insert, inside a
 * closed leather bag, puts that cell near 60 °C against a 45 °C charging limit.
 * The hardware to fix it now exists — RT1 is a 10 k NTC on the cell and U3 is an
 * nPM1300 that reads it — but hardware without a policy is a thermistor nobody
 * asked a question of.
 *
 * ⭐ THE INTERLOCK IS FREE AND THE FIRMWARE ALREADY KNOWS. The thermal analysis
 * listed three fixes in order of preference and the first one costs nothing: a
 * closed bag cannot dissipate a watt, and the Hall sensor has been telling this
 * firmware whether the bag is open since the first commit. The rest is a
 * temperature loop, which is what the PMIC is for.
 *
 * ⚠️ THE NUMBERS ARE NOT WRITTEN TWICE. They come from thermal/budget.py, and
 * tools/check.py asserts that these constants still match what that model
 * computes. A limit that drifts away from the analysis that justified it is
 * worse than no limit, because it looks considered.
 */
#ifndef SB_POWER_H
#define SB_POWER_H

#include <stdbool.h>
#include <stdint.h>

/* ── from the cell's datasheet, and from thermal/budget.py ───────────────── */
/* ⛔ THESE USED TO BE A GENERIC LITHIUM CELL. "Standard Li-ion charge ceiling",
 * "half current" — reasonable numbers for a cell nobody had chosen, which is
 * what BT1 was: a 148 mm semi-custom pouch drawn to fill the insert floor. The
 * cell is now Jauch LP523450JU, a catalogue part, and it states its own bands:
 *
 *   0 to +15 C   0.2 C max   (200 mA)
 *   +15 to +45 C 1.0 C max   (1000 mA)
 *   +45 to +55 C 0.5 C max   (500 mA)
 *
 * ⚠️ So the thresholds MOVED — 10/40 became 15/45 — and the ceiling went from 45
 * to 55. The old numbers were not wrong, they were a guess that happened to be
 * conservative. Being conservative by accident is not the same as being right.
 */
#define SB_CELL_CAPACITY_MAH 950    /* LP523450JU, minimum capacity        */
#define SB_CELL_FULL_MA 1000        /* 1.0 C, the +15..+45 C band          */
#define SB_CELL_REDUCED_MA 200      /* 0.2 C, the cold band                */
#define SB_CELL_LIMIT_C 45          /* above this the cell derates         */
#define SB_CELL_ABS_MAX_C 55        /* above this it must not charge       */
#define SB_CELL_MARGIN_K 5          /* nobody designs to the limit itself  */

/* ── state of charge ─────────────────────────────────────────────────────────
 *
 * ⛔ THE LINEAR MAP WAS WRONG BY A THIRD OF THE GAUGE AND THE DATASHEET SAYS SO.
 * npm1300.c used to spread 0..100% linearly across 3.0..4.2 V and call itself a
 * placeholder. It is worse than that: the LP523450JU's own delivery-state line
 * gives two points on its discharge curve — "Max. 30% (3.75-3.79V); Optional
 * 60% (3.85-3.95V)" — and the linear map reads 3.77 V as 64% where the cell
 * says 30%. A bag that reports two thirds of a charge on a cell that is nearly
 * a third full is not a rough gauge, it is a wrong one.
 *
 * ⭐ SO THE CURVE HAS FOUR POINTS AND ALL FOUR ARE THE CELL'S OWN. Cut-off,
 * the two delivery states, and the charge ceiling. Nothing between them is
 * known from the datasheet, and this interpolates straight lines and says so —
 * a real product characterises the cell or runs Nordic's fuel-gauge library,
 * and both of those want the cell in hand.
 */
#define SB_CELL_EMPTY_MV 3000       /* discharge cut-off                      */
#define SB_CELL_FULL_MV 4200        /* max charge voltage                     */
#define SB_CELL_IMPEDANCE_MOHM 180  /* pack impedance including the PCM       */

/* Open-circuit voltage in millivolts to percent, from the four datasheet
 * points. `mv` must be the RESTED voltage — see sb_soc_ocv_mv(). */
uint8_t sb_soc_from_ocv_mv(uint16_t mv);

/* ⚠️ AND THE TERMINAL VOLTAGE IS NOT THE OPEN-CIRCUIT VOLTAGE. 180 mΩ against
 * the 136 mA camera burst is 24 mV — a couple of percent — and against the
 * 1000 mA charge current it is 180 mV, which is most of the useful range. Pass
 * the current the PMIC reports, signed: positive charging into the cell,
 * negative discharging out of it. */
uint16_t sb_soc_ocv_mv(uint16_t terminal_mv, int16_t current_ma);
#define SB_CHG_FULL_MW 5000         /* what a Qi pad will deliver          */
#define SB_CHG_SLOW_MW 2900         /* what a CLOSED bag can dissipate     */

/* ⚠️ JEITA, not a single threshold. A lithium cell has four temperature bands
 * and only one of them allows full current; the nPM1300 implements this in
 * hardware and these are the numbers it gets told. */
#define SB_JEITA_COLD_C 0           /* below: no charging at all           */
#define SB_JEITA_COOL_C 15          /* 0..15: 0.2 C, from the datasheet    */
#define SB_JEITA_WARM_C SB_CELL_LIMIT_C   /* 45..55: 0.5 C                 */
#define SB_JEITA_HOT_C SB_CELL_ABS_MAX_C

typedef enum {
    SB_CHG_OFF = 0,
    SB_CHG_SLOW,                    /* the closed-bag ceiling              */
    SB_CHG_FULL,
} sb_charge_mode;

typedef enum {
    SB_CHG_NO_SOURCE = 0,
    SB_CHG_CELL_TOO_COLD,
    SB_CHG_CELL_TOO_HOT,
    SB_CHG_CELL_MARGINAL,           /* inside JEITA's reduced-current bands */
    SB_CHG_BAG_CLOSED,              /* ⭐ the finding, enforced             */
    SB_CHG_SENSOR_LOST,
    SB_CHG_OK,
} sb_charge_reason;

typedef struct {
    bool vbus_present;              /* something is on the charging pad    */
    bool bag_open;                  /* the Hall sensor, debounced          */
    int16_t cell_c;                 /* from the PMIC's NTC input           */
    bool ntc_valid;                 /* false if the thermistor reads open  */
} sb_charge_input;

typedef struct {
    sb_charge_mode mode;
    sb_charge_reason why;
    uint16_t limit_mw;
} sb_charge_decision;

/* Pure. No I/O, no clock, no state — so the whole policy is testable. */
sb_charge_decision sb_charge_decide(const sb_charge_input *in);

/* The register-level configuration the nPM1300 needs once at boot, expressed
 * as data rather than as a sequence of writes: the platform layer owns I2C. */
typedef struct {
    int16_t cold_c, cool_c, warm_c, hot_c;
    uint16_t full_mw, slow_mw;
} sb_jeita_profile;

sb_jeita_profile sb_charge_profile(void);

#endif /* SB_POWER_H */
