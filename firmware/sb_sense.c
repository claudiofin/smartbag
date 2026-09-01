#include <string.h>

#include "sb_sense.h"

/* ── the radars, and where they are ───────────────────────────────────────────
 * U2 and U6 sit at the two ends of the insert, on the rigid islands, at
 * x = ±91 mm from the centre in hardware/netlist.py's frame. The insert floor
 * is 225 x 78 mm, so in floor coordinates measured from the front-left corner
 * they are at (21.5, 0) and (203.5, 0) — up at the collar, looking down. */
#define RADAR_L_X_MM 21
#define RADAR_R_X_MM 203
#define FLOOR_W_MM 225
#define FLOOR_D_MM 78

static void go(sb_sense *s, sb_sense_state to, uint32_t now_ms)
{
    s->state = to;
    s->state_since_ms = now_ms;
}

static void send(sb_emit_fn emit, void *ctx, sb_event_kind kind, int32_t arg,
                 bool entering, uint32_t now_ms)
{
    if (!emit) {
        return;
    }
    const sb_event ev = {
        .kind = kind, .at_ms = now_ms, .arg = arg, .entering = entering,
    };
    emit(ctx, &ev);
}

void sb_sense_init(sb_sense *s, uint32_t now_ms)
{
    memset(s, 0, sizeof(*s));
    s->state = SB_SENSE_ASLEEP;
    s->state_since_ms = now_ms;
    s->hall_edge_ms = now_ms;
    s->last_range_mm = SB_TOF_FLOOR_MM;
}

/* ⛔ DEBOUNCE IS NOT A DELAY, IT IS A COMMITMENT. Waiting 40 ms and then reading
 * again still believes whatever the second read said. What this does is refuse
 * to change its mind until the raw line has held the NEW value for the whole
 * window — so a slider chattering across the magnet produces one edge, and the
 * bounces are counted rather than acted on. smartbag.c has a counter called
 * hall_bounces_rejected that had nothing to increment it until now. */
static bool hall_settled(sb_sense *s, bool raw, uint32_t now_ms)
{
    if (raw != s->hall_raw) {
        s->hall_raw = raw;
        s->hall_edge_ms = now_ms;
        if (raw != s->hall_stable) {
            return false;               /* a candidate edge, not yet believed */
        }
        s->hall_bounces++;              /* it came back before it settled */
        return false;
    }
    if (raw != s->hall_stable && now_ms - s->hall_edge_ms >= SB_HALL_DEBOUNCE_MS) {
        s->hall_stable = raw;
        return true;
    }
    return false;
}

/* ⛔ THE RADAR DOES NOT RETURN A DISTANCE, IT RETURNS A SWEEP. The A121 gives
 * amplitude per range bin, and turning that into "there is something 90 mm away"
 * is a peak search — arithmetic over a few hundred numbers, the same class of
 * thing as the FSR's blobs and just as free of any model.
 *
 * ⚠️ THE FIRST BIN IS NOT AN OBJECT. Every pulsed radar sees its own transmit
 * leakage and the housing it is sitting in; the first few bins are that, and a
 * naive maximum finds them every time, from every board, at the same distance —
 * which reads as an object that is always there. SB_RADAR_BLIND_BINS skips them.
 *
 * ⚠️ And a peak has to stand out to count. Below the noise floor there is
 * nothing to report, and reporting the largest sample of a flat sweep is how
 * you get a bag that always contains one thing.
 */
uint16_t sb_sense_peak_mm(const uint16_t *bins, int n)
{
    uint32_t sum = 0;
    int best = -1;
    uint16_t peak = 0;

    for (int i = SB_RADAR_BLIND_BINS; i < n; i++) {
        sum += bins[i];
        if (bins[i] > peak) {
            peak = bins[i];
            best = i;
        }
    }
    if (best < 0 || n <= SB_RADAR_BLIND_BINS) {
        return 0;
    }
    const uint32_t mean = sum / (uint32_t)(n - SB_RADAR_BLIND_BINS);
    if (peak < mean * 3) {
        return 0;                        /* a flat sweep is an empty bag */
    }
    return (uint16_t)(best * SB_RADAR_BIN_MM);
}

