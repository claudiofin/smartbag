/* The phone decoder against the firmware encoder's own bytes.
 *
 * ⭐ These are not fixtures someone typed. app/vectors.json is written by
 * firmware/gen_vectors.c, which links the same sb_ble.c the device runs. If a
 * field width, an order, or a sentinel changes on either side, this goes red.
 *
 * Run:  node app/test_protocol.mjs        (or ./tools/verify.sh)
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import assert from 'node:assert/strict';
import * as p from './protocol.js';

const here = dirname(fileURLToPath(import.meta.url));
const V = JSON.parse(readFileSync(join(here, 'vectors.json'), 'utf8'));
const bytes = (name) => {
  assert.ok(V[name], `vectors.json has no case "${name}" — regenerate with make -C firmware vectors`);
  return p.hexToBytes(V[name].hex);
};

let n = 0;
function test(name, fn) {
  fn();
  n++;
  console.log(`  ok  ${name}`);
}

test('inventory decodes the objects the firmware put in', () => {
  const inv = p.decodeInventory(bytes('inventory_two'));
  assert.equal(inv.version, p.PROTOCOL_VERSION);
  assert.equal(inv.items.length, 2);
  assert.deepEqual(inv.items.map((i) => i.id), [7, 9]);
  assert.ok(inv.items.every((i) => i.cameraConfirmed));
  assert.ok(inv.ledgerSeq > 0, 'ledger_seq must advance on mouth events');
});

test('a full inventory does not fit an unnegotiated notification', () => {
  const raw = bytes('inventory_full');
  const inv = p.decodeInventory(raw);
  assert.equal(inv.items.length, 24);
  assert.equal(raw.length, 198);
  assert.equal(p.fitsNotification(raw.length), false);
  assert.equal(p.fitsNotification(raw.length, 247), true);
  /* ⛔ And the failure mode if the app does not check: BLE hands over the
   * first 20 bytes without complaint, which decodes as a bag holding one
   * object out of twenty-four. Refusing is the only safe behaviour. */
  assert.throws(() => p.decodeInventory(raw.slice(0, 20)), /truncated|expected|present/i);
});

test('an event fits a default MTU, which is why it is the live path', () => {
  const raw = bytes('event_object_in');
  assert.equal(p.fitsNotification(raw.length), true);
  const ev = p.decodeEvent(raw);
  assert.equal(ev.name, 'object in');
  assert.equal(ev.objectId, 7);
});

test('an event with no object reports null, not zero', () => {
  const ev = p.decodeEvent(bytes('event_low_battery'));
  assert.equal(ev.name, 'low battery');
  assert.equal(ev.objectId, null);
});

test('a low-confidence entry arrives with no coordinates and a compartment', () => {
  const map = p.decodePositionMap(bytes('position_mixed'));
  assert.equal(map.entries.length, 2);
  const [placed, vague] = map.entries;

  assert.equal(placed.id, 7);
  assert.equal(placed.placed, true);
  assert.equal(placed.x, 190);
  assert.equal(placed.y, 39);

  assert.equal(vague.id, 9);
  assert.equal(vague.placed, false, 'the device withheld this position');
  assert.equal(vague.x, null);
  assert.equal(vague.y, null);
  /* ⭐ The part that makes the design work: the answer degrades, it does not
   * disappear. "Left compartment" is still a true statement. */
  assert.equal(vague.compartment, 0);
  assert.ok(vague.confidence < p.CONFIDENCE_FLOOR);

  assert.equal(map.everMeasured, true);
  assert.equal(map.measuredAgo, 60);
});

test('a map that was never measured places nothing at all', () => {
  const map = p.decodePositionMap(bytes('position_never_measured'));
  assert.equal(map.staleness, 255);
  assert.equal(map.everMeasured, false);
  assert.equal(map.measuredAgo, null, 'never is not the same as long ago');
  assert.ok(map.entries.every((e) => !e.placed),
    'full staleness must suppress every coordinate, whatever its confidence');
  assert.deepEqual(map.entries.map((e) => e.compartment), [2, 0]);
});

test('device info', () => {
  const info = p.decodeDeviceInfo(bytes('device_info'));
  assert.equal(info.battery, 74);
  assert.equal(info.firmware, '1.3');
  assert.equal(info.taxelFaults, 0);
});

