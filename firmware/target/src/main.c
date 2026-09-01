/* The entry point: build the HAL, hand it to the logic, and get out of the way.
 *
 * ⭐ THIS FILE IS DELIBERATELY SHORT AND HAS NOTHING TO TEST IN IT. Every
 * decision the bag makes — when to wake, what to believe, whether to charge —
 * is in ../smartbag.c, ../sb_power.c, ../sb_sensors.c and ../sb_fsr.c, under
 * 378 host assertions. If a rule ever appears here it has escaped from
 * somewhere it could be checked, and it should be put back.
 *
 * ⚠️ COMPILED, and that is recent. tools/check.py builds this image and fails
 * if it does not link; see README.md for what that does and does not prove.
 */
#include <zephyr/kernel.h>
#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/logging/log.h>

#include "smartbag.h"
#include "sb_hal.h"
#include "sb_power.h"
#include "sb_sensors.h"
#include "sb_sense.h"
#include "sb_fsr.h"
#include "sb_ble.h"

LOG_MODULE_REGISTER(smartbag, CONFIG_LOG_DEFAULT_LEVEL);

int sb_hal_zephyr_init(sb_hal *hal);
bool sb_pmic_ready(void);
int16_t sb_pmic_cell_temp_c(bool *valid);
void sb_pmic_apply(const sb_charge_decision *d);
int sb_gatt_start(const sb_device *d, const sb_config *cfg, sb_enroll *e);

static sb_hal hal;
static sb_device dev;
static sb_sensors sensors;
static sb_enroll enroll;
static const sb_config *const cfg = &SB_DEFAULTS;

/* ⚠️ 28 kB of it — an 18 kB RGB565 frame and a 9 kB luma one — so it is a
 * static and not a stack frame. Zephyr's main thread stack is 2 kB. */
static sb_sense sense;

/* The FSR front end: the multiplexer and the amplifiers behind the same HAL. */
static void fsr_drive(void *c, uint8_t col, sb_fsr_drive m);
static uint16_t fsr_read(void *c, uint8_t row);
static void fsr_settle(void *c, uint32_t us);
static sb_fsr_hal fsr_hal;

/* ⭐ THE LOOP PRODUCES EVENTS AND sb_feed DECIDES WHAT THEY MEAN, and this
 * three-line function is the entire join between them. Everything above it is
 * silicon and everything below it is under host assertions. */
static void feed(void *ctx, const sb_event *ev)
{
    ARG_UNUSED(ctx);
    sb_feed(&dev, cfg, ev);
}

/* ⚠️ The Hall sensor is the whole wake-up chain's first link and it is also the
 * charge interlock's only input. Reading it in one place means the two cannot
 * disagree about whether the bag is open. */
static bool bag_is_open(void)
{
    /* DRV5032 is open-drain and active low: pulled down when a magnet is near,
     * which is when the closure is SHUT. */
    return hal.gpio_get(hal.ctx, SB_PIN_HALL);
}

