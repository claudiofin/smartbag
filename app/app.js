/* The app.
 *
 * ⭐ THE THREE THINGS docs/app-and-ble.md SAYS THIS UI HAS TO DO, and where
 * they are:
 *
 *   1. "Show age, everywhere." → `ageLine()` and `staleClass()`. There is no
 *      view of a position in this file that does not carry how old it is. The
 *      position panel renders the age *before* the map, so it cannot be
 *      scrolled past.
 *
 *   2. "Degrade to compartments." → `renderMap()`. An object the device
 *      declined to place is not dropped and not guessed at: its compartment
 *      band lights up and it is named underneath. This is the normal state
 *      after a walk, not an edge case, so it is drawn as a first-class answer.
 *
 *   3. "Handle several inserts without pretending they are one bag." →
 *      `inserts` is a list and exactly one is shown at a time. There is
 *      deliberately no combined view: nothing in the system knows what is in
 *      the bag you are not carrying.
 *
 * ⚠️ The service UUIDs below are placeholders. A vendor-assigned 128-bit UUID
 * is a real allocation and inventing one that collides with somebody's shipped
 * product would be worse than leaving this obviously fake.
 */
import * as proto from './protocol.js';
import { SimulatedInsert, INSERT_DIMENSIONS } from './sim.js';

const SERVICE_UUID = '5342a000-0000-1000-8000-00805f9b34fb';   /* placeholder */
const CHARS = {
  inventory: '5342a001-0000-1000-8000-00805f9b34fb',
  position: '5342a002-0000-1000-8000-00805f9b34fb',
  event: '5342a003-0000-1000-8000-00805f9b34fb',
  enrollment: '5342a004-0000-1000-8000-00805f9b34fb',
  deviceInfo: '5342a005-0000-1000-8000-00805f9b34fb',
};

const $ = (id) => document.getElementById(id);
const inserts = [];
let current = null;
let simCount = 0;

/* ── age, which is the whole product ─────────────────────────────────────── */
function ageLine(map) {
  if (!map || !map.everMeasured) {
    return ['This insert has never taken a measurement.', 'gone'];
  }
  const s = map.measuredAgo;
  const when = s < 60 ? `${s} s ago`
    : s < 3600 ? `${Math.round(s / 60)} min ago`
      : `${(s / 3600).toFixed(1)} h ago`;
  /* ⛔ Staleness is disturbance, not time. A bag that sat on a table for an
   * hour has a better map than one carried for four minutes, and saying "1 h
   * ago" without saying how much it was shaken would get that backwards. */
  if (map.staleness >= 255) {
    return [`Measured ${when}, and shaken past the point of being useful since.`, 'gone'];
  }
  if (map.staleness >= proto.CONFIDENCE_FLOOR) {
    return [`Measured ${when}, and moved a good deal since — treat this as approximate.`, 'soft'];
  }
  if (map.staleness > 8) {
    return [`Measured ${when}, barely disturbed since.`, 'fresh'];
  }
  return [`Measured ${when}.`, 'fresh'];
}

/* ── the map ─────────────────────────────────────────────────────────────── */
function renderMap(map, labelFor) {
  const { w, d } = INSERT_DIMENSIONS;
  const pad = 8;
  const W = w + pad * 2, H = d + pad * 2;
  const placed = map ? map.entries.filter((e) => e.placed) : [];
  const vague = map ? map.entries.filter((e) => !e.placed) : [];

  /* ⭐ An unplaced object is drawn where it actually is known to be: inside its
   * third of the insert, filling it, with its name in the middle. That is the
   * honest shape of the answer — a region, not a point — and it has to look
   * like a deliberate state rather than like a failed render, because after any
   * walk it is the state the app is normally in. */
  const inBand = new Map();
  for (const e of vague) {
    const k = e.compartment > 2 ? 3 : e.compartment;
    inBand.set(k, [...(inBand.get(k) || []), labelFor(e.id)]);
  }
  const bands = [0, 1, 2].map((i) => {
    const x = pad + (i * w) / 3;
    const who = inBand.get(i) || [];
    const fill = who.length
      ? `<rect x="${x + 1.5}" y="${pad + 1.5}" width="${w / 3 - 3}" height="${d - 3}"
           rx="3" fill="var(--accent)" opacity="0.13"/>`
      : '';
    const text = who.map((label, k) => `
      <text x="${x + w / 6}" y="${pad + d / 2 + (k - (who.length - 1) / 2) * 9 + 2.5}"
        text-anchor="middle" font-size="7" fill="var(--fg)">${escape(label)}</text>`).join('');
    return `<rect x="${x}" y="${pad}" width="${w / 3}" height="${d}" rx="3"
      fill="none" stroke="var(--line)"/>${fill}${text}`;
  }).join('');

  /* The halo grows with staleness: a dot you should trust less is literally
   * less of a dot. It never becomes a sharp dot in the wrong place. */
  const halo = 3 + (map ? map.staleness : 0) / 14;
  const dots = placed.map((e) => `
    <circle cx="${pad + e.x}" cy="${pad + e.y}" r="${halo}"
      fill="var(--accent)" opacity="0.18"/>
    <circle cx="${pad + e.x}" cy="${pad + e.y}" r="2.6" fill="var(--accent)"/>
    <text x="${pad + e.x}" y="${pad + e.y - halo - 3}" text-anchor="middle"
      font-size="6.5" fill="var(--fg)">${escape(labelFor(e.id))}</text>`).join('');

  $('map-wrap').innerHTML =
    `<svg viewBox="0 0 ${W} ${H}" role="img"
       aria-label="plan of the insert, ${placed.length} of ${placed.length + vague.length} objects placed">
       ${bands}${dots}</svg>`;

  const names = ['left', 'middle', 'right'];
  const parts = [];
  if (placed.length) {
    parts.push(`${placed.length} placed to within a centimetre or so.`);
  }
  if (vague.length) {
    /* ⚠️ Named in the plan above, summarised here. Dropping these objects
     * because their coordinates were withheld would be the app inventing an
     * emptier bag than the device reported. */
    const where = [...inBand.keys()].map((k) => (k > 2 ? 'somewhere inside' : `the ${names[k]} third`));
    parts.push(`${vague.length} not measured well enough to place — known only to ${where.join(' and ')}.`);
  }
  $('map-caption').textContent = parts.join(' ') || 'Nothing to place.';
}