test('enrollment: ready, then committed', () => {
  const ready = p.decodeEnrollment(bytes('enroll_ready'));
  assert.equal(ready.ok, true);
  assert.equal(ready.objectId, 500, 'the device allocates the id');
  const done = p.decodeEnrollment(bytes('enroll_committed'));
  assert.equal(done.status, p.ENROLL_STATUS.COMMITTED);
  assert.equal(done.samples, 8);
});

test('enrollment names the object it cannot separate the new one from', () => {
  const fail = p.decodeEnrollment(bytes('enroll_too_similar'));
  assert.equal(fail.ok, false);
  assert.match(fail.reason, /separable/);
  /* ⛔ Without this id the app can only say "too similar to something", which
   * is not an instruction anyone can act on. */
  assert.equal(fail.conflictsWith, 42);
});

test('enrollment blames the light before it blames the user', () => {
  const fail = p.decodeEnrollment(bytes('enroll_too_dark'));
  assert.equal(fail.ok, false);
  assert.match(fail.reason, /dark/);
  assert.equal(fail.conflictsWith, null);
});

test('the enrollment writes round-trip through the field layout', () => {
  const begin = p.encodeEnrollBegin(0, 3, 'black wallet');
  assert.equal(begin[0], 1);
  assert.equal(begin[1] | (begin[2] << 8), 0, '0 means the device picks');
  assert.equal(begin[3], 3);
  assert.equal(new TextDecoder().decode(begin.slice(4)), 'black wallet');
  /* ⚠️ The label is capped at 24 bytes on the device; the app must cap it too
   * or the write is silently trimmed somewhere the user cannot see. */
  const long = p.encodeEnrollBegin(0, 3, 'x'.repeat(60));
  assert.equal(long.length, 4 + 24);
});

test('a payload from a future protocol version is refused, not guessed at', () => {
  const raw = bytes('inventory_two');
  const tampered = Uint8Array.from(raw);
  tampered[0] = 2;
  assert.throws(() => p.decodeInventory(tampered), /version/);
});



/* ── the simulator is pinned to the firmware, not merely similar to it ────── */
const s = await import('./sim.js');
const hex = (b) => Array.from(b, (x) => x.toString(16).padStart(2, '0')).join('');

test('the simulator encodes inventories byte-for-byte like the firmware', () => {
  const inv = p.decodeInventory(bytes('inventory_two'));
  const re = s.encodeInventory({
    ledgerSeq: inv.ledgerSeq,
    items: inv.items.map((i) => ({
      id: i.id, klass: i.klass, since: i.since,
      cameraConfirmed: i.cameraConfirmed, massOnly: i.massOnly,
    })),
  });
  assert.equal(hex(re), V.inventory_two.hex);
});

test('and position maps, suppression rules included', () => {
  for (const name of ['position_mixed', 'position_never_measured']) {
    const map = p.decodePositionMap(bytes(name));
    const re = s.encodePositionMap({
      staleness: map.staleness,
      measuredAgo: map.measuredAgo,
      /* ⛔ Feeding the *original* coordinates back in, not the nulls the
       * decoder produced. If the simulator forgot either suppression rule it
       * would emit them and this would fail — which is the point. */
      entries: map.entries.map((e, i) => ({
        id: e.id,
        x: [190, 28][i], y: [39, 33][i],
        compartment: e.compartment, confidence: e.confidence,
      })),
    });
    assert.equal(hex(re), V[name].hex, name);
  }
});

test('and events and device info', () => {
  assert.equal(hex(s.encodeEvent(3, 7, 123456)), V.event_object_in.hex);
  assert.equal(hex(s.encodeEvent(6, 0, 999000)), V.event_low_battery.hex);
  const info = p.decodeDeviceInfo(bytes('device_info'));
  assert.equal(hex(s.encodeDeviceInfo({
    battery: info.battery, firmwareMajor: 1, firmwareMinor: 3,
    uptime: info.uptime, taxelFaults: 0, state: info.state,
    energyUah: info.energyUah,
  })), V.device_info.hex);
});

console.log(`${n} tests passed`);