bool sb_sense_triangulate(uint16_t left_mm, uint16_t right_mm,
                          int16_t *x_mm, int16_t *y_mm)
{
    /* Two circles centred on the radars. d is the distance between them. */
    const int32_t d = RADAR_R_X_MM - RADAR_L_X_MM;
    const int32_t r0 = left_mm, r1 = right_mm;

    /* ⛔ NO SOLUTION IS THE INTERESTING ANSWER, NOT AN ERROR. If the circles do
     * not meet, the two radars are looking at different objects — which is what
     * happens with two things in the bag, and is exactly when a made-up point
     * would be worst. The caller falls back to a compartment. */
    if (r0 + r1 < d || r0 > r1 + d || r1 > r0 + d) {
        return false;
    }
    /* a is how far along the baseline the intersection sits. */
    const int32_t a = (r0 * r0 - r1 * r1 + d * d) / (2 * d);
    int32_t h2 = r0 * r0 - a * a;
    if (h2 < 0) {
        h2 = 0;
    }
    /* Integer square root: no libm on the target, and this needs 12 bits. */
    int32_t h = 0;
    while ((h + 1) * (h + 1) <= h2) {
        h++;
    }
    /* ⚠️ Of the two mirrored solutions only the one inside the bag is real: the
     * radars look along the floor from the collar, so y is positive into the
     * bag and never behind it. */
    const int32_t x = RADAR_L_X_MM + a;
    if (x < 0 || x > FLOOR_W_MM || h > FLOOR_D_MM) {
        return false;
    }
    *x_mm = (int16_t)x;
    *y_mm = (int16_t)h;
    return true;
}

