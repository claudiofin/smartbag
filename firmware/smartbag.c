#include "smartbag.h"

#include <string.h>

/* ⚠️ These four numbers are the whole power/latency argument.
 *
 * hall_debounce_ms — a zip slider is a mechanical thing dragged past a magnet;
 *   without a debounce it produces a burst of edges and each one would arm the
 *   ToF. 40 ms costs nothing and removes the entire class.
 * settle_ms — measuring while the bag is moving reads inertial load, not mass.
 *   2 s of stillness is roughly "set down", which is the only moment the FSR
 *   tells the truth.
 * capture_timeout_ms — the burst must not be able to hang with the camera
 *   powered. 400 ms is ten times the burst it is protecting.
 * stale_threshold — integrated motion, in milli-g seconds, past which the map
 *   is marked stale. Not recomputed: marked. Recomputing here would be the
 *   expensive mistake.
 */
const sb_config SB_DEFAULTS = {
    .hall_debounce_ms = 40,
    .settle_ms = 2000,
    .capture_timeout_ms = 400,
    .stale_threshold = 1200,
};

static void enter(sb_device *d, sb_state s, uint32_t now_ms)
{
    d->state = s;
    d->state_since_ms = now_ms;
}

void sb_init(sb_device *d, uint32_t now_ms)
{
    memset(d, 0, sizeof(*d));
    enter(d, SB_SLEEP, now_ms);
    d->map.valid = false;
}

static sb_object *find(sb_ledger *l, uint16_t id)
{
    for (uint8_t i = 0; i < l->count; i++)
        if (l->items[i].id == id)
            return &l->items[i];
    return 0;
}

/* ⭐ THE LEDGER IS APPEND-ONLY IN SPIRIT. An object that leaves is marked absent
 * rather than deleted, so `seq` and the id space stay stable and the phone can
 * resync by sequence number instead of re-reading everything. */
static void ledger_apply(sb_ledger *l, uint16_t id, uint8_t klass,
                         bool entering, uint32_t now_ms)
{
    sb_object *o = find(l, id);
    if (!o) {
        if (!entering || l->count >= SB_MAX_OBJECTS)
            return;
        o = &l->items[l->count++];
        o->id = id;
        o->klass = klass;
    }
    o->present = entering;
    o->since_ms = now_ms;
    l->seq++;
}

/* ⛔ MEASURE IS TRANSIENT, not a state the device rests in. Making it a resting
 * state cost a second tick to leave, and until that tick arrived the device
 * ignored the bag being opened again — in the test that ran forty insertions,
 * exactly half of them were dropped on the floor. A measurement is an action;
 * the only states worth resting in are the ones that cost power to hold. */
static void measure(sb_device *d, uint32_t now_ms)
{
    enter(d, SB_MEASURE, now_ms);
    d->radar_pings++;
    d->map.measured_at_ms = now_ms;
    d->map.disturbance = 0;
    d->map.valid = true;
    enter(d, SB_SLEEP, now_ms);
}