const escape = (s) => String(s).replace(/[<>&]/g, (c) =>
  ({ '<': '&lt;', '>': '&gt;', '&': '&amp;' }[c]));

function duration(s) {
  if (s < 90) return `${s} s`;
  if (s < 5400) return `${Math.round(s / 60)} min`;
  return `${(s / 3600).toFixed(1)} h`;
}

/* ── rendering an insert ─────────────────────────────────────────────────── */
function render() {
  $('inserts').innerHTML = inserts.map((ins, i) =>
    `<button data-i="${i}" aria-current="${ins === current}">${escape(ins.name)}${ins.simulated ? ' · sim' : ''}</button>`).join('');
  $('main').hidden = !current;
  if (!current) return;

  const st = current.view;
  $('status').innerHTML = [
    ['battery', st.info ? `${st.info.battery}%` : '—'],
    ['firmware', st.info ? st.info.firmware : '—'],
    ['uptime', st.info ? duration(st.info.uptime) : '—'],
    ['taxel faults', st.info ? st.info.taxelFaults : '—'],
    ['ledger seq', st.inventory ? st.inventory.ledgerSeq : '—'],
    ['link', current.simulated ? 'simulated' : 'BLE'],
  ].map(([k, v]) => `<dt>${k}</dt><dd>${escape(v)}</dd>`).join('');

  const items = st.inventory ? st.inventory.items : [];
  $('count').textContent = items.length ? `${items.length} objects` : '';
  $('inventory').innerHTML = items.length
    ? items.map((it) => `<li><span>${escape(current.labelFor(it.id))}</span>
        <span class="meta">${escape(it.className)} · in for ${duration(it.since)}
        ${it.massOnly ? ' · by mass only' : ''}</span></li>`).join('')
    : '<li class="empty">Empty, as far as the insert can tell.</li>';

  const [line, cls] = ageLine(st.position);
  $('map-age').textContent = line;
  $('map-age').className = `age ${cls}`;
  renderMap(st.position, (id) => current.labelFor(id));

  document.querySelectorAll('.sim-only').forEach((el) => {
    el.style.display = current.simulated ? '' : 'none';
  });
}

function log(text, strong) {
  const li = document.createElement('li');
  li.innerHTML = strong ? `<b>${escape(text)}</b>` : escape(text);
  $('log').prepend(li);
  while ($('log').children.length > 40) $('log').lastChild.remove();
}

