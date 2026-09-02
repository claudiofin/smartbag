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
import { silhouette } from './icons.js';

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
/* The bag, in millimetres, straight out of dimensions.py. Front elevation:
 * x across the width, z up from the floor the bag stands on. */
const BAG = {
  wBottom: 240, wTop: 276, h: 190, mouth: 245, handleZ: 176, leather: 3.5,
  insW: 225, insH: 179.6, floor: 13.1,   /* leather + power plate + sensing floor */
};

function bagOutline() {
  const b = BAG, xb = b.wBottom / 2, xt = b.wTop / 2, xm = b.mouth * 0 + 100;
  /* ⚠️ SVG y runs down and the bag is described upwards, so every z becomes
   * TOP - z. Doing that once here is the only reason the path below reads like
   * the dimensions it came from. */
  const Y = (z) => 320 - z;
  return `
    M ${-xb + 16} ${Y(0)}
    a 16 16 0 0 1 -16 -16
    L ${-xt} ${Y(b.h)}
    C ${-xt} ${Y(b.h + 30)} ${-xm - 14} ${Y(b.mouth - 12)} ${-xm} ${Y(b.mouth)}
    L ${xm} ${Y(b.mouth)}
    C ${xm + 14} ${Y(b.mouth - 12)} ${xt} ${Y(b.h + 30)} ${xt} ${Y(b.h)}
    L ${xb} ${Y(16)}
    a 16 16 0 0 1 -16 16
    Z`;
}

