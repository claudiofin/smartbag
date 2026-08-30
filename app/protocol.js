/* The phone half of docs/app-and-ble.md.
 *
 * ⭐ THIS FILE IS TESTED AGAINST THE FIRMWARE, not against itself. The C encoder
 * in firmware/sb_ble.c writes vectors.json; test_protocol.mjs decodes those
 * exact bytes with these functions and checks the meaning survives. That is the
 * only mechanism in the repo that stops the two halves of the product drifting
 * apart, and it is cheap: `make -C firmware vectors` and run the test.
 *
 * ⚠️ NO UI DECISIONS HERE. Deciding that an unplaced object should be drawn as
 * a compartment band rather than a dot is app.js's job. This file's only
 * opinion is that it must never hand the UI a coordinate the device refused to
 * give — which is why `placed` is a field and `x` may be null.
 */

export const PROTOCOL_VERSION = 1;
export const POS_UNKNOWN = -32768;        /* INT16_MIN, the sentinel */
export const CONFIDENCE_FLOOR = 96;
export const ATT_DEFAULT_MTU = 23;
export const ATT_HEADER = 3;

export const CLASSES = [
  'unknown', 'wallet', 'phone', 'keys', 'pouch', 'cosmetic', 'glasses',
  'earbuds', 'card', 'bottle',
];

export const EVENT_NAMES = {
  1: 'closure opened', 2: 'closure closed', 3: 'object in',
  4: 'object out', 5: 'remap done', 6: 'low battery',
};

export const ENROLL_STATUS = { READY: 1, CAPTURED: 2, COMMITTED: 3, FAILED: 4 };
export const ENROLL_FAILURE = {
  1: 'too dark — the illuminators could not see it',
  2: 'not enough usable frames — hold it still a moment longer',
  3: 'not separable from an object already enrolled',
  4: 'protocol error',
  5: 'no room left for another object',
};

class Reader {
  constructor(bytes) { this.b = bytes; this.o = 0; }
  u8() { return this.b[this.o++]; }
  u16() { const v = this.b[this.o] | (this.b[this.o + 1] << 8); this.o += 2; return v; }
  i16() { const v = this.u16(); return v >= 0x8000 ? v - 0x10000 : v; }
  u32() {
    const b = this.b, o = this.o; this.o += 4;
    return (b[o] | (b[o + 1] << 8) | (b[o + 2] << 16)) + b[o + 3] * 0x1000000;
  }
  get left() { return this.b.length - this.o; }
}

function check(r, version, want, what) {
  if (version !== PROTOCOL_VERSION) {
    throw new Error(`${what}: protocol version ${version}, expected ${PROTOCOL_VERSION}`);
  }
  /* ⚠️ A payload that is short is a truncated payload, and a truncated
   * inventory is indistinguishable from an emptied bag. Refuse it. */
  if (r.left < want) {
    throw new Error(`${what}: ${want} bytes of entries expected, ${r.left} present`);
  }
}

export function decodeInventory(bytes) {
  const r = new Reader(bytes);
  const version = r.u8(), count = r.u8(), ledgerSeq = r.u32();
  check(r, version, count * 8, 'inventory');
  const items = [];
  for (let i = 0; i < count; i++) {
    const id = r.u16(), klass = r.u8(), flags = r.u8(), since = r.u32();
    items.push({
      id, klass, since,
      className: CLASSES[klass] || `class ${klass}`,
      cameraConfirmed: (flags & 0x01) !== 0,
      massOnly: (flags & 0x02) !== 0,
    });
  }
  return { version, ledgerSeq, items };
}

export function decodePositionMap(bytes) {
  const r = new Reader(bytes);
  const version = r.u8(), count = r.u8(), staleness = r.u8();
  const measuredAgo = r.u32();
  check(r, version, count * 8, 'position map');
  const entries = [];
  for (let i = 0; i < count; i++) {
    const id = r.u16(), x = r.i16(), y = r.i16();
    const compartment = r.u8(), confidence = r.u8();
    /* ⭐ The sentinel becomes a boolean here, once, so no view can accidentally
     * plot -32768 as a position. */
    const placed = x !== POS_UNKNOWN && y !== POS_UNKNOWN;
    entries.push({
      id, compartment, confidence, placed,
      x: placed ? x : null,
      y: placed ? y : null,
    });
  }
  return {
    version, staleness, entries,
    /* 0xFFFFFFFF means it never happened, which is not the same as long ago. */
    measuredAgo: measuredAgo === 0xFFFFFFFF ? null : measuredAgo,
    everMeasured: measuredAgo !== 0xFFFFFFFF,
  };
}

export function decodeEvent(bytes) {
  const r = new Reader(bytes);
  const type = r.u8(), objectId = r.u16(), timestamp = r.u32();
  return {
    type, objectId: objectId || null, timestamp,
    name: EVENT_NAMES[type] || `event ${type}`,
  };
}

export function decodeDeviceInfo(bytes) {
  const r = new Reader(bytes);
  const version = r.u8(), battery = r.u8(), fw = r.u16();
  const uptime = r.u32(), taxelFaults = r.u8(), state = r.u8();
  const energyUah = r.u16();
  return {
    version, battery, uptime, taxelFaults, state, energyUah,
    firmware: `${fw >> 8}.${fw & 0xFF}`,
  };
}

export function decodeEnrollment(bytes) {
  const r = new Reader(bytes);
  const status = r.u8(), arg = r.u8(), id = r.u16();
  if (status === ENROLL_STATUS.FAILED) {
    return {
      status, ok: false,
      reason: ENROLL_FAILURE[arg] || `failure ${arg}`,
      /* ⛔ On "not separable", `id` is the object it collides with, not the one
       * being enrolled. The app has to be able to name it — that is the whole
       * point of sending it. */
      conflictsWith: arg === 3 ? id : null,
    };
  }
  return { status, ok: true, objectId: id, samples: arg };
}

export function encodeEnrollBegin(objectId, klass, label) {
  const text = new TextEncoder().encode(label).slice(0, 24);
  const out = new Uint8Array(4 + text.length);
  out[0] = 1;
  out[1] = objectId & 0xFF;
  out[2] = objectId >> 8;
  out[3] = klass;
  out.set(text, 4);
  return out;
}
export const encodeEnrollCommit = () => new Uint8Array([2]);
export const encodeEnrollAbort = () => new Uint8Array([3]);
export function encodeEnrollForget(objectId) {
  return new Uint8Array([4, objectId & 0xFF, objectId >> 8]);
}

/* ⛔ Rule 3 from sb_ble.h, on this side of the link. A phone that never
 * negotiated its MTU cannot receive a full inventory as a notification, and
 * BLE will not fragment it — it will silently deliver the first 20 bytes.
 * The app has to check rather than hope. */
export function fitsNotification(byteLength, mtu = ATT_DEFAULT_MTU) {
  return byteLength + ATT_HEADER <= mtu;
}

export function hexToBytes(hex) {
  const out = new Uint8Array(hex.length / 2);
  for (let i = 0; i < out.length; i++) {
    out[i] = parseInt(hex.substr(i * 2, 2), 16);
  }
  return out;
}
