#include "sb_ble.h"

#include <string.h>

/* Explicit little-endian writers. ⚠️ Not memcpy of a packed struct: the wire
 * format has to be identical on the MCU and on a phone, and struct layout is
 * the compiler's opinion, not a specification. */
static void put_u8(uint8_t *b, size_t *o, uint8_t v) { b[(*o)++] = v; }
static void put_u16(uint8_t *b, size_t *o, uint16_t v)
{
    b[(*o)++] = (uint8_t)(v & 0xFF);
    b[(*o)++] = (uint8_t)(v >> 8);
}
static void put_i16(uint8_t *b, size_t *o, int16_t v)
{
    put_u16(b, o, (uint16_t)v);
}
static void put_u32(uint8_t *b, size_t *o, uint32_t v)
{
    b[(*o)++] = (uint8_t)(v & 0xFF);
    b[(*o)++] = (uint8_t)((v >> 8) & 0xFF);
    b[(*o)++] = (uint8_t)((v >> 16) & 0xFF);
    b[(*o)++] = (uint8_t)((v >> 24) & 0xFF);
}

bool sb_ble_fits(int len, uint16_t mtu)
{
    return len >= 0 && (uint32_t)len + SB_ATT_HEADER <= mtu;
}

bool sb_ble_needs_resync(const sb_device *d, uint32_t app_seq)
{
    return app_seq != d->ledger.seq;
}

uint8_t sb_ble_staleness(const sb_device *d, const sb_config *cfg)
{
    if (!d->map.valid) {
        return 255;
    }
    if (cfg->stale_threshold == 0) {
        return 0;
    }
    uint64_t s = (uint64_t)d->map.disturbance * 255u / cfg->stale_threshold;
    return s > 255u ? 255u : (uint8_t)s;
}

int sb_ble_encode_inventory(const sb_device *d, uint8_t *buf, size_t cap)
{
    uint8_t count = 0;
    for (uint8_t i = 0; i < d->ledger.count; i++) {
        if (d->ledger.items[i].present) {
            count++;
        }
    }
    size_t need = 6u + (size_t)count * 8u;
    if (cap < need) {
        return -1;
    }

    size_t o = 0;
    put_u8(buf, &o, SB_BLE_VERSION);
    put_u8(buf, &o, count);
    put_u32(buf, &o, d->ledger.seq);
    for (uint8_t i = 0; i < d->ledger.count; i++) {
        const sb_object *it = &d->ledger.items[i];
        if (!it->present) {
            continue;
        }
        put_u16(buf, &o, it->id);
        put_u8(buf, &o, it->klass);
        /* ⚠️ The flag matters to the app: an object held on mass alone is one
         * the camera never confirmed, and the UI is entitled to say so. */
        put_u8(buf, &o, SB_FLAG_CAMERA_CONFIRMED);
        put_u32(buf, &o, it->since_ms / 1000u);
    }
    return (int)o;
}

