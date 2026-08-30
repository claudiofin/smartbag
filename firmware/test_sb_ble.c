/* Host tests for the GATT payloads.
 *
 * ⭐ WHAT IS WORTH TESTING here is not that bytes come out in an order. It is
 * the three claims the payload makes about itself: that a full inventory does
 * not fit in a default-MTU notification, that a low-confidence position cannot
 * carry coordinates, and that enrollment refuses an object it will not be able
 * to tell apart later. Each of those is a place where the easy implementation
 * lies to the app.
 */
#include "sb_ble.h"

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

static uint16_t rd_u16(const uint8_t *b) { return (uint16_t)(b[0] | (b[1] << 8)); }
static int16_t rd_i16(const uint8_t *b) { return (int16_t)rd_u16(b); }
static uint32_t rd_u32(const uint8_t *b)
{
    return (uint32_t)b[0] | ((uint32_t)b[1] << 8) | ((uint32_t)b[2] << 16)
           | ((uint32_t)b[3] << 24);
}

static void feed(sb_device *d, sb_event_kind k, uint32_t t, int32_t arg,
                 bool entering)
{
    sb_event e = {.kind = k, .at_ms = t, .arg = arg, .entering = entering};
    sb_feed(d, C, &e);
}

static uint32_t insert_object(sb_device *d, uint32_t t, uint16_t id)
{
    feed(d, SB_EV_CLOSURE_OPENED, t, 0, false);
    feed(d, SB_EV_TOF_CROSSED, t + 500, 0, false);
    for (int i = 0; i < SB_CAPTURE_FRAMES; i++) {
        feed(d, SB_EV_FRAME_READY, t + 520 + i * 13, 0, false);
    }
    feed(d, SB_EV_CLASSIFIED, t + 600, id, true);
    return t + 600;
}

/* ── inventory ───────────────────────────────────────────────────────────── */
static void test_inventory_round_trip(void)
{
    sb_device d;
    sb_init(&d, 0);
    uint32_t t = 1000;
    t = insert_object(&d, t, 7) + 1000;
    t = insert_object(&d, t, 9) + 1000;

    uint8_t buf[SB_BLE_MAX_PAYLOAD];
    int n = sb_ble_encode_inventory(&d, buf, sizeof(buf));
    CHECK(n == 6 + 2 * 8, "length %d", n);
    CHECK(buf[0] == SB_BLE_VERSION, "version %u", buf[0]);
    CHECK(buf[1] == 2, "count %u", buf[1]);
    CHECK(rd_u32(buf + 2) == d.ledger.seq, "seq %u", rd_u32(buf + 2));
    CHECK(rd_u16(buf + 6) == 7, "first id %u", rd_u16(buf + 6));
    CHECK(rd_u16(buf + 14) == 9, "second id %u", rd_u16(buf + 14));
}

static void test_inventory_never_truncates(void)
{
    /* ⚠️ A short read must be an error, not a shorter bag. */
    sb_device d;
    sb_init(&d, 0);
    insert_object(&d, 1000, 7);
    uint8_t small[10];
    CHECK(sb_ble_encode_inventory(&d, small, sizeof(small)) < 0,
          "encoder truncated instead of refusing");
}

