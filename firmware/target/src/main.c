/* The entry point: build the HAL, hand it to the logic, and get out of the way.
 *
 * ⭐ THIS FILE IS DELIBERATELY SHORT AND HAS NOTHING TO TEST IN IT. Every
 * decision the bag makes — when to wake, what to believe, whether to charge —
 * is in ../smartbag.c, ../sb_power.c, ../sb_sensors.c and ../sb_fsr.c, under
 * 378 host assertions. If a rule ever appears here it has escaped from
 * somewhere it could be checked, and it should be put back.
 *
 * ⚠️ NOT COMPILED. See src/sb_hal_zephyr.c and README.md: there is no nRF
 * Connect SDK on the machine this was written on.
 */
#include <zephyr/kernel.h>
#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/logging/log.h>

#include "smartbag.h"
#include "sb_hal.h"
#include "sb_power.h"
#include "sb_sensors.h"
#include "sb_fsr.h"

LOG_MODULE_REGISTER(smartbag, CONFIG_LOG_DEFAULT_LEVEL);

int sb_hal_zephyr_init(sb_hal *hal);
bool sb_pmic_ready(void);
int16_t sb_pmic_cell_temp_c(bool *valid);
void sb_pmic_apply(const sb_charge_decision *d);

static sb_hal hal;
static sb_device dev;
static sb_sensors sensors;
static const sb_config *const cfg = &SB_DEFAULTS;

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

    int err = bt_enable(NULL);
    if (err) {
        /* ⚠️ Not fatal. A bag that cannot talk to a phone still has to know
         * what is in it and still has to charge safely; the radio is the least
         * important thing here and must not take the rest down with it. */
        LOG_WRN("bluetooth did not start (%d) — running without it", err);
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

        sb_tick(&dev, cfg, now);

        /* ⚠️ 100 ms, not 1 ms. thermal/budget.py's 25 uW of "deep sleep" is the
         * dominant term in the whole power budget once the sensors are idle,
         * and it is only 25 uW if this loop is asleep almost all of the time. */
        k_msleep(100);
    }
    return 0;
}