/* ── wiring one insert, simulated or real: the same decoders either way ──── */
function attach(ins) {
  ins.view = { inventory: null, position: null, info: null };
  ins.on('inventory', (b) => {
    ins.view.inventory = proto.decodeInventory(b);
    /* ⛔ Rule 3, enforced rather than hoped for. */
    if (!proto.fitsNotification(b.length, ins.mtu || 247)) {
      log(`inventory is ${b.length} bytes and will not survive this MTU — reading instead`);
    }
    render();
  });
  ins.on('position', (b) => { ins.view.position = proto.decodePositionMap(b); render(); });
  ins.on('event', (b) => {
    const e = proto.decodeEvent(b);
    log(`${e.name}${e.objectId ? `: ${ins.labelFor(e.objectId)}` : ''}`, e.type === 3 || e.type === 4);
  });
  ins.on('enrollment', (b) => {
    const r = proto.decodeEnrollment(b);
    const el = $('enrol-status');
    if (!r.ok) {
      el.className = 'enrol-status bad';
      /* ⛔ The refusal names the thing it collides with. "Too similar to
       * something" is not an instruction; "the insert cannot tell this apart
       * from your brown wallet" is. */
      el.textContent = r.conflictsWith
        ? `Refused: the insert cannot tell this apart from “${ins.labelFor(r.conflictsWith)}”. Enrolling it anyway would make the two interchangeable for good.`
        : `Refused: ${r.reason}`;
    } else if (r.status === proto.ENROLL_STATUS.READY) {
      el.className = 'enrol-status';
      el.textContent = `Hold it under the mouth of the bag. Assigned id ${r.objectId}.`;
    } else if (r.status === proto.ENROLL_STATUS.CAPTURED) {
      el.className = 'enrol-status';
      el.textContent = `${r.samples} usable frames…`;
    } else {
      el.className = 'enrol-status good';
      el.textContent = `Enrolled from ${r.samples} frames. It is registered, not in the bag.`;
    }
  });
  ins.view.inventory = proto.decodeInventory(ins.inventoryBytes());
  ins.view.position = proto.decodePositionMap(ins.positionBytes());
  ins.view.info = proto.decodeDeviceInfo(ins.deviceInfoBytes());
  inserts.push(ins);
  current = ins;
  render();
}

/* ── controls ────────────────────────────────────────────────────────────── */
$('inserts').addEventListener('click', (e) => {
  const i = e.target.dataset.i;
  if (i !== undefined) { current = inserts[+i]; render(); }
});

$('add-sim').addEventListener('click', () => {
  const names = ['Work tote', 'Weekend bag', 'Evening clutch'];
  attach(new SimulatedInsert(names[simCount++ % names.length]));
  log('simulated insert attached');
});

$('sim-insert').addEventListener('click', () => current?.openAndInsert());
$('sim-walk').addEventListener('click', () => { current?.walk(30); render(); });

let enrolling = null;
$('enrol').addEventListener('submit', (e) => {
  e.preventDefault();
  if (!current) return;
  /* ⚠️ Found by driving the form twice in a row: without this, two capture
   * timers run against one enrollment session, the sample count is whatever
   * the race decides, and the commit fires mid-capture. One enrollment at a
   * time, and the form says so. */
  if (enrolling) return;
  const label = $('enrol-label').value.trim();
  if (!label) return;
  const klass = +$('enrol-class').value;
  const button = $('enrol').querySelector('button');
  button.disabled = true;
  current.enrollBegin(klass, label);
  /* The device gates on usable frames, so the app cannot rush it. Six frames
   * at 120 ms is roughly the second the user is holding still anyway. */
  let k = 0;
  const ins = current;
  enrolling = setInterval(() => {
    ins.enrollSample();
    if (++k >= 6) {
      clearInterval(enrolling);
      enrolling = null;
      button.disabled = false;
      ins.enrollCommit();
    }
  }, 120);
  $('enrol-label').value = '';
});

$('connect').addEventListener('click', async () => {
  if (!navigator.bluetooth) {
    banner('This browser has no Web Bluetooth. Chrome or Edge on desktop and Android do; Safari and Firefox do not. The simulated insert works everywhere.');
    return;
  }
  try {
    const dev = await navigator.bluetooth.requestDevice({
      filters: [{ services: [SERVICE_UUID] }],
    });
    const gatt = await dev.gatt.connect();
    const svc = await gatt.getPrimaryService(SERVICE_UUID);
    const ins = { name: dev.name || 'Insert', simulated: false, listeners: {},
                  mtu: 247, labelFor: (id) => `object ${id}` };
    const cbs = { inventory: [], position: [], event: [], enrollment: [] };
    ins.on = (k, fn) => { cbs[k].push(fn); return ins; };
    for (const [key, uuid] of Object.entries(CHARS)) {
      if (key === 'deviceInfo') continue;
      const ch = await svc.getCharacteristic(uuid);
      await ch.startNotifications();
      ch.addEventListener('characteristicvaluechanged', (ev) => {
        const b = new Uint8Array(ev.target.value.buffer);
        for (const fn of cbs[key]) fn(b);
      });
    }
    const read = async (uuid) =>
      new Uint8Array((await (await svc.getCharacteristic(uuid)).readValue()).buffer);
    ins.inventoryBytes = () => read(CHARS.inventory);
    attach(ins);
    banner(null);
  } catch (err) {
    /* ⚠️ Including the ordinary case: there is no such device, because the
     * board in this repo is unrouted and has never been built. */
    banner(`No insert connected: ${err.message}`);
  }
});

function banner(text) {
  $('banner').hidden = !text;
  if (text) $('banner').textContent = text;
}

/* Start with something on screen: an empty app cannot be judged. */
attach(new SimulatedInsert('Work tote'));
simCount = 1;
log('simulated insert attached');