int sb_ble_encode_position(const sb_device *d, const sb_config *cfg,
                           const sb_ble_position *pos, int n,
                           uint32_t now_ms, uint8_t *buf, size_t cap)
{
    if (n < 0 || n > 255) {
        return -2;
    }
    size_t need = 7u + (size_t)n * 8u;
    if (cap < need) {
        return -1;
    }

    uint32_t ago = d->map.valid && now_ms >= d->map.measured_at_ms
                   ? (now_ms - d->map.measured_at_ms) / 1000u
                   : 0xFFFFFFFFu;

    uint8_t stale = sb_ble_staleness(d, cfg);
    /* ⛔ Caught by looking at a golden vector rather than by a test: a map that
     * has never been measured was still emitting per-object coordinates,
     * because confidence is per entry and staleness is per map. Two hundred
     * millimetres from a measurement that never happened is exactly the
     * confident font the whole document warns about. At full staleness nothing
     * gets coordinates, whatever its individual confidence says. */
    bool suppress_all = (stale == 255);

    size_t o = 0;
    put_u8(buf, &o, SB_BLE_VERSION);
    put_u8(buf, &o, (uint8_t)n);
    put_u8(buf, &o, stale);
    put_u32(buf, &o, ago);

    for (int i = 0; i < n; i++) {
        put_u16(buf, &o, pos[i].object_id);
        /* ── rule 1, and it is enforced here rather than trusted to callers ──
         * Under the confidence floor the coordinates are withheld. Note that
         * the compartment is NOT withheld with them: knowing something is in
         * the right-hand third is a real answer, and the two fields exist
         * separately so the device can give it. */
        if (suppress_all || pos[i].confidence < SB_CONFIDENCE_FLOOR) {
            put_i16(buf, &o, SB_POS_UNKNOWN);
            put_i16(buf, &o, SB_POS_UNKNOWN);
        } else {
            /* micrometres in, millimetres out: the wire format's resolution,
             * and about the resolution a 14 mm taxel pitch can support. */
            int32_t xmm = (pos[i].x_um + (pos[i].x_um >= 0 ? 500 : -500)) / 1000;
            int32_t ymm = (pos[i].y_um + (pos[i].y_um >= 0 ? 500 : -500)) / 1000;
            if (xmm > 32767) xmm = 32767;
            if (xmm < -32767) xmm = -32767;   /* never the sentinel by accident */
            if (ymm > 32767) ymm = 32767;
            if (ymm < -32767) ymm = -32767;
            put_i16(buf, &o, (int16_t)xmm);
            put_i16(buf, &o, (int16_t)ymm);
        }
        put_u8(buf, &o, pos[i].compartment);
        put_u8(buf, &o, pos[i].confidence);
    }
    return (int)o;
}

int sb_ble_encode_event(sb_ble_event_type type, uint16_t object_id,
                        uint32_t timestamp, uint8_t *buf, size_t cap)
{
    if (cap < 7u) {
        return -1;
    }
    size_t o = 0;
    put_u8(buf, &o, (uint8_t)type);
    put_u16(buf, &o, object_id);
    put_u32(buf, &o, timestamp);
    return (int)o;
}

int sb_ble_encode_device_info(const sb_device *d, uint32_t now_ms,
                              uint8_t battery_pct, uint16_t fw,
                              uint8_t taxel_faults, uint8_t *buf, size_t cap)
{
    if (cap < 12u) {
        return -1;
    }
    size_t o = 0;
    put_u8(buf, &o, SB_BLE_VERSION);
    put_u8(buf, &o, battery_pct);
    put_u16(buf, &o, fw);
    put_u32(buf, &o, now_ms / 1000u);
    put_u8(buf, &o, taxel_faults);
    put_u8(buf, &o, (uint8_t)d->state);
    put_u16(buf, &o, (uint16_t)(sb_energy_uah_x1000(d) / 1000u));
    return (int)o;
}

/* ── enrollment ───────────────────────────────────────────────────────────── */
void sb_enroll_init(sb_enroll *e, uint16_t first_id)
{
    memset(e, 0, sizeof(*e));
    e->next_id = first_id;
}

static int fail(uint8_t *out, size_t cap, sb_enroll_failure why, uint16_t who)
{
    if (cap < 4u) {
        return -1;
    }
    size_t o = 0;
    put_u8(out, &o, SB_ENROLL_FAILED);
    put_u8(out, &o, (uint8_t)why);
    put_u16(out, &o, who);
    return (int)o;
}

void sb_enroll_sample(sb_enroll *e, bool usable)
{
    if (!e->active) {
        return;
    }
    if (usable) {
        if (e->samples < 255) {
            e->samples++;
        }
    } else if (e->dark_samples < 255) {
        e->dark_samples++;
    }
}

