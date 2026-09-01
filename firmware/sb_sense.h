/* The sensing loop: the thing that turns silicon into sb_event.
 *
 * ⛔ THIS WAS THE HOLE, AND IT WAS AN ODD-SHAPED ONE. Every DECISION the bag
 * makes was written and tested — smartbag.c holds the wake-up chain and the
 * ledger, sb_power.c the charge policy, sb_fsr.c the matrix and its blobs,
 * sb_ble.c the wire — and all of it is driven by sb_feed(), which nothing ever
 * called. The firmware could boot, advertise, charge and answer a phone, and
 * report an empty bag forever, because no code read a sensor.
 *
 * ⭐ SO THIS FILE PRODUCES EVENTS AND DECIDES NOTHING. It polls the Hall sensor,
 * ranges the time-of-flight, sweeps the matrix and pings the radars, and hands
 * what it finds to sb_feed(). Every threshold that decides *behaviour* stays
 * where it was; what lives here is the sequence and the timing, which is the
 * part that has to be right against real parts.
 *
 * ⭐ AND IT IS A STATE MACHINE OVER THE HAL, NOT A DRIVER. Same trick as the
 * rest: it takes an sb_hal vtable, so the whole sequence runs on a laptop
 * against a simulated bag and is tested there. The alternative — writing it
 * inside main() against nrfx — is how sequencing bugs become things you can
 * only find with a scope.
 *
 * ⚠️ WHAT IT DOES NOT DO. It does not classify. It captures: sb_camera.c pulls
 * a 96x96 frame off the Arducam Mega and reduces it to the grey the model was
 * trained on, and the loop leaves it in s->frame_grey with an SB_EV_FRAME_READY
 * beside it. Recognition is an embedding and a nearest-neighbour lookup over
 * that buffer (ml/classify.py) and it is a different file's problem.
 */
#ifndef SB_SENSE_H
#define SB_SENSE_H

#include <stdbool.h>
#include <stdint.h>

#include "sb_camera.h"
#include "sb_fsr.h"
#include "sb_hal.h"
#include "sb_sensors.h"
#include "smartbag.h"

/* ── timings, and every one of them is from a datasheet or a measurement ───── */

/* ⚠️ The Hall sensor is a mechanical contact as far as this is concerned: a zip
 * slider crossing the magnet chatters. 40 ms is the debounce smartbag.c already
 * assumes when it counts hall_bounces_rejected. */
#define SB_HALL_DEBOUNCE_MS 40

/* ⭐ THE SETTLE WINDOW IS THE WHOLE POWER BUDGET. thermal/budget.py charges the
 * radar, the camera and the inference against 40 events a day because they only
 * run once the bag has stopped moving. Measuring a swinging bag would cost the
 * same energy and produce a map of where things were a second ago. */
#define SB_SETTLE_MS 2000

/* VL53L1X datasheet section 2.3: 30 ms for a long-distance ranging period. */
#define SB_TOF_PERIOD_MS 30

/* ⚠️ How far the beam sees before it is looking at the floor rather than at an
 * object crossing the mouth. The insert is 179.6 mm deep and the collar sits at
 * the top of it. */
#define SB_TOF_FLOOR_MM 175

/* A121: a sweep is tens of milliseconds and the two radars share one bus, so
 * they are measured in turn rather than together. */
#define SB_RADAR_SETTLE_MS 5

/* ⚠️ The sweep, in range bins. 2.5 mm a bin over 128 bins is 320 mm, which
 * covers the 225 mm floor from either end with room for the far wall. */
#define SB_RADAR_BINS 128
#define SB_RADAR_BIN_MM 3

/* ⛔ The first bins are the sensor looking at itself. Transmit leakage and the
 * package's own reflection sit there on every board ever made; a maximum that
 * includes them finds an object at the same distance every time. */
#define SB_RADAR_BLIND_BINS 8

