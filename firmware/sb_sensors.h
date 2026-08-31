/* Bringing the two radars and the time-of-flight sensor up, and timing out.
 *
 * ⛔ THE REGISTER MAPS ARE NOT HERE AND THAT IS DELIBERATE. Acconeer ships an
 * A121 driver and ST ships a VL53L1X API; both are large, vendor-licensed, and
 * uninteresting to reimplement. What neither of them decides is the part this
 * product gets wrong if nobody writes it down: WHEN each sensor is allowed to
 * cost power, how long it is given to answer, and what happens when it does not.
 *
 * ⭐ AND THAT PART IS TESTABLE WITHOUT SILICON. The sequences below run against
 * the sb_hal vtable, so test_sb_sensors.c can drive them with a simulated bus
 * that models the datasheets' timing — including a sensor that never raises its
 * interrupt, which is the failure this code exists to survive.
 *
 * ⚠️ Every delay is from a datasheet and says which one.
 */
#ifndef SB_SENSORS_H
#define SB_SENSORS_H

#include <stdbool.h>
#include <stdint.h>

#include "sb_hal.h"

/* ── VL53L1X, ST DocID031281 ─────────────────────────────────────────────── */
/* ⚠️ "XSHUT should be high only when AVDD is on" — the datasheet's words. The
 * rail comes from the PMIC's load switch and is off between bursts, so the
 * order is: rail up, settle, then release XSHUT. Getting it backwards is not a
 * crash, it is a sensor that works on the bench and fails cold. */
#define SB_TOF_RAIL_SETTLE_MS 2
#define SB_TOF_BOOT_MS 2            /* firmware boot after XSHUT release      */
#define SB_TOF_I2C_ADDR 0x29
#define SB_TOF_TIMEOUT_MS 120       /* one ranging period plus generous slack */

/* ── A121, Acconeer datasheet v1.8 ───────────────────────────────────────── */
/* ⚠️ ENABLE is active high and shared by both sensors — one pin, two chips —
 * so bringing either up powers both. That is a deliberate consequence of the
 * pin budget and it means the enable delay is paid once, not twice. */
#define SB_RADAR_ENABLE_MS 2
#define SB_RADAR_TIMEOUT_MS 200
#define SB_RADAR_MEASURE_MS 50

typedef enum { SB_RADAR_LEFT = 0, SB_RADAR_RIGHT = 1 } sb_radar_side;

typedef enum {
    SB_SENS_OK = 0,
    SB_SENS_NO_REPLY,               /* the bus answered with nothing sensible */
    SB_SENS_TIMEOUT,                /* it never raised its interrupt          */
    SB_SENS_NOT_READY,              /* asked before it was brought up         */
} sb_sens_status;

typedef struct {
    bool tof_up;
    bool radar_up;
    uint32_t tof_timeouts;
    uint32_t radar_timeouts;
} sb_sensors;

void sb_sensors_init(sb_sensors *s);

/* ⭐ Power on only when something is going to be measured. The wake-up chain
 * arms these; nothing here polls. */
sb_sens_status sb_tof_up(sb_sensors *s, const sb_hal *hal);
void sb_tof_down(sb_sensors *s, const sb_hal *hal);

/* Blocks until the sensor interrupts or the timeout expires. Returns the
 * distance in millimetres through `mm` on success. */
sb_sens_status sb_tof_range(sb_sensors *s, const sb_hal *hal, uint16_t *mm);

sb_sens_status sb_radar_up(sb_sensors *s, const sb_hal *hal);
void sb_radar_down(sb_sensors *s, const sb_hal *hal);
sb_sens_status sb_radar_measure(sb_sensors *s, const sb_hal *hal,
                                sb_radar_side side, uint16_t *bins, int n);

#endif /* SB_SENSORS_H */
