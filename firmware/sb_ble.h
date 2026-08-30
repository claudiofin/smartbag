/* The GATT payloads from docs/app-and-ble.md, and the rules that go with them.
 *
 * ⛔ THIS IS NOT A BLUETOOTH STACK. There is no link layer, no L2CAP, no
 * security manager, no vendor SDK. What is here is the part that is actually
 * specified and actually decidable: the byte layout of each characteristic, the
 * enrollment handshake, and the three rules that decide whether the app is
 * being told the truth. Bind it to NimBLE or a SoftDevice by handing these
 * buffers to whatever that stack calls a notify.
 *
 * ⭐ THE THREE RULES, because they are the reason this file is not just structs:
 *
 *   1. A POSITION WITH LOW CONFIDENCE MUST NOT CARRY COORDINATES. The spec is
 *      explicit that `compartment` is not derived from `x`. When the device is
 *      not sure, it sends the compartment it is sure of and SB_POS_UNKNOWN for
 *      x and y, so the app physically cannot draw a dot. A confident-looking
 *      dot in the wrong place is worse than no dot.
 *
 *   2. STALENESS TRAVELS WITH THE MAP. Positions are measurements with an age,
 *      and the age is in the payload, not inferred by the app from when the
 *      notification arrived.
 *
 *   3. THE INVENTORY DOES NOT FIT IN A NOTIFICATION. 24 objects is 198 bytes
 *      against the 20 the default ATT MTU leaves. Notifications cannot be
 *      fragmented — only reads can. sb_ble_fits() exists so that this fails
 *      loudly at build-and-test time instead of silently truncating the
 *      inventory on a phone that declined to negotiate.
 */
#ifndef SB_BLE_H
#define SB_BLE_H

#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>

#include "smartbag.h"

#define SB_BLE_VERSION 1
#define SB_ATT_DEFAULT_MTU 23
#define SB_ATT_HEADER 3               /* opcode + handle */
#define SB_BLE_MAX_PAYLOAD 244        /* what a 247-byte MTU leaves */

/* Sentinel for "I know the compartment, not the coordinates". */
#define SB_POS_UNKNOWN INT16_MIN
#define SB_COMPARTMENT_UNKNOWN 255

/* Below this, coordinates are suppressed and only the compartment survives. */
#define SB_CONFIDENCE_FLOOR 96

/* Inventory entry flags */
#define SB_FLAG_CAMERA_CONFIRMED 0x01
#define SB_FLAG_MASS_ONLY        0x02

typedef enum {
    SB_EVT_CLOSURE_OPENED = 1,
    SB_EVT_CLOSURE_CLOSED = 2,
    SB_EVT_OBJECT_IN = 3,
    SB_EVT_OBJECT_OUT = 4,
    SB_EVT_REMAP_DONE = 5,
    SB_EVT_LOW_BATTERY = 6,
} sb_ble_event_type;

typedef struct {
    uint16_t object_id;
    int32_t x_um, y_um;               /* what sb_fsr_blobs produced */
    uint8_t compartment;
    uint8_t confidence;               /* 0..255 from the assignment cost */
} sb_ble_position;

/* Every encoder returns the number of bytes written, or a negative value if the
 * buffer was too small. ⚠️ Never a truncated payload: a short inventory is
 * indistinguishable from an emptied bag. */
int sb_ble_encode_inventory(const sb_device *d, uint8_t *buf, size_t cap);
int sb_ble_encode_position(const sb_device *d, const sb_config *cfg,
                           const sb_ble_position *pos, int n,
                           uint32_t now_ms, uint8_t *buf, size_t cap);
int sb_ble_encode_event(sb_ble_event_type type, uint16_t object_id,
                        uint32_t timestamp, uint8_t *buf, size_t cap);
int sb_ble_encode_device_info(const sb_device *d, uint32_t now_ms,
                              uint8_t battery_pct, uint16_t fw,
                              uint8_t taxel_faults, uint8_t *buf, size_t cap);

/* 0 = just measured, 255 = shaken past the point of belief. */
uint8_t sb_ble_staleness(const sb_device *d, const sb_config *cfg);

/* Does a payload of `len` survive a notification at this MTU? */
bool sb_ble_fits(int len, uint16_t mtu);

/* ⭐ The app sends the last ledger_seq it saw; the device says whether the app
 * missed anything while out of range. Cheaper than buffering notifications for
 * a phone that may never come back. */
bool sb_ble_needs_resync(const sb_device *d, uint32_t app_seq);

/* ── enrollment ───────────────────────────────────────────────────────────── */
typedef enum {
    SB_ENROLL_CMD_BEGIN = 1,
    SB_ENROLL_CMD_COMMIT = 2,
    SB_ENROLL_CMD_ABORT = 3,
    SB_ENROLL_CMD_FORGET = 4,
} sb_enroll_cmd;

typedef enum {
    SB_ENROLL_READY = 1,
    SB_ENROLL_CAPTURED = 2,
    SB_ENROLL_COMMITTED = 3,
    SB_ENROLL_FAILED = 4,
} sb_enroll_status;

typedef enum {
    SB_ENROLL_FAIL_TOO_DARK = 1,
    SB_ENROLL_FAIL_TOO_FAST = 2,     /* not enough usable samples */
    SB_ENROLL_FAIL_TOO_SIMILAR = 3,  /* and the conflicting id comes with it */
    SB_ENROLL_FAIL_PROTOCOL = 4,
    SB_ENROLL_FAIL_FULL = 5,
} sb_enroll_failure;

#define SB_ENROLL_MIN_SAMPLES 5
#define SB_ENROLL_LABEL_MAX 24

typedef struct {
    bool active;
    uint16_t object_id;
    uint8_t klass;
    uint8_t samples;
    uint8_t dark_samples;
    char label[SB_ENROLL_LABEL_MAX + 1];
    uint16_t next_id;
    /* ⚠️ Supplied by the caller because separability is the recognition
     * model's business, not the radio's. Returns true and fills `conflict` if
     * the candidate cannot be told apart from something already enrolled. */
    bool (*too_similar)(void *ctx, uint16_t candidate, uint16_t *conflict);
    void *ctx;
} sb_enroll;

void sb_enroll_init(sb_enroll *e, uint16_t first_id);

/* Feed one written ATT payload. Writes the indication into `out` and returns
 * its length, or negative on a malformed write. */
int sb_enroll_write(sb_enroll *e, sb_device *d, const uint8_t *req, size_t len,
                    uint32_t now_ms, uint8_t *out, size_t cap);

/* One captured frame during enrollment. `usable` is false for a frame the
 * pipeline rejected — too dark, too motion-blurred. */
void sb_enroll_sample(sb_enroll *e, bool usable);

#endif /* SB_BLE_H */
