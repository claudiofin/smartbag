/* Host tests for the SmartBag core.
 *
 * ⭐ WHAT IS WORTH TESTING HERE is not that a state machine changes state. It
 * is that the expensive things happen rarely and only when they should: that a
 * bouncing zip does not fire the camera, that a walk cannot trigger a
 * measurement, that a stuck sensor cannot leave the camera powered, and that
 * the device never claims to know where something is after it has been shaken.
 *
 * Build and run:  make -C firmware test
 */
#include "smartbag.h"

#include <stdio.h>
#include <string.h>

static int failures;
static int checks;

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

static const sb_config *C = &SB_DEFAULTS;

static void feed(sb_device *d, sb_event_kind k, uint32_t t, int32_t arg,
                 bool entering)
{
    sb_event e = {.kind = k, .at_ms = t, .arg = arg, .entering = entering};
    sb_feed(d, C, &e);
}

/* Drive one full "object goes in" sequence, returning the time it ends. */
static uint32_t insert_object(sb_device *d, uint32_t t, uint16_t id)
{
    feed(d, SB_EV_CLOSURE_OPENED, t, 0, false);
    feed(d, SB_EV_TOF_CROSSED, t + 500, 0, false);
    for (int i = 0; i < SB_CAPTURE_FRAMES; i++)
        feed(d, SB_EV_FRAME_READY, t + 520 + i * 13, 0, false);
    feed(d, SB_EV_CLASSIFIED, t + 600, id, true);
    return t + 600;
}

static void test_starts_asleep(void)
{
    sb_device d;
    sb_init(&d, 0);
    CHECK(d.state == SB_SLEEP, "state %d", d.state);
    CHECK(sb_map_is_stale(&d, C), "a device that has never measured must not "
                                  "claim a valid map");
    CHECK(sb_energy_uah_x1000(&d) == 0, "idle device spent charge");
}

static void test_hall_bounce_does_not_fire_the_camera(void)
{
    sb_device d;
    sb_init(&d, 0);
    /* A slider dragged past the magnet: five edges in 30 ms. */
    for (int i = 0; i < 5; i++)
        feed(&d, i % 2 ? SB_EV_CLOSURE_CLOSED : SB_EV_CLOSURE_OPENED,
             1000 + i * 6, 0, false);
    CHECK(d.hall_bounces_rejected == 4, "rejected %u of 4 bounces",
          d.hall_bounces_rejected);
    CHECK(d.state == SB_OPEN, "state %d", d.state);

    feed(&d, SB_EV_TOF_CROSSED, 1200, 0, false);
    CHECK(d.camera_bursts == 1, "%u bursts, expected exactly 1",
          d.camera_bursts);
}

static void test_tof_only_arms_when_open(void)
{
    sb_device d;
    sb_init(&d, 0);
    feed(&d, SB_EV_TOF_CROSSED, 100, 0, false);   /* bag shut */
    CHECK(d.camera_bursts == 0, "ToF fired the camera through a closed bag");

    feed(&d, SB_EV_CLOSURE_OPENED, 200, 0, false);
    feed(&d, SB_EV_TOF_CROSSED, 300, 0, false);
    feed(&d, SB_EV_TOF_CROSSED, 340, 0, false);   /* same object, still moving */
    CHECK(d.camera_bursts == 1, "%u bursts: one object must not fire twice",
          d.camera_bursts);
}

static void test_capture_timeout_releases_the_camera(void)
{
    sb_device d;
    sb_init(&d, 0);
    feed(&d, SB_EV_CLOSURE_OPENED, 0, 0, false);
    feed(&d, SB_EV_TOF_CROSSED, 100, 0, false);
    feed(&d, SB_EV_FRAME_READY, 120, 0, false);   /* then the sensor hangs */
    sb_tick(&d, C, 100 + C->capture_timeout_ms + 1);
    CHECK(d.state == SB_OPEN, "state %d: a stuck sensor kept the camera on",
          d.state);
}

static void test_closing_beats_everything(void)
{
    sb_device d;
    sb_init(&d, 0);
    feed(&d, SB_EV_CLOSURE_OPENED, 0, 0, false);
    feed(&d, SB_EV_TOF_CROSSED, 100, 0, false);
    feed(&d, SB_EV_CLOSURE_CLOSED, 200, 0, false);
    CHECK(d.state == SB_SLEEP, "state %d", d.state);
    feed(&d, SB_EV_FRAME_READY, 220, 0, false);
    CHECK(d.frames_captured == 0, "frames arrived after the bag shut");
}