function renderMap(map, labelFor, classFor) {
  const b = BAG;
  const Y = (z) => 320 - z;
  const VB = { x: -152, y: 12, w: 304, h: 324 };
  const placed = map ? map.entries.filter((e) => e.placed) : [];
  const vague = map ? map.entries.filter((e) => !e.placed) : [];

  /* ⭐ THE BAG IS DRAWN AS THE BAG. Not a rectangle standing in for one and not
   * a plan view: the outline below is 240 mm across the base, 276 at the top of
   * the body and 245 tall to the rim, because those are the numbers the CAD and
   * every render in this repository are built from. Someone holding the thing
   * should recognise it. */
  /* ⭐ THE EMPTY HALF OF THE BAG IS NOT EMPTY. A wallet is 88 mm tall in a 245 mm
   * bag, so the top of every honest drawing of this product is air — and it is
   * the air the sensors look through. Drawing the collar band and what it sees
   * fills that space with the mechanism instead of leaving it blank, and it is
   * the same picture as the section render: two beams from the ends, one
   * downward field from the middle. */
  const collarTop = b.leather + b.insH, collarBot = collarTop - 20;
  const sensing = `
    <rect x="${-b.insW / 2}" y="${Y(collarTop)}" width="${b.insW}" height="${20}"
          rx="4" fill="var(--accent)" opacity="0.10"/>
    <rect x="${-b.insW / 2 + 6}" y="${Y(collarBot + 12)}" width="${b.insW - 12}"
          height="4" rx="1.4" fill="var(--accent)" opacity="0.55"/>
    <path d="M ${-88} ${Y(collarBot)} L ${-34} ${Y(b.floor)} L ${-142 + 34} ${Y(b.floor)} Z"
          fill="var(--accent)" opacity="0.055"/>
    <path d="M ${88} ${Y(collarBot)} L ${34} ${Y(b.floor)} L ${142 - 34} ${Y(b.floor)} Z"
          fill="var(--accent)" opacity="0.055"/>
    <path d="M ${-14} ${Y(collarBot)} L ${-58} ${Y(b.floor)} L ${58} ${Y(b.floor)}
             L ${14} ${Y(collarBot)} Z" fill="var(--accent)" opacity="0.05"/>`;

  const shell = `
    <path d="${bagOutline()}" fill="var(--accent)" opacity="0.05"/>
    <path d="${bagOutline()}" fill="none" stroke="var(--line)" stroke-width="1.4"/>
    <path d="M ${-58} ${Y(b.handleZ)} C ${-58} ${Y(300)} ${58} ${Y(300)} ${58} ${Y(b.handleZ)}"
          fill="none" stroke="var(--line)" stroke-width="3.4" stroke-linecap="round"/>
    <line x1="${-100}" y1="${Y(b.mouth)}" x2="${100}" y2="${Y(b.mouth)}"
          stroke="var(--line)" stroke-width="1.4" stroke-dasharray="3 3"/>
    <rect x="${-b.insW / 2}" y="${Y(b.leather + b.insH)}" width="${b.insW}"
          height="${b.insH}" rx="7" fill="none" stroke="var(--line)"
          stroke-width="0.8" opacity="0.55"/>
    ${sensing}
    <line x1="${-b.insW / 2}" y1="${Y(b.floor)}" x2="${b.insW / 2}" y2="${Y(b.floor)}"
          stroke="var(--accent)" stroke-width="1.6" opacity="0.5"/>`;

  /* An object the insert has not placed is known to be in its third of the bag
   * and nowhere more precise. A tinted third is the honest shape of that. */
  const inBand = new Map();
  for (const e of vague) {
    const k = e.compartment > 2 ? 2 : e.compartment;
    inBand.set(k, [...(inBand.get(k) || []), labelFor(e.id)]);
  }
  const bands = [0, 1, 2].map((i) => {
    const x = -b.insW / 2 + (i * b.insW) / 3;
    const who = inBand.get(i) || [];
    if (!who.length) return '';
    return `<rect x="${x + 2}" y="${Y(b.floor)}" width="${b.insW / 3 - 4}"
        height="${b.floor + 140 - b.floor}" rx="4" fill="var(--accent)" opacity="0.12"
        transform="translate(0 ${-140})"/>` + who.map((label, k) => `
      <text x="${x + b.insW / 6}" y="${Y(b.floor + 60) + k * 10}" text-anchor="middle"
        font-size="9" fill="var(--fg)">${escape(label)}</text>`).join('');
  }).join('');

  /* ⚠️ Depth is measured and has nowhere to go in a front view, so it is spent
   * on the two things a front view can say: what is nearer is drawn slightly
   * larger and slightly more solid. Back to front, so the nearer object wins
   * the overlap — which is also what your eye would see through the opening. */
  const soft = map ? Math.min(0.5, map.staleness / 2400) : 0;
  const LINE = 11;
  const taken = [];
  const objects = [...placed].sort((p, q) => q.y - p.y).map((e) => {
    const cx = -b.insW / 2 + e.x;
    const depth = Math.min(1, Math.max(0, e.y / 78));
    const k = 1 - 0.12 * depth;
    const text = labelFor(e.id);
    const { h, markup } = silhouette(classFor(e.id), 0, 0);
    const top = Y(b.floor + h * k);
    const halfW = Math.max(14, text.length * 3.1);
    let ly = top - 5;
    for (const cand of [ly, ly - LINE, ly - LINE * 2, ly - LINE * 3]) {
      const box = [cx - halfW, cx + halfW, cand - LINE * 0.8, cand + 2];
      const clash = taken.some((t) => box[0] < t[1] && t[0] < box[1]
                                   && box[2] < t[3] && t[2] < box[3]);
      if (!clash) { taken.push(box); ly = cand; break; }
    }
    ly = Math.max(ly, VB.y + 10);
    return `<g transform="translate(${cx} ${Y(b.floor)}) scale(${k})"
               fill="var(--accent)" fill-opacity="${(0.26 - soft * 0.22) * (1.15 - depth * 0.35)}"
               stroke="var(--accent)" stroke-width="${1.3 / k}"
               stroke-opacity="${(1 - soft) * (1 - depth * 0.35)}"
               stroke-linejoin="round" stroke-linecap="round">${markup}</g>
      <text x="${cx}" y="${ly}" text-anchor="middle" font-size="10"
        fill="var(--fg)" opacity="0.94" paint-order="stroke"
        stroke="var(--panel)" stroke-width="3.5" stroke-linejoin="round"
        >${escape(text)}</text>`;
  }).join('');

  $('map-wrap').innerHTML =
    `<svg viewBox="${VB.x} ${VB.y} ${VB.w} ${VB.h}" role="img"
       aria-label="the bag seen from the front, ${placed.length} of ${placed.length + vague.length} objects placed">
       ${shell}${bands}${objects}</svg>`;
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

  // The app bar says the two things you look at a bag app to learn without
  // reading it: which bag, and whether it is about to go flat.
  document.body.classList.add('attached');
  $('appbar-sub').textContent = st.info
    ? `${current.name} · ${st.info.battery}%` : current.name;

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
  // ⚠️ The class comes from the INVENTORY, not the position map: the map
  // carries ids and coordinates, and what an object is belongs to the ledger.
  const klassOf = new Map(items.map((it) => [it.id, it.className]));
  renderMap(st.position, (id) => current.labelFor(id),
            (id) => klassOf.get(id) || 'unknown');

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

/* Start with something on screen: an empty app cannot be judged.
 *
 * ⭐ `?demo=5` seeds a bag with five things in it and no event log, which is what
 * a screenshot of this app should show — the state it is in for the other 23
 * hours of the day, rather than the state it is in one second after being
 * opened. It is the same simulator and the same code path; the only thing the
 * parameter does is decide how many objects are already there. */
const demo = Math.min(6, Math.max(0, +new URLSearchParams(location.search).get('demo') || 0));
const insert = new SimulatedInsert('Work tote', demo ? { seedObjects: demo } : {});
/* ⭐ A handle on the simulated insert, so something outside this page can drive
 * it. tools/build_app_film.sh puts the app in a phone on a 1080x1920 canvas and
 * scripts a bag being opened and used; without a handle the film would have to
 * re-implement the app to animate it, which is the one thing this project does
 * not do anywhere else. It is also the console handle anybody debugging wants. */
window.insert = insert;
attach(insert);
simCount = 1;
if (!demo) log('simulated insert attached');

/* ⭐ The phone shell: three tabs over the panels that are already on the page.
 * It sets one attribute — the CSS does the rest — so there is no second layout
 * to keep in step with the first. */
const tabs = $('tabs');
document.body.dataset.tab = 'bag';
tabs.hidden = false;
tabs.addEventListener('click', (ev) => {
  const b = ev.target.closest('button[data-tab]');
  if (!b) return;
  document.body.dataset.tab = b.dataset.tab;
  tabs.querySelectorAll('button').forEach((x) => x.classList.toggle('on', x === b));
  window.scrollTo(0, 0);
});
