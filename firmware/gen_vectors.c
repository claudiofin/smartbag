/* Emit golden GATT payloads as JSON, so the phone side can be tested against
 * the device side without either one existing.
 *
 * ⭐ WHY THIS FILE EXISTS. docs/app-and-ble.md says the interface is the part
 * worth pinning down early "because it is where the two halves have to agree".
 * A document cannot enforce agreement. These vectors can: the C encoder writes
 * them, the JavaScript decoder reads them, and app/test_protocol.mjs fails if
 * the two ever drift. Change a field width on either side and a test goes red
 * instead of a phone quietly rendering the wrong object's position.
 *
 * Usage:  make -C firmware vectors   (writes app/vectors.json)
 */
#include "sb_ble.h"

#include <stdio.h>
#include <string.h>

static const sb_config *C = &SB_DEFAULTS;
static int first = 1;

static void emit(const char *name, const uint8_t *b, int n, const char *note)
{
    if (n < 0) {
        fprintf(stderr, "encoder refused for %s\n", name);
        return;
    }
    printf("%s\n  \"%s\": { \"note\": \"%s\", \"hex\": \"",
           first ? "" : ",", name, note);
    first = 0;
    for (int i = 0; i < n; i++) {
        printf("%02x", b[i]);
    }
    printf("\" }");
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

static bool never_similar(void *ctx, uint16_t c, uint16_t *out)
{
    (void)ctx; (void)c; (void)out;
    return false;
}
static bool always_similar(void *ctx, uint16_t c, uint16_t *out)
{
    (void)ctx; (void)c;
    *out = 42;
    return true;
}

int main(void)
{
    uint8_t buf[SB_BLE_MAX_PAYLOAD];
    printf("{");

    /* two objects in the bag */
    sb_device d;
    sb_init(&d, 0);
    uint32_t t = 1000;
    t = insert_object(&d, t, 7) + 1000;
    t = insert_object(&d, t, 9) + 1000;
    emit("inventory_two", buf, sb_ble_encode_inventory(&d, buf, sizeof(buf)),
         "a wallet and a set of keys");

    /* a full bag: the payload that does not fit a default-MTU notification */
    sb_device full;
    sb_init(&full, 0);
    uint32_t ft = 1000;
    for (uint16_t i = 0; i < SB_MAX_OBJECTS; i++) {
        ft = insert_object(&full, ft, (uint16_t)(100 + i)) + 1000;
    }
    emit("inventory_full", buf,
         sb_ble_encode_inventory(&full, buf, sizeof(buf)),
         "24 objects, 198 bytes, needs a negotiated MTU");

    /* one confident position and one the device refuses to place */
    d.map.valid = true;
    d.map.measured_at_ms = 10000;
    d.map.disturbance = C->stale_threshold / 4;
    sb_ble_position pos[2] = {
        {.object_id = 7, .x_um = 189800, .y_um = 39000,
         .compartment = 2, .confidence = 200},
        {.object_id = 9, .x_um = 28100, .y_um = 32500,
         .compartment = 0, .confidence = 40},
    };
    emit("position_mixed", buf,
         sb_ble_encode_position(&d, C, pos, 2, 70000, buf, sizeof(buf)),
         "object 7 placed; object 9 known only to a compartment");

    sb_device shaken;
    sb_init(&shaken, 0);
    shaken.map.valid = false;
    emit("position_never_measured", buf,
         sb_ble_encode_position(&shaken, C, pos, 2, 70000, buf, sizeof(buf)),
         "staleness 255: the device has never measured");

    emit("event_object_in", buf,
         sb_ble_encode_event(SB_EVT_OBJECT_IN, 7, 123456, buf, sizeof(buf)),
         "the live path, small enough for an unnegotiated link");
    emit("event_low_battery", buf,
         sb_ble_encode_event(SB_EVT_LOW_BATTERY, 0, 999000, buf, sizeof(buf)),
         "no object id");

    emit("device_info", buf,
         sb_ble_encode_device_info(&d, 3600000, 74, 0x0103, 0, buf,
                                   sizeof(buf)),
         "battery 74%, firmware 1.3, no taxel faults");

    /* enrollment replies */
    sb_enroll e;
    uint8_t req[32];
    sb_enroll_init(&e, 500);
    e.too_similar = never_similar;
    req[0] = SB_ENROLL_CMD_BEGIN; req[1] = 0; req[2] = 0; req[3] = 3;
    memcpy(req + 4, "black wallet", 12);
    emit("enroll_ready", buf,
         sb_enroll_write(&e, &d, req, 16, 1000, buf, sizeof(buf)),
         "device allocated id 500");
    for (int i = 0; i < 8; i++) {
        sb_enroll_sample(&e, true);
    }
    req[0] = SB_ENROLL_CMD_COMMIT;
    emit("enroll_committed", buf,
         sb_enroll_write(&e, &d, req, 1, 2000, buf, sizeof(buf)),
         "8 usable samples");

    sb_enroll_init(&e, 501);
    e.too_similar = always_similar;
    req[0] = SB_ENROLL_CMD_BEGIN; req[1] = 0; req[2] = 0; req[3] = 3;
    sb_enroll_write(&e, &d, req, 4, 3000, buf, sizeof(buf));
    for (int i = 0; i < 8; i++) {
        sb_enroll_sample(&e, true);
    }
    req[0] = SB_ENROLL_CMD_COMMIT;
    emit("enroll_too_similar", buf,
         sb_enroll_write(&e, &d, req, 1, 4000, buf, sizeof(buf)),
         "not separable from object 42");

    sb_enroll_init(&e, 502);
    e.too_similar = never_similar;
    req[0] = SB_ENROLL_CMD_BEGIN;
    sb_enroll_write(&e, &d, req, 4, 5000, buf, sizeof(buf));
    for (int i = 0; i < 2; i++) sb_enroll_sample(&e, true);
    for (int i = 0; i < 7; i++) sb_enroll_sample(&e, false);
    req[0] = SB_ENROLL_CMD_COMMIT;
    emit("enroll_too_dark", buf,
         sb_enroll_write(&e, &d, req, 1, 6000, buf, sizeof(buf)),
         "mostly unusable frames");

    printf("\n}\n");
    return 0;
}