static void test_inventory_does_not_fit_a_notification(void)
{
    /* ⛔ The finding. A full bag is 198 bytes; the default ATT MTU leaves 20,
     * and notifications cannot be fragmented. Either the phone negotiates a
     * bigger MTU or the app reads the characteristic instead of listening. */
    sb_device d;
    sb_init(&d, 0);
    uint32_t t = 1000;
    for (uint16_t i = 0; i < SB_MAX_OBJECTS; i++) {
        t = insert_object(&d, t, (uint16_t)(100 + i)) + 1000;
    }
    uint8_t buf[SB_BLE_MAX_PAYLOAD];
    int n = sb_ble_encode_inventory(&d, buf, sizeof(buf));
    CHECK(n == 6 + SB_MAX_OBJECTS * 8, "full inventory is %d bytes", n);
    CHECK(!sb_ble_fits(n, SB_ATT_DEFAULT_MTU),
          "a full inventory must not be claimed to fit the default MTU");
    CHECK(sb_ble_fits(n, 247), "it must fit a negotiated 247-byte MTU");

    uint16_t need = (uint16_t)(n + SB_ATT_HEADER);
    printf("  inventory: %d objects is %d bytes, needs MTU >= %u "
           "(default is %d)\n", SB_MAX_OBJECTS, n, need, SB_ATT_DEFAULT_MTU);

    /* The live path was sized to survive without negotiation, and does. */
    int ev = sb_ble_encode_event(SB_EVT_OBJECT_IN, 7, 12345, buf, sizeof(buf));
    CHECK(sb_ble_fits(ev, SB_ATT_DEFAULT_MTU),
          "events must work on an unnegotiated link");
}

/* ── positions ───────────────────────────────────────────────────────────── */
static void test_low_confidence_withholds_coordinates(void)
{
    sb_device d;
    sb_init(&d, 0);
    d.map.valid = true;
    d.map.measured_at_ms = 10000;
    d.map.disturbance = 0;

    sb_ble_position p[2] = {
        {.object_id = 7, .x_um = 189800, .y_um = 39000,
         .compartment = 2, .confidence = 200},
        /* ⚠️ Same coordinates, no confidence. The device knows the compartment
         * and does not know the point. */
        {.object_id = 9, .x_um = 189800, .y_um = 39000,
         .compartment = 2, .confidence = SB_CONFIDENCE_FLOOR - 1},
    };
    uint8_t buf[SB_BLE_MAX_PAYLOAD];
    int n = sb_ble_encode_position(&d, C, p, 2, 70000, buf, sizeof(buf));
    CHECK(n == 7 + 2 * 8, "length %d", n);
    CHECK(rd_u32(buf + 3) == 60, "measured_ago %u s", rd_u32(buf + 3));

    CHECK(rd_i16(buf + 9) == 190, "confident x %d mm", rd_i16(buf + 9));
    CHECK(rd_i16(buf + 11) == 39, "confident y %d mm", rd_i16(buf + 11));
    CHECK(buf[13] == 2, "compartment %u", buf[13]);

    CHECK(rd_i16(buf + 17) == SB_POS_UNKNOWN,
          "low-confidence x leaked a coordinate: %d", rd_i16(buf + 17));
    CHECK(rd_i16(buf + 19) == SB_POS_UNKNOWN, "low-confidence y leaked");
    CHECK(buf[21] == 2, "the compartment must survive the suppression, got %u",
          buf[21]);
}

static void test_a_map_never_measured_places_nothing(void)
{
    /* ⛔ Per-entry confidence is not enough. A map with staleness 255 has no
     * business emitting a coordinate for anything, however confident the
     * assignment was when it was made. */
    sb_device d;
    sb_init(&d, 0);
    d.map.valid = false;
    sb_ble_position p = {.object_id = 7, .x_um = 189800, .y_um = 39000,
                         .compartment = 2, .confidence = 255};
    uint8_t buf[SB_BLE_MAX_PAYLOAD];
    int n = sb_ble_encode_position(&d, C, &p, 1, 70000, buf, sizeof(buf));
    CHECK(n == 7 + 8, "length %d", n);
    CHECK(buf[2] == 255, "staleness %u", buf[2]);
    CHECK(rd_u32(buf + 3) == 0xFFFFFFFFu, "measured_ago must be the sentinel");
    CHECK(rd_i16(buf + 9) == SB_POS_UNKNOWN,
          "a never-measured map emitted x = %d", rd_i16(buf + 9));
    CHECK(rd_i16(buf + 11) == SB_POS_UNKNOWN, "and y");
    CHECK(buf[13] == 2, "the compartment still survives, got %u", buf[13]);
}

