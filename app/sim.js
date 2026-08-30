/* A simulated insert, so the app can be built and judged without hardware.
 *
 * ⛔ THE TRAP THIS AVOIDS. The obvious way to write a demo mode is to hand the
 * UI plain objects — `{id: 7, x: 190}` — and it is a trap, because then the UI
 * is developed against data the device can never send. It will look finished
 * and break on first contact. So this simulator encodes real payloads, byte for
 * byte, and the app decodes them with the same protocol.js it uses on a real
 * link. There is exactly one code path.
 *
 * ⭐ AND THE ENCODERS ARE PINNED. test_protocol.mjs asserts that what this file
 * produces is identical to what firmware/sb_ble.c produces for the same state.
 * A simulator free to invent its own wire format would be worth nothing.
 */
import {
  PROTOCOL_VERSION, POS_UNKNOWN, CONFIDENCE_FLOOR,
} from './protocol.js';

class Writer {
  constructor() { this.b = []; }
  u8(v) { this.b.push(v & 0xFF); return this; }
  u16(v) { this.b.push(v & 0xFF, (v >> 8) & 0xFF); return this; }
  i16(v) { return this.u16(v < 0 ? v + 0x10000 : v); }
  u32(v) {
    this.b.push(v & 0xFF, (v >>> 8) & 0xFF, (v >>> 16) & 0xFF, (v >>> 24) & 0xFF);
    return this;
  }
  get bytes() { return Uint8Array.from(this.b); }
}

export function encodeInventory({ ledgerSeq, items }) {
  const w = new Writer().u8(PROTOCOL_VERSION).u8(items.length).u32(ledgerSeq);
  for (const it of items) {
    w.u16(it.id).u8(it.klass)
      .u8((it.cameraConfirmed ? 1 : 0) | (it.massOnly ? 2 : 0))
      .u32(it.since);
  }
  return w.bytes;
}

export function encodePositionMap({ staleness, measuredAgo, entries }) {
  const ago = measuredAgo === null ? 0xFFFFFFFF : measuredAgo;
  const w = new Writer().u8(PROTOCOL_VERSION).u8(entries.length)
    .u8(staleness).u32(ago);
  /* ⚠️ Both suppression rules live here too, because the simulator has to be
   * able to lie in exactly the ways the firmware can — and in no others. A
   * simulator that could produce a payload the device cannot is a simulator
   * that lets impossible UI states ship. */
  const suppressAll = staleness === 255;
  for (const e of entries) {
    w.u16(e.id);
    if (suppressAll || e.confidence < CONFIDENCE_FLOOR) {
      w.i16(POS_UNKNOWN).i16(POS_UNKNOWN);
    } else {
      w.i16(e.x).i16(e.y);
    }
    w.u8(e.compartment).u8(e.confidence);
  }
  return w.bytes;
}

export function encodeEvent(type, objectId, timestamp) {
  return new Writer().u8(type).u16(objectId || 0).u32(timestamp).bytes;
}

export function encodeDeviceInfo(
  { battery, firmwareMajor, firmwareMinor, uptime, taxelFaults, state, energyUah }
) {
  return new Writer().u8(PROTOCOL_VERSION).u8(battery)
    .u16((firmwareMajor << 8) | firmwareMinor)
    .u32(uptime).u8(taxelFaults).u8(state).u16(energyUah).bytes;
}

/* ── the simulated peripheral ─────────────────────────────────────────────── */

const CATALOGUE = [
  { klass: 1, label: 'brown wallet' },
  { klass: 3, label: 'house keys' },
  { klass: 5, label: 'lipstick' },
  { klass: 4, label: 'makeup pouch' },
  { klass: 6, label: 'reading glasses' },
  { klass: 7, label: 'earbuds case' },
];

/* Insert coordinates, from dimensions.py: 225 x 78 mm. */
const INSERT_W = 225, INSERT_D = 78;

let nextId = 700;

export class SimulatedInsert {
  constructor(name, { seedObjects = 3 } = {}) {
    this.name = name;
    this.id = `sim-${name.toLowerCase().replace(/\W+/g, '-')}`;
    this.simulated = true;
    this.listeners = { inventory: [], position: [], event: [], enrollment: [] };
    this.t0 = Date.now();
    this.ledgerSeq = 0;
    this.items = [];
    this.disturbance = 0;
    this.staleThreshold = 1200;
    this.measuredAt = null;
    this.battery = 60 + Math.floor(Math.random() * 35);
    this.enroll = null;
    this.enrollSamples = 0;
    for (let i = 0; i < seedObjects; i++) {
      this.#add(CATALOGUE[i % CATALOGUE.length]);
    }
    this.#remap();
  }

  get uptime() { return Math.floor((Date.now() - this.t0) / 1000); }

  on(what, fn) { this.listeners[what].push(fn); return this; }
  #emit(what, bytes) { for (const fn of this.listeners[what]) fn(bytes); }