static void test_ledger_tracks_in_and_out(void)
{
    sb_device d;
    sb_init(&d, 0);
    insert_object(&d, 0, 42);
    CHECK(sb_holds(&d, 42), "object not in the inventory after going in");
    CHECK(d.ledger.seq == 1, "seq %u", d.ledger.seq);

    /* Take it out again. */
    uint32_t t = 10000;
    feed(&d, SB_EV_CLOSURE_OPENED, t, 0, false);
    feed(&d, SB_EV_TOF_CROSSED, t + 100, 0, false);
    feed(&d, SB_EV_CLASSIFIED, t + 200, 42, false);
    CHECK(!sb_holds(&d, 42), "object still present after leaving");
    CHECK(d.ledger.seq == 2, "seq %u", d.ledger.seq);
    CHECK(d.ledger.count == 1, "count %u: leaving must not delete the entry",
          d.ledger.count);

    uint16_t ids[8];
    CHECK(sb_inventory(&d, ids, 8) == 0, "inventory not empty");
}

static void test_walking_never_triggers_a_measurement(void)
{
    sb_device d;
    sb_init(&d, 0);
    uint32_t t = insert_object(&d, 0, 7);
    CHECK(d.state == SB_SETTLE, "state %d", d.state);

    /* Two minutes of walking: a motion chunk every 200 ms. */
    for (int i = 0; i < 600; i++) {
        t += 200;
        feed(&d, SB_EV_MOTION, t, 90, false);
        sb_tick(&d, C, t);
    }
    CHECK(d.radar_pings == 0, "%u radar pings while walking", d.radar_pings);
    CHECK(sb_map_is_stale(&d, C), "map claimed valid after a two-minute walk");

    /* Set the bag down. */
    t += C->settle_ms + 1;
    sb_tick(&d, C, t);
    CHECK(d.radar_pings == 1, "%u pings after settling, expected 1",
          d.radar_pings);
    CHECK(!sb_map_is_stale(&d, C), "map still stale right after measuring");
    CHECK(d.state == SB_SLEEP, "state %d: must go straight back to sleep",
          d.state);
}

static void test_map_goes_stale_again_with_motion(void)
{
    sb_device d;
    sb_init(&d, 0);
    uint32_t t = insert_object(&d, 0, 9);
    t += C->settle_ms + 1;
    sb_tick(&d, C, t);
    CHECK(!sb_map_is_stale(&d, C), "map not valid after measuring");

    feed(&d, SB_EV_MOTION, t + 100, (int32_t)C->stale_threshold - 1, false);
    CHECK(!sb_map_is_stale(&d, C), "a nudge should not void the map");
    feed(&d, SB_EV_MOTION, t + 200, 2, false);
    CHECK(sb_map_is_stale(&d, C), "map survived motion past the threshold");
}

static void test_energy_shape(void)
{
    /* ⚠️ Estimates, not measurements — see sb_energy_uah_x1000. The point of
     * the assertion is the SHAPE: a heavy day of use has to be negligible
     * against a 2000 mAh cell, or the wake-up chain is not worth its
     * complexity. */
    sb_device d;
    sb_init(&d, 0);
    uint32_t t = 0;
    for (int i = 0; i < 40; i++) {
        t = insert_object(&d, t + 20000, (uint16_t)(100 + i));
        t += C->settle_ms + 1;
        sb_tick(&d, C, t);
    }
    uint32_t uah = sb_energy_uah_x1000(&d) / 1000;
    CHECK(d.camera_bursts == 40 && d.radar_pings == 40, "%u bursts, %u pings",
          d.camera_bursts, d.radar_pings);
    CHECK(uah < 1000, "%u uAh for a heavy day: that is no longer negligible",
          uah);
    printf("  note  40 insertions + 40 remaps ~ %u uAh, "
           "%.3f%% of a 2000 mAh cell\n", uah, uah / 20000.0);
}

int main(void)
{
    printf("firmware/test_smartbag\n");
    test_starts_asleep();
    test_hall_bounce_does_not_fire_the_camera();
    test_tof_only_arms_when_open();
    test_capture_timeout_releases_the_camera();
    test_closing_beats_everything();
    test_ledger_tracks_in_and_out();
    test_walking_never_triggers_a_measurement();
    test_map_goes_stale_again_with_motion();
    test_energy_shape();
    printf("%s  %d checks, %d failures\n", failures ? "FAILED" : "ok",
           checks, failures);
    return failures ? 1 : 0;
}