static void test_staleness_tracks_disturbance(void)
{
    sb_device d;
    sb_init(&d, 0);
    CHECK(sb_ble_staleness(&d, C) == 255,
          "a device that has never measured must report maximum staleness");

    d.map.valid = true;
    d.map.disturbance = 0;
    CHECK(sb_ble_staleness(&d, C) == 0, "fresh map is not 0");
    d.map.disturbance = C->stale_threshold / 2;
    uint8_t half = sb_ble_staleness(&d, C);
    CHECK(half > 100 && half < 155, "half-shaken map reads %u", half);
    d.map.disturbance = C->stale_threshold * 10;
    CHECK(sb_ble_staleness(&d, C) == 255, "saturation failed");
}

static void test_resync(void)
{
    sb_device d;
    sb_init(&d, 0);
    CHECK(!sb_ble_needs_resync(&d, 0), "nothing has happened yet");
    insert_object(&d, 1000, 7);
    CHECK(sb_ble_needs_resync(&d, 0),
          "an app that missed an event must be told to resync");
    CHECK(!sb_ble_needs_resync(&d, d.ledger.seq), "a caught-up app must not");
}

/* ── enrollment ──────────────────────────────────────────────────────────── */
static uint16_t g_conflict_with;

static bool similar_stub(void *ctx, uint16_t candidate, uint16_t *conflict)
{
    (void)ctx; (void)candidate;
    if (g_conflict_with) {
        *conflict = g_conflict_with;
        return true;
    }
    return false;
}

static int begin(sb_enroll *e, sb_device *d, uint16_t id, uint8_t klass,
                 const char *label, uint8_t *out)
{
    uint8_t req[4 + SB_ENROLL_LABEL_MAX];
    size_t n = strlen(label);
    req[0] = SB_ENROLL_CMD_BEGIN;
    req[1] = (uint8_t)(id & 0xFF);
    req[2] = (uint8_t)(id >> 8);
    req[3] = klass;
    memcpy(req + 4, label, n);
    return sb_enroll_write(e, d, req, 4 + n, 1000, out, 8);
}

static int commit(sb_enroll *e, sb_device *d, uint8_t *out)
{
    uint8_t req[1] = {SB_ENROLL_CMD_COMMIT};
    return sb_enroll_write(e, d, req, 1, 2000, out, 8);
}

static void test_enrollment_happy_path(void)
{
    sb_device d; sb_init(&d, 0);
    sb_enroll e; sb_enroll_init(&e, 500);
    g_conflict_with = 0;
    e.too_similar = similar_stub;

    uint8_t out[8];
    CHECK(begin(&e, &d, 0, 3, "black wallet", out) == 4, "begin length");
    CHECK(out[0] == SB_ENROLL_READY, "status %u", out[0]);
    CHECK(rd_u16(out + 2) == 500, "device must allocate an id, got %u",
          rd_u16(out + 2));

    for (int i = 0; i < SB_ENROLL_MIN_SAMPLES + 2; i++) {
        sb_enroll_sample(&e, true);
    }
    CHECK(commit(&e, &d, out) == 4, "commit length");
    CHECK(out[0] == SB_ENROLL_COMMITTED, "status %u", out[0]);
    CHECK(out[1] == SB_ENROLL_MIN_SAMPLES + 2, "sample count %u", out[1]);
    CHECK(d.ledger.count == 1, "object not added to the ledger");
    /* ⚠️ Enrolled is not the same as inside. Registering a wallet at the
     * kitchen table must not make the bag claim to be carrying it. */
    CHECK(!d.ledger.items[0].present,
          "enrollment must not mark the object as present");
}

