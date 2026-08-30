/* SmartBag core logic: the wake-up chain, the inventory ledger, and the rule
 * that decides when the position map has gone stale.
 *
 * ⛔ NO HAL, NO RTOS, NO DRIVERS. Everything here is pure C over injected time
 * and injected sensor events. That is deliberate: the interesting part of this
 * firmware is not how to read a Hall sensor, it is *when* each sensor is
 * allowed to cost power and *what* the device is entitled to claim afterwards.
 * Those decisions are testable on a host, and here they are tested. The parts
 * that need real silicon are named in `smartbag_platform` and left unwritten.
 *
 * ⭐ THE POWER BUDGET IS THE ARCHITECTURE. A camera and an NPU that run for
 * 120 ms cost more than the radio does all day; a ToF that polls freely costs
 * more than both. So nothing is polled: each stage is armed only by the stage
 * before it, and the whole chain is armed only when the closure opens.
 */
#ifndef SMARTBAG_H
#define SMARTBAG_H

#include <stdbool.h>
#include <stdint.h>

#define SB_MAX_OBJECTS 24
#define SB_CAPTURE_FRAMES 3

/* ── the wake-up chain ─────────────────────────────────────────────────────── */
typedef enum {
    SB_SLEEP,      /* everything down but the Hall input and the IMU  */
    SB_OPEN,       /* closure open: the ToF is powered and watching   */
    SB_CAPTURE,    /* something crossed the mouth: camera + IR burst  */
    SB_SETTLE,     /* it is inside; wait for it to stop moving        */
    SB_MEASURE,    /* radar ping + FSR read, then straight back down  */
} sb_state;

/* Events the platform layer feeds in. Everything is edge-driven. */
typedef enum {
    SB_EV_CLOSURE_OPENED,
    SB_EV_CLOSURE_CLOSED,
    SB_EV_TOF_CROSSED,     /* the ToF beam was broken                 */
    SB_EV_FRAME_READY,     /* one camera frame has been captured      */
    SB_EV_CLASSIFIED,      /* the NPU produced a label for the burst  */
    SB_EV_MOTION,          /* IMU: a chunk of movement, in milli-g·s  */
    SB_EV_STILL,           /* IMU: quiet for the settle window        */
} sb_event_kind;

typedef struct {
    sb_event_kind kind;
    uint32_t at_ms;
    int32_t arg;           /* object id for CLASSIFIED, milli-g·s for MOTION */
    bool entering;         /* CLASSIFIED: true if the object came in         */
} sb_event;

/* ── the inventory: a ledger, not a snapshot ───────────────────────────────── */
typedef struct {
    uint16_t id;
    uint8_t klass;
    uint32_t since_ms;
    bool present;
} sb_object;

typedef struct {
    sb_object items[SB_MAX_OBJECTS];
    uint8_t count;
    uint32_t seq;          /* increments on every accepted mouth event */
} sb_ledger;

/* ── how much to trust the position map ────────────────────────────────────── */
typedef struct {
    uint32_t measured_at_ms;
    uint32_t disturbance;  /* integrated motion since the last measurement */
    bool valid;
} sb_map;

typedef struct {
    sb_state state;
    uint32_t state_since_ms;
    uint8_t frames_captured;
    sb_ledger ledger;
    sb_map map;

    /* counters, so the tests can assert on behaviour and not on internals */
    uint32_t camera_bursts;
    uint32_t radar_pings;
    uint32_t hall_bounces_rejected;
    uint32_t last_closure_edge_ms;
    bool have_closure_edge;
} sb_device;

/* Tunables. Exposed because every one of them is a power/latency trade the
 * caller may want to make differently, and because the tests pin them. */
typedef struct {
    uint32_t hall_debounce_ms;   /* a zip slider bounces; so does a magnet   */
    uint32_t settle_ms;          /* stillness required before measuring      */
    uint32_t capture_timeout_ms; /* give up if the burst never completes     */
    uint32_t stale_threshold;    /* integrated motion that voids the map     */
} sb_config;

extern const sb_config SB_DEFAULTS;

void sb_init(sb_device *d, uint32_t now_ms);
void sb_feed(sb_device *d, const sb_config *cfg, const sb_event *ev);
void sb_tick(sb_device *d, const sb_config *cfg, uint32_t now_ms);

/* Queries the BLE layer answers with. */
bool sb_map_is_stale(const sb_device *d, const sb_config *cfg);
int sb_inventory(const sb_device *d, uint16_t *out, int max);
bool sb_holds(const sb_device *d, uint16_t id);

/* Estimated charge for the work done so far, in microamp-hours. Rough numbers
 * from the component classes in hardware/netlist.py, not measurements. */
uint32_t sb_energy_uah_x1000(const sb_device *d);

#endif /* SMARTBAG_H */