typedef enum {
    SB_SENSE_ASLEEP = 0,   /* bag shut, everything down, microamps          */
    SB_SENSE_AWAKE,        /* bag open: the ToF watches the mouth           */
    SB_SENSE_CAPTURING,    /* something crossed: frames for the recogniser  */
    SB_SENSE_SETTLING,     /* bag shut again, waiting for it to stop moving */
    SB_SENSE_MAPPING,      /* the measurement: radar, then the matrix       */
} sb_sense_state;

typedef struct {
    sb_sense_state state;
    uint32_t state_since_ms;

    /* Hall debounce */
    bool hall_raw, hall_stable;
    uint32_t hall_edge_ms;

    /* the mouth */
    uint32_t last_tof_ms;
    uint16_t last_range_mm;
    bool beam_broken;
    uint8_t frames_wanted;

    /* ⭐ The camera, and the frame it produced. `grey` is what ml/classify.py
     * takes: 96x96 one byte a pixel. It is a member rather than a malloc
     * because there is no allocator on the target and exactly one burst is ever
     * in flight. */
    sb_camera cam;
    uint8_t wire[SB_CAM_WIRE_BYTES];   /* RGB565 off the bus, 18 kB          */
    uint8_t frame_grey[SB_CAM_PIXELS]; /* what ml/classify.py takes, 9 kB    */
    uint32_t frames_captured, frame_failures;

    /* what the last map found */
    sb_fsr_frame frame;
    uint8_t blob_count;      /* from sb_fsr_blobs, not from here */
    uint16_t radar_mm[2];

    /* ⚠️ Counters rather than logging: the tests assert on these, and on a
     * target they are the only evidence a sequence ran at all. */
    uint32_t maps_done, captures, hall_bounces, radar_failures;
} sb_sense;

void sb_sense_init(sb_sense *s, uint32_t now_ms);

/* Run one step. Emits zero or more events through `emit`, which is normally a
 * wrapper around sb_feed(). Returns the milliseconds until it next needs to be
 * called — the caller sleeps for that long, which is where the microamps come
 * from. */
typedef void (*sb_emit_fn)(void *ctx, const sb_event *ev);

uint32_t sb_sense_step(sb_sense *s, const sb_hal *hal, sb_sensors *sensors,
                       const sb_fsr_hal *fsr, uint32_t now_ms,
                       sb_emit_fn emit, void *ctx);

/* ── what does NOT need to be written, and did not ────────────────────────────
 *
 * ⭐ POSITION AND MASS ARE ALREADY ARITHMETIC AND ALWAYS WERE. sb_fsr_blobs()
 * returns a centroid in micrometres, a summed conductance that stands in for
 * mass, a cell count and a compartment — connected components over 96 numbers,
 * no model anywhere near it. Adding an sb_contact struct here would have been
 * the same four fields under a second name.
 *
 * ⚠️ AND RECOGNITION IS NOT TRAINED ON THE OWNER'S THINGS EITHER. ml/classify.py
 * trains an embedding once, offline, on rendered primitives the product will
 * never see; enrolment stores one prototype per object and recognition is a
 * cosine comparison. That is why showing the bag a wallet once is enough, and
 * why nothing about anybody's wallet reaches any weights.
 *
 * ⛔ WHAT IS ACTUALLY MISSING IS REAL SENSOR DATA TO VALIDATE AGAINST — a
 * different claim from "there is no model". The pipeline is written and
 * measured on synthetic frames; whether a wallet can be told from a passport
 * through four IR LEDs at 96x96 is a question only the built thing answers.
 */

/* The strongest reflection in a sweep, in millimetres, or 0 for "nothing
 * stands out". See the comment on the implementation for why a plain maximum is
 * wrong twice over. */
uint16_t sb_sense_peak_mm(const uint16_t *bins, int n);

/* ⚠️ The radar answers "how far", not "where". Two distances from two known
 * points is a two-circle intersection: it has two solutions, mirrored about the
 * line between the sensors, and only one of them is inside the bag. Returns
 * false when the circles do not meet — which is what happens when the two
 * radars are looking at different objects, and is the interesting case rather
 * than an error. */
bool sb_sense_triangulate(uint16_t left_mm, uint16_t right_mm,
                          int16_t *x_mm, int16_t *y_mm);

#endif /* SB_SENSE_H */