  #add({ klass, label }) {
    const id = nextId++;
    this.items.push({
      id, klass, label, since: this.uptime, cameraConfirmed: true,
      massOnly: false,
      x: 20 + Math.floor(Math.random() * (INSERT_W - 40)),
      y: 12 + Math.floor(Math.random() * (INSERT_D - 24)),
    });
    this.ledgerSeq++;
    return id;
  }

  #compartmentOf(x) {
    return x < INSERT_W / 3 ? 0 : x < (2 * INSERT_W) / 3 ? 1 : 2;
  }

  #staleness() {
    if (this.measuredAt === null) return 255;
    return Math.min(255, Math.floor((this.disturbance * 255) / this.staleThreshold));
  }

  inventoryBytes() {
    return encodeInventory({
      ledgerSeq: this.ledgerSeq,
      items: this.items.map((i) => ({ ...i, since: this.uptime - i.since })),
    });
  }

  positionBytes() {
    const staleness = this.#staleness();
    return encodePositionMap({
      staleness,
      measuredAgo: this.measuredAt === null
        ? null : Math.floor((Date.now() - this.measuredAt) / 1000),
      entries: this.items.map((i) => ({
        id: i.id, x: i.x, y: i.y,
        compartment: this.#compartmentOf(i.x),
        /* ⭐ Confidence decays with disturbance, which is what makes the app's
         * degrade-to-compartment path the normal case rather than an edge one.
         * A bag that has been carried anywhere is a bag whose map is soft. */
        confidence: Math.max(0, 255 - Math.floor((this.disturbance * 255) / this.staleThreshold)),
      })),
    });
  }

  deviceInfoBytes() {
    return encodeDeviceInfo({
      battery: this.battery, firmwareMajor: 1, firmwareMinor: 3,
      uptime: this.uptime, taxelFaults: 0, state: 0,
      energyUah: Math.floor(this.uptime / 60),
    });
  }

  #remap() {
    this.measuredAt = Date.now();
    this.disturbance = 0;
    this.#emit('position', this.positionBytes());
    this.#emit('event', encodeEvent(5, 0, this.uptime));
  }

  /* ── the scripted things a bag does ──────────────────────────────────── */
  openAndInsert() {
    this.#emit('event', encodeEvent(1, 0, this.uptime));
    const pick = CATALOGUE[Math.floor(Math.random() * CATALOGUE.length)];
    const id = this.#add(pick);
    this.#emit('event', encodeEvent(3, id, this.uptime));
    this.#emit('event', encodeEvent(2, 0, this.uptime));
    this.#emit('inventory', this.inventoryBytes());
    setTimeout(() => this.#remap(), 900);
    return id;
  }

  remove(id) {
    const i = this.items.findIndex((o) => o.id === id);
    if (i < 0) return;
    this.items.splice(i, 1);
    this.ledgerSeq++;
    this.#emit('event', encodeEvent(4, id, this.uptime));
    this.#emit('inventory', this.inventoryBytes());
    setTimeout(() => this.#remap(), 900);
  }

  /* Walking. ⚠️ This is the state the product is actually in most of the time,
   * so it is the state the UI has to look right in. */
  walk(seconds = 20) {
    /* ⚠️ 20 units of integrated motion per second of walking, against the
     * firmware's stale_threshold of 1200. That puts half a minute of walking
     * in the middle band — placed, but with visible doubt — and a minute past
     * the confidence floor, where only compartments survive. Those two states
     * are the ones the UI has to get right, so the simulator has to be able to
     * reach both; a rate that jumped straight to "no idea" would have hidden
     * the interesting half of the design. */
    this.disturbance += seconds * 20;
    for (const it of this.items) {
      it.x = Math.round(Math.max(10, Math.min(INSERT_W - 10, it.x + (Math.random() - 0.5) * 40)));
      it.y = Math.round(Math.max(8, Math.min(INSERT_D - 8, it.y + (Math.random() - 0.5) * 16)));
    }
    this.#emit('position', this.positionBytes());
  }

  /* ── enrollment, with the refusals ───────────────────────────────────── */
  enrollBegin(klass, label) {
    this.enroll = { klass, label, id: nextId++ };
    this.enrollSamples = 0;
    this.#emit('enrollment', Uint8Array.from([1, 0, this.enroll.id & 0xFF, this.enroll.id >> 8]));
    return this.enroll.id;
  }
  enrollSample() {
    if (!this.enroll) return;
    this.enrollSamples++;
    this.#emit('enrollment', Uint8Array.from([2, this.enrollSamples, this.enroll.id & 0xFF, this.enroll.id >> 8]));
  }
  enrollCommit() {
    if (!this.enroll) {
      this.#emit('enrollment', Uint8Array.from([4, 4, 0, 0]));
      return;
    }
    const e = this.enroll;
    this.enroll = null;
    if (this.enrollSamples < 5) {
      this.#emit('enrollment', Uint8Array.from([4, 2, 0, 0]));
      return;
    }
    /* The refusal that matters, reproduced: a label that collides with one
     * already enrolled stands in for an embedding that is not separable. */
    const clash = this.items.find(
      (o) => o.klass === e.klass && o.label.split(' ').pop() === e.label.split(' ').pop());
    if (clash) {
      this.#emit('enrollment', Uint8Array.from([4, 3, clash.id & 0xFF, clash.id >> 8]));
      return;
    }
    this.items.push({
      id: e.id, klass: e.klass, label: e.label, since: this.uptime,
      cameraConfirmed: true, massOnly: false,
      x: 20 + Math.floor(Math.random() * (INSERT_W - 40)),
      y: 12 + Math.floor(Math.random() * (INSERT_D - 24)),
    });
    this.ledgerSeq++;
    this.#emit('enrollment', Uint8Array.from([3, this.enrollSamples, e.id & 0xFF, e.id >> 8]));
    this.#emit('inventory', this.inventoryBytes());
  }

  labelFor(id) {
    return this.items.find((o) => o.id === id)?.label ?? `object ${id}`;
  }
}

export const INSERT_DIMENSIONS = { w: INSERT_W, d: INSERT_D };