/* ── one step of the machine ────────────────────────────────────────────────*/
uint32_t sb_sense_step(sb_sense *s, const sb_hal *hal, sb_sensors *sensors,
                       const sb_fsr_hal *fsr, uint32_t now_ms,
                       sb_emit_fn emit, void *ctx)
{
    /* The Hall sensor is read in every state and it is the only thing that is:
     * it is what wakes the bag and what tells the charge policy the bag is
     * shut, and a state machine that stopped reading it while busy would miss
     * the closure that ends the burst it is in the middle of. */
    const bool open = hal->gpio_get(hal->ctx, SB_PIN_HALL);
    if (hall_settled(s, open, now_ms)) {
        send(emit, ctx, s->hall_stable ? SB_EV_CLOSURE_OPENED
                                       : SB_EV_CLOSURE_CLOSED, 0, false, now_ms);
        if (s->hall_stable) {
            /* ⭐ The ToF comes up on the OPENING edge and not before. It is
             * 20 mW while ranging against 25 µW asleep — the single most
             * expensive thing in the bag that is not the radio, and the whole
             * reason the wake-up chain starts with a magnet. */
            sb_tof_up(sensors, hal);
            /* ⚠️ The camera is probed on the opening edge rather than at boot:
             * it is a module on a connector at the end of a flex, and whether
             * it is there is a question with a different answer every time the
             * bag is opened. A probe that failed leaves cam.ready false and the
             * captures below turn into counted failures rather than silence. */
            if (!s->cam.ready) {
                sb_cam_probe(&s->cam, hal);
            } else {
                sb_cam_wake(&s->cam, hal);
            }
            go(s, SB_SENSE_AWAKE, now_ms);
        } else {
            sb_tof_down(sensors, hal);
            sb_cam_sleep(&s->cam, hal);
            go(s, SB_SENSE_SETTLING, now_ms);
        }
    }

    switch (s->state) {
    case SB_SENSE_ASLEEP:
        /* ⚠️ 250 ms, not faster. Asleep the only thing that can change is the
         * zip, and a hand opening a bag takes half a second. */
        return 250;

    case SB_SENSE_AWAKE: {
        if (now_ms - s->last_tof_ms < SB_TOF_PERIOD_MS) {
            return SB_TOF_PERIOD_MS - (now_ms - s->last_tof_ms);
        }
        s->last_tof_ms = now_ms;
        uint16_t mm = 0;
        if (sb_tof_range(sensors, hal, &mm) != SB_SENS_OK) {
            return SB_TOF_PERIOD_MS;
        }
        /* ⛔ THE BEAM IS BROKEN, NOT SHORTER. A range that simply got smaller is
         * a hand hovering; what says an object went in is the beam breaking and
         * then CLEARING again, and only the second edge is the moment to look at
         * what is now on the floor. Triggering on the break alone fires on the
         * hand as well as on what it was holding. */
        const bool broken = mm < SB_TOF_FLOOR_MM;
        if (broken && !s->beam_broken) {
            s->beam_broken = true;
            send(emit, ctx, SB_EV_TOF_CROSSED, mm, true, now_ms);
            s->frames_wanted = 3;
            s->captures++;
            go(s, SB_SENSE_CAPTURING, now_ms);
        }
        s->beam_broken = broken;
        s->last_range_mm = mm;
        return SB_TOF_PERIOD_MS;
    }

    case SB_SENSE_CAPTURING: {
        /* ⚠️ Three frames as the object passes, which is what ml/classify.py's
         * burst assumes, and the illuminators are on for the exposure only:
         * 600 mW for ten milliseconds a time is a rounding error in the budget,
         * 600 mW held on is not.
         *
         * ⛔ AND THE LEDS COME ON BEFORE THE SHUTTER, NOT AROUND THE TRANSFER.
         * The exposure is over the moment the module raises its capture-done
         * flag; the 18 kB burst that follows is the frame already taken being
         * carried across a bus. Holding the illuminators through it would triple
         * the energy for a picture that cannot change. */
        hal->gpio_set(hal->ctx, SB_PIN_IR_LED_EN, SB_PIN_HIGH);
        sb_cam_status cs = sb_cam_expose(&s->cam, hal);
        hal->gpio_set(hal->ctx, SB_PIN_IR_LED_EN, SB_PIN_LOW);
        if (cs == SB_CAM_OK) {
            cs = sb_cam_fetch(&s->cam, hal, s->wire, sizeof(s->wire),
                              s->frame_grey);
        }

        if (cs == SB_CAM_OK) {
            s->frames_captured++;
            send(emit, ctx, SB_EV_FRAME_READY, s->frames_wanted, true, now_ms);
        } else {
            /* ⚠️ A frame that did not arrive is not a frame. Emitting
             * SB_EV_FRAME_READY anyway would hand the recogniser the previous
             * capture — or uninitialised memory on the first one — and it would
             * answer with a label and a confidence like any other. */
            s->frame_failures++;
        }
        if (--s->frames_wanted == 0) {
            /* ⭐ 56-136 mA. Down between bursts, up for the next one; the
             * settle window that follows is two seconds of the largest current
             * in the design being switched off. */
            sb_cam_sleep(&s->cam, hal);
            go(s, SB_SENSE_AWAKE, now_ms);
        }
        return 30;
    }

    case SB_SENSE_SETTLING:
        /* ⭐ Waiting for the bag to stop moving, and the IMU is what says so.
         * The map is worth taking once; taking it while the bag swings spends
         * the same energy on an answer about where things were. */
        if (now_ms - s->state_since_ms < SB_SETTLE_MS) {
            return SB_SETTLE_MS - (now_ms - s->state_since_ms);
        }
        send(emit, ctx, SB_EV_STILL, 0, false, now_ms);
        sb_radar_up(sensors, hal);
        go(s, SB_SENSE_MAPPING, now_ms);
        return SB_RADAR_SETTLE_MS;

    case SB_SENSE_MAPPING: {
        /* ⚠️ One radar at a time: they share the SPI bus and each sweep is tens
         * of milliseconds. Measuring them together would need two buses, which
         * is not what hardware/netlist.py drew. */
        for (int i = 0; i < 2; i++) {
            uint16_t bins[SB_RADAR_BINS];
            if (sb_radar_measure(sensors, hal, (sb_radar_side)i, bins,
                                 SB_RADAR_BINS) == SB_SENS_OK) {
                s->radar_mm[i] = sb_sense_peak_mm(bins, SB_RADAR_BINS);
            } else {
                s->radar_mm[i] = 0;
                s->radar_failures++;
            }
        }
        sb_radar_down(sensors, hal);

        /* ⭐ AND THEN THE MATRIX, WHICH NEEDS NO MODEL AT ALL. A sweep is 96
         * numbers; sb_fsr_blobs turns them into regions with a centroid and a
         * summed load. That is where "where is it" and "how heavy is it" come
         * from, and neither has ever needed training. */
        if (!s->frame.calibrated) {
            sb_fsr_calibrate(fsr, SB_FSR_SCAN_TIA, &s->frame);
        }
        sb_fsr_scan(fsr, SB_FSR_SCAN_TIA, &s->frame);
        sb_fsr_blob blobs[SB_MAX_OBJECTS];
        const int n = sb_fsr_blobs(&s->frame, 40,
                                   FLOOR_W_MM * 1000 / SB_FSR_COLS,
                                   FLOOR_D_MM * 1000 / SB_FSR_ROWS,
                                   blobs, SB_MAX_OBJECTS);
        s->blob_count = (uint8_t)(n < 0 ? 0 : n);
        s->maps_done++;

        send(emit, ctx, SB_EV_MOTION, 0, false, now_ms);
        go(s, SB_SENSE_ASLEEP, now_ms);
        return 250;
    }
    }
    return 250;
}