int main(void)
{
    if (sb_hal_zephyr_init(&hal) != 0) {
        LOG_ERR("HAL did not come up — nothing below this is meaningful");
        return -ENODEV;
    }
    sb_sensors_init(&sensors);
    sb_init(&dev, hal.now_ms(hal.ctx));
    fsr_hal = (sb_fsr_hal){ fsr_drive, fsr_read, fsr_settle, NULL };
    sb_sense_init(&sense, hal.now_ms(hal.ctx));

    int err = bt_enable(NULL);
    if (err) {
        /* ⚠️ Not fatal. A bag that cannot talk to a phone still has to know
         * what is in it and still has to charge safely; the radio is the least
         * important thing here and must not take the rest down with it. */
        LOG_WRN("bluetooth did not start (%d) — running without it", err);
    } else {
        sb_enroll_init(&enroll, 1);
        err = sb_gatt_start(&dev, cfg, &enroll);
        if (err) {
            LOG_WRN("advertising did not start (%d)", err);
        }
    }

    if (!sb_pmic_ready()) {
        /* ⛔ FATAL, unlike the radio. Without the PMIC there is no cell
         * temperature, and firmware/sb_power.c refuses to charge without one —
         * so a bag that ran on would quietly never charge again. */
        LOG_ERR("nPM1300 not ready — no cell temperature, so no charging");
    }
    LOG_INF("SmartBag up: %u taxels, cell %u mAh",
            (unsigned)SB_FSR_TAXELS, (unsigned)SB_CELL_CAPACITY_MAH);

    for (;;) {
        const uint32_t now = hal.now_ms(hal.ctx);

        /* ⭐ THE CHARGE DECISION IS TAKEN EVERY TICK AND IS CHEAP. It is three
         * comparisons against numbers out of the cell's datasheet, and the
         * alternative — deciding once when the pad appears — is a bag that
         * started charging on a cool morning and kept going in a hot car. */
        bool ntc_ok = false;
        const int16_t cell_c = sb_pmic_cell_temp_c(&ntc_ok);
        const sb_charge_input in = {
            .vbus_present = hal.gpio_get(hal.ctx, SB_PIN_PMIC_IRQ),
            .bag_open = bag_is_open(),
            .cell_c = cell_c,
            .ntc_valid = ntc_ok,
        };
        const sb_charge_decision d = sb_charge_decide(&in);
        sb_pmic_apply(&d);

        /* ⭐ AND HERE IS THE THING THAT WAS MISSING FOR THE WHOLE OF THIS
         * PROJECT'S LIFE. sb_feed() is what turns a sensor into an inventory
         * and until now nothing called it: the bag could boot, advertise,
         * charge and answer a phone, and report itself empty forever. */
        const uint32_t wait = sb_sense_step(&sense, &hal, &sensors, &fsr_hal,
                                            now, feed, NULL);

        sb_tick(&dev, cfg, now);

        /* ⚠️ THE SLEEP IS THE SENSING LOOP'S, NOT A CONSTANT. thermal/budget.py's
         * 25 uW of deep sleep is the dominant term once the sensors are idle,
         * and sb_sense_step returns 250 ms when the bag is shut and 30 while it
         * is watching the mouth — so the bag polls fast exactly when something
         * is happening and is asleep the rest of the time. The floor of 20 ms
         * is there so the charge decision above still runs often enough to
         * matter, and its ceiling is the loop's own answer. */
        k_msleep(wait < 20 ? 20 : (wait > 250 ? 250 : wait));
    }
    return 0;
}

/* ── the taxel front end ──────────────────────────────────────────────────────
 * ⚠️ Three lines of glue that could have lived in sb_hal_zephyr.c and do not,
 * because sb_fsr.h's vtable is a different shape from sb_hal's and joining them
 * there would have made that file know about both. */
static void fsr_drive(void *c, uint8_t col, sb_fsr_drive m)
{
    ARG_UNUSED(c);
    /* ⛔ THE POLARITY IS INVERTED HERE AND THAT IS THE BOARD, NOT A BUG.
     * sb_fsr.c models a matrix where the idle columns are held at ground and
     * the selected one is driven high. hardware/netlist.py drew the opposite
     * and did it on purpose: all sixteen columns rest at VREF through R20..R35,
     * and U7 — one CD74HC4067 — pulls exactly ONE of them down to ground. The
     * topology is what sb_fsr.c actually depends on, which is that the idle
     * columns sit at the same potential as the row amplifiers' summing junction
     * and so cannot carry a sneak current. Which end of the supply that shared
     * potential is does not change a single reading.
     *
     * ⭐ AND IT MEANS THE GHOSTING TEST'S BAD CASE CANNOT BE BUILT ON THIS
     * BOARD. test_sb_fsr.c solves the network and finds a phantom taxel reading
     * 39% of a real one when the idle columns float; here they cannot float,
     * because sixteen resistors hold them. SB_FSR_HIZ and SB_FSR_LOW therefore
     * do the same thing — disable the multiplexer — and the pull-ups do the
     * rest.
     *
     * ⚠️ The channel is 0..15. There is no col+16: it is one 16:1 part, not two. */
    switch (m) {
    case SB_FSR_HIGH: hal.mux_select(hal.ctx, col); break;   /* select = pull low */
    case SB_FSR_LOW:
    case SB_FSR_HIZ:
    default:          hal.mux_select(hal.ctx, -1); break;    /* the pull-ups hold */
    }
}

static uint16_t fsr_read(void *c, uint8_t row)
{
    ARG_UNUSED(c);
    return hal.adc_read(hal.ctx, row);
}

static void fsr_settle(void *c, uint32_t us)
{
    ARG_UNUSED(c);
    hal.delay_us(hal.ctx, us);
}