static void test_enrollment_rejects_a_lookalike(void)
{
    /* ⛔ The one that matters. Closed-set recognition confuses inseparable
     * objects forever, so the refusal has to happen here, with the conflicting
     * id attached so the app can name it. */
    sb_device d; sb_init(&d, 0);
    sb_enroll e; sb_enroll_init(&e, 500);
    e.too_similar = similar_stub;
    g_conflict_with = 42;

    uint8_t out[8];
    begin(&e, &d, 0, 3, "the other black wallet", out);
    for (int i = 0; i < 10; i++) {
        sb_enroll_sample(&e, true);
    }
    CHECK(commit(&e, &d, out) == 4, "commit length");
    CHECK(out[0] == SB_ENROLL_FAILED, "status %u", out[0]);
    CHECK(out[1] == SB_ENROLL_FAIL_TOO_SIMILAR, "reason %u", out[1]);
    CHECK(rd_u16(out + 2) == 42, "must name the conflict, got %u",
          rd_u16(out + 2));
    CHECK(d.ledger.count == 0, "a rejected object must not reach the ledger");
    g_conflict_with = 0;
}

static void test_enrollment_rejects_too_few_and_too_dark(void)
{
    sb_device d; sb_init(&d, 0);
    sb_enroll e; sb_enroll_init(&e, 500);
    uint8_t out[8];

    begin(&e, &d, 0, 3, "keys", out);
    sb_enroll_sample(&e, true);
    commit(&e, &d, out);
    CHECK(out[0] == SB_ENROLL_FAILED && out[1] == SB_ENROLL_FAIL_TOO_FAST,
          "one sample accepted: %u/%u", out[0], out[1]);

    begin(&e, &d, 0, 3, "keys", out);
    for (int i = 0; i < 8; i++) {
        sb_enroll_sample(&e, true);
    }
    for (int i = 0; i < 9; i++) {
        sb_enroll_sample(&e, false);
    }
    commit(&e, &d, out);
    /* Darkness is diagnosed ahead of scarcity: it tells the user what to fix. */
    CHECK(out[0] == SB_ENROLL_FAILED && out[1] == SB_ENROLL_FAIL_TOO_DARK,
          "mostly-dark burst accepted: %u/%u", out[0], out[1]);
    CHECK(d.ledger.count == 0, "failed enrollments reached the ledger");
}

static void test_commit_without_begin_is_refused(void)
{
    sb_device d; sb_init(&d, 0);
    sb_enroll e; sb_enroll_init(&e, 500);
    uint8_t out[8];
    CHECK(commit(&e, &d, out) == 4, "length");
    CHECK(out[0] == SB_ENROLL_FAILED && out[1] == SB_ENROLL_FAIL_PROTOCOL,
          "a bare commit was accepted: %u/%u", out[0], out[1]);
    CHECK(d.ledger.count == 0, "phantom object created");
}

static void test_enrollment_ids_do_not_collide(void)
{
    sb_device d; sb_init(&d, 0);
    sb_enroll e; sb_enroll_init(&e, 500);
    uint8_t out[8];
    uint16_t first, second;
    begin(&e, &d, 0, 1, "a", out);
    first = rd_u16(out + 2);
    for (int i = 0; i < 8; i++) sb_enroll_sample(&e, true);
    commit(&e, &d, out);
    begin(&e, &d, 0, 1, "b", out);
    second = rd_u16(out + 2);
    CHECK(first != second, "reused id %u", first);
    /* A non-zero id is a re-enrollment and must be honoured verbatim. */
    begin(&e, &d, 77, 1, "c", out);
    CHECK(rd_u16(out + 2) == 77, "re-enrollment id ignored: %u",
          rd_u16(out + 2));
}

int main(void)
{
    printf("sb_ble: GATT payloads\n");
    test_inventory_round_trip();
    test_inventory_never_truncates();
    test_inventory_does_not_fit_a_notification();
    test_low_confidence_withholds_coordinates();
    test_a_map_never_measured_places_nothing();
    test_staleness_tracks_disturbance();
    test_resync();
    test_enrollment_happy_path();
    test_enrollment_rejects_a_lookalike();
    test_enrollment_rejects_too_few_and_too_dark();
    test_commit_without_begin_is_refused();
    test_enrollment_ids_do_not_collide();
    printf("%d checks, %d failures\n", checks, failures);
    return failures ? 1 : 0;
}