void sb_feed(sb_device *d, const sb_config *cfg, const sb_event *ev)
{
    switch (ev->kind) {

    case SB_EV_CLOSURE_OPENED:
    case SB_EV_CLOSURE_CLOSED: {
        /* ⛔ DEBOUNCE FIRST, ALWAYS. This is the only place in the design where
         * a mechanical contact reaches the state machine, and it is also the
         * gate that powers everything else. An un-debounced closure edge does
         * not cost one wrong reading, it costs a whole camera burst. */
        /* ⚠️ The FIRST edge is never a bounce. Comparing against a
         * zero-initialised timestamp made the debounce swallow any opening at
         * t < 40 ms — which in the tests was every opening at t = 0, and in the
         * field would be every opening in the first moment after boot. */
        if (d->have_closure_edge
            && ev->at_ms - d->last_closure_edge_ms < cfg->hall_debounce_ms) {
            d->hall_bounces_rejected++;
            return;
        }
        d->have_closure_edge = true;
        d->last_closure_edge_ms = ev->at_ms;
        if (ev->kind == SB_EV_CLOSURE_OPENED) {
            /* ⚠️ Openable from any resting state, not only from SLEEP. Guarding
             * on SLEEP alone meant that reopening the bag while it was still
             * waiting to settle did nothing at all: the device sat in SETTLE
             * with the mouth wide open and ignored everything put into it. */
            if (d->state == SB_SLEEP || d->state == SB_SETTLE)
                enter(d, SB_OPEN, ev->at_ms);
        } else {
            /* Closing beats everything: nothing can cross a shut mouth. */
            enter(d, SB_SLEEP, ev->at_ms);
            d->frames_captured = 0;
        }
        return;
    }

    case SB_EV_TOF_CROSSED:
        /* ⚠️ Only from OPEN. A ToF crossing while the bag is shut is noise, and
         * while a capture is already running it is the same object still on its
         * way in. Either way it must not start a second burst. */
        if (d->state == SB_OPEN) {
            enter(d, SB_CAPTURE, ev->at_ms);
            d->frames_captured = 0;
            d->camera_bursts++;
        }
        return;

    case SB_EV_FRAME_READY:
        if (d->state == SB_CAPTURE && d->frames_captured < SB_CAPTURE_FRAMES)
            d->frames_captured++;
        return;

    case SB_EV_CLASSIFIED:
        if (d->state != SB_CAPTURE)
            return;
        ledger_apply(&d->ledger, (uint16_t)ev->arg, 0, ev->entering, ev->at_ms);
        /* Something moved inside, so wherever things were, they are not there
         * any more. */
        d->map.valid = false;
        d->map.disturbance = cfg->stale_threshold;
        enter(d, SB_SETTLE, ev->at_ms);
        return;

    case SB_EV_MOTION:
        if (ev->arg > 0)
            d->map.disturbance += (uint32_t)ev->arg;
        /* ⚠️ Motion cancels a pending settle. Without this the device would
         * measure two seconds after the last *event* rather than after the last
         * *movement*, which on a walk is never. */
        if (d->state == SB_SETTLE)
            d->state_since_ms = ev->at_ms;
        return;

    case SB_EV_STILL:
        if (d->state == SB_SETTLE && ev->at_ms - d->state_since_ms >= cfg->settle_ms)
            measure(d, ev->at_ms);
        return;
    }
}

void sb_tick(sb_device *d, const sb_config *cfg, uint32_t now_ms)
{
    switch (d->state) {

    case SB_CAPTURE:
        if (d->frames_captured >= SB_CAPTURE_FRAMES) {
            /* Frames are in; the NPU runs next and will send CLASSIFIED. Stay
             * here so a late frame cannot start a second burst. */
            return;
        }
        /* ⛔ The camera must not be able to stay powered on a stuck sensor. */
        if (now_ms - d->state_since_ms > cfg->capture_timeout_ms)
            enter(d, SB_OPEN, now_ms);
        return;

    case SB_SETTLE:
        if (now_ms - d->state_since_ms >= cfg->settle_ms)
            measure(d, now_ms);
        return;

    case SB_SLEEP:
    case SB_OPEN:
    case SB_MEASURE:
        return;
    }
}

bool sb_map_is_stale(const sb_device *d, const sb_config *cfg)
{
    return !d->map.valid || d->map.disturbance >= cfg->stale_threshold;
}

int sb_inventory(const sb_device *d, uint16_t *out, int max)
{
    int n = 0;
    for (uint8_t i = 0; i < d->ledger.count && n < max; i++)
        if (d->ledger.items[i].present)
            out[n++] = d->ledger.items[i].id;
    return n;
}

bool sb_holds(const sb_device *d, uint16_t id)
{
    for (uint8_t i = 0; i < d->ledger.count; i++)
        if (d->ledger.items[i].id == id)
            return d->ledger.items[i].present;
    return false;
}

/* ⚠️ ESTIMATES, NOT MEASUREMENTS. Order-of-magnitude figures for the component
 * classes: a camera burst plus NPU inference ~6.7 uAh, a radar ping ~4.2 uAh.
 * They are here to make the shape of the budget visible in a test — a day of
 * heavy use costs less than a milliamp-hour — not to be quoted as data. */
uint32_t sb_energy_uah_x1000(const sb_device *d)
{
    return d->camera_bursts * 6700u + d->radar_pings * 4200u;
}