int sb_enroll_write(sb_enroll *e, sb_device *d, const uint8_t *req, size_t len,
                    uint32_t now_ms, uint8_t *out, size_t cap)
{
    if (len < 1u) {
        return -2;
    }
    uint8_t cmd = req[0];

    if (cmd == SB_ENROLL_CMD_BEGIN) {
        if (len < 4u) {
            return -2;
        }
        if (d->ledger.count >= SB_MAX_OBJECTS) {
            return fail(out, cap, SB_ENROLL_FAIL_FULL, 0);
        }
        e->active = true;
        e->samples = 0;
        e->dark_samples = 0;
        uint16_t asked = (uint16_t)(req[1] | (req[2] << 8));
        /* 0 means "you pick". A non-zero id is a re-enrollment of something the
         * app already knows about. */
        e->object_id = asked ? asked : e->next_id++;
        e->klass = req[3];
        size_t n = len > 4u ? len - 4u : 0u;
        if (n > SB_ENROLL_LABEL_MAX) {
            n = SB_ENROLL_LABEL_MAX;
        }
        memcpy(e->label, req + 4, n);
        e->label[n] = '\0';
        if (cap < 4u) {
            return -1;
        }
        size_t o = 0;
        put_u8(out, &o, SB_ENROLL_READY);
        put_u8(out, &o, 0);
        put_u16(out, &o, e->object_id);
        return (int)o;
    }

    if (!e->active) {
        /* COMMIT or ABORT with nothing running. Answering "committed" here is
         * how an app ends up believing in an object that was never shown. */
        return fail(out, cap, SB_ENROLL_FAIL_PROTOCOL, 0);
    }

    if (cmd == SB_ENROLL_CMD_ABORT) {
        e->active = false;
        if (cap < 4u) {
            return -1;
        }
        size_t o = 0;
        put_u8(out, &o, SB_ENROLL_CAPTURED);
        put_u8(out, &o, 0);
        put_u16(out, &o, e->object_id);
        return (int)o;
    }

    if (cmd == SB_ENROLL_CMD_FORGET) {
        e->active = false;
        uint16_t id = len >= 3u ? (uint16_t)(req[1] | (req[2] << 8))
                                : e->object_id;
        for (uint8_t i = 0; i < d->ledger.count; i++) {
            if (d->ledger.items[i].id == id) {
                d->ledger.items[i].present = false;
            }
        }
        if (cap < 4u) {
            return -1;
        }
        size_t o = 0;
        put_u8(out, &o, SB_ENROLL_COMMITTED);
        put_u8(out, &o, 0);
        put_u16(out, &o, id);
        return (int)o;
    }

    if (cmd != SB_ENROLL_CMD_COMMIT) {
        return fail(out, cap, SB_ENROLL_FAIL_PROTOCOL, 0);
    }

    /* ⚠️ Order matters. Darkness is diagnosed before scarcity, because "the
     * light was wrong" is actionable by the user and "show it again" is not. */
    if (e->dark_samples > e->samples) {
        e->active = false;
        return fail(out, cap, SB_ENROLL_FAIL_TOO_DARK, 0);
    }
    if (e->samples < SB_ENROLL_MIN_SAMPLES) {
        e->active = false;
        return fail(out, cap, SB_ENROLL_FAIL_TOO_FAST, 0);
    }
    /* ⛔ The check the whole document is about. Recognition is closed-set, so
     * two objects that are not separable will be confused forever. Saying so
     * now costs one dialog; saying nothing costs the user's trust the first
     * time the bag swaps their two black wallets. */
    uint16_t conflict = 0;
    if (e->too_similar && e->too_similar(e->ctx, e->object_id, &conflict)) {
        e->active = false;
        return fail(out, cap, SB_ENROLL_FAIL_TOO_SIMILAR, conflict);
    }

    e->active = false;
    if (d->ledger.count < SB_MAX_OBJECTS) {
        sb_object *it = &d->ledger.items[d->ledger.count++];
        it->id = e->object_id;
        it->klass = e->klass;
        it->since_ms = now_ms;
        it->present = false;   /* enrolled is not the same as inside */
    }
    if (cap < 4u) {
        return -1;
    }
    size_t o = 0;
    put_u8(out, &o, SB_ENROLL_COMMITTED);
    put_u8(out, &o, e->samples);
    put_u16(out, &o, e->object_id);
    return (int)o;
}
