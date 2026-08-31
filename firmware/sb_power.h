/* The charge policy: what stops the cell reaching 60 °C in a closed bag.
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

/* ── from thermal/budget.py ──────────────────────────────────────────────── */
#define SB_CELL_LIMIT_C 45          /* standard Li-ion charge ceiling      */
#define SB_CELL_MARGIN_K 5          /* nobody designs to the limit itself  */
#define SB_CHG_FULL_MW 5000         /* what a Qi pad will deliver          */
#define SB_CHG_SLOW_MW 2200         /* what a CLOSED bag can dissipate     */

/* ⚠️ JEITA, not a single threshold. A lithium cell has four temperature bands
 * and only one of them allows full current; the nPM1300 implements this in
 * hardware and these are the numbers it gets told. */
#define SB_JEITA_COLD_C 0           /* below: no charging at all           */
#define SB_JEITA_COOL_C 10          /* 0..10: half current                 */
#define SB_JEITA_WARM_C 40          /* 40..45: half current                */
#define SB_JEITA_HOT_C SB_CELL_LIMIT_C

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
