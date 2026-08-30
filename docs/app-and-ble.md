# The companion app, and the BLE contract it talks to

**This document is now implemented on both sides.** The device side is
[`firmware/sb_ble.c`](../firmware/sb_ble.c); the phone side is
[`app/`](../app/). What follows is still the specification — it is the reason
each field exists, which the code cannot tell you — and it is now also checked:
`firmware/gen_vectors.c` writes golden payloads and `app/test_protocol.mjs`
decodes those exact bytes, so the two halves cannot drift apart quietly.

It was written first because the repo was describing a device that had no way to
tell anyone what it knew. An insert that recognises its contents and cannot
report them is not half a product, it is no product — and the interface is the
part worth pinning down early, because it is where the two halves have to agree.

⚠️ Still not implemented, and listed at the end: pairing, bonding, encryption,
OTA, and anything to do with an account.

---

## What owns the identity: the insert, not the bag

This decides the whole data model, so it comes first.

The insert is **removable by design** — that is the entire reason it exists, so
the bag never has to be modified. Which means:

- **one insert = one BLE peripheral = one inventory.** The insert is the thing
  with a MAC address, a ledger and a battery. It is the unit.
- **the bag is not a thing the system knows about.** Move the insert from the
  black tote to the tan one and nothing changes electrically. The insert has no
  sensor that could tell it which bag it is sitting in, and it should not
  pretend otherwise.
- **several bags means several inserts.** If you own three, the app pairs three
  peripherals and shows three inventories. "Which bag am I carrying?" becomes
  "which insert is in range?", which is a question BLE can actually answer.

The app may of course let you *name* an insert ("work bag", "weekend") — but
that is a label the user assigns, not something the hardware discovers. Anything
else would be an invented fact, which is the failure mode this whole design
keeps trying to avoid.

### The one honest exception

If someone genuinely needs the insert to know which bag it is in, the answer is
the same escape hatch as for two identical objects: a passive tag **in the bag**.
The current board has no NFC reader, so this is not free — it is a hardware
change, and it is listed here as a possibility, not a plan.

---

## Two data, two update policies

The app must never render these the same way, because they do not have the same
truth value. (See the data model section of the main README for the reasoning.)

| datum | changes | staleness |
|---|---|---|
| **inventory** — what is inside | only on an event at the mouth | never goes stale on its own |
| **position map** — where each thing is | on every disturbance | perishable; carries a timestamp and a `stale` flag |

An inventory entry is a fact. A position is a measurement with an age. The UI
has to show the age, and has to be able to say *"I do not know precisely"* —
"lipstick, right compartment, measured 40 minutes ago" is a good answer;
"lipstick, under the pouch" when the map is three walks old is a lie with a
confident font.

---

## GATT service

One primary service. All multi-byte values little-endian, all lengths in bytes.

**Service** `SmartBag Inventory` — 128-bit UUID, vendor-assigned.

### `Inventory` — read, notify

The current contents. Notified on every change; a full read returns the whole
list.

```
uint8   version            protocol version, starts at 1
uint8   count              number of entries that follow
uint32  ledger_seq         increments on every mouth event, ever
{ repeated `count` times:
  uint16  object_id        stable id assigned at enrollment
  uint8   class            enum: wallet, phone, keys, pouch, cosmetic, ...
  uint8   flags            bit0 confirmed by camera · bit1 present by mass only
  uint32  since            seconds since it entered (device uptime clock)
}
```

`ledger_seq` lets the app detect that it missed events while out of range and
ask for a resync, without the device having to buffer notifications.

### `PositionMap` — read, notify

Where things are, and how much to trust it.

```
uint8   version
uint8   count
uint8   staleness          0 = just measured, 255 = badly shaken since
uint32  measured_ago       seconds since the last full measurement
{ repeated `count` times:
  uint16  object_id
  int16   x, y             millimetres, insert coordinates
  uint8   compartment      0 left · 1 middle · 2 right · 255 unknown
  uint8   confidence       0..255 from the assignment cost
}
```

⚠️ **`compartment` is not derived from `x`.** When confidence is low the device
reports the compartment it is still sure of and sets `x, y` to a sentinel. The
app must render the compartment, not invent a dot on a map. Two fields exist
precisely so the device can answer at the resolution it actually has.

### `Event` — notify only

The wake-up chain, as it happens. Small and frequent; this is what makes the app
feel live rather than polled.

```
uint8   type               1 closure opened · 2 closure closed · 3 object in
                           · 4 object out · 5 remap done · 6 low battery
uint16  object_id          0 if not applicable
uint32  timestamp
```

### `Enrollment` — write, indicate

The registration flow (see the README: recognition is closed-set, so every
object has to be shown once).

```
write:   uint8 command   1 begin · 2 commit · 3 abort · 4 forget
         uint16 object_id     (0 on begin: the device allocates one)
         uint8  class
         utf8   label[..]     user-visible name
indicate: uint8 status   1 ready, show the object
                         2 captured, N samples so far
                         3 committed
                         4 failed: too dark / too fast / too similar to <id>
```

⚠️ Status 4 with `too similar to <id>` is the one that matters. If a new object
is not separable from one already enrolled, the device must **say so at
enrollment time**, not silently accept it and then confuse the two forever.

### `DeviceInfo` — read

```
uint8   version
uint8   battery_pct
uint16  firmware            major << 8 | minor
uint32  uptime              seconds
uint8   taxel_faults        taxels failing self-test, 0..96
uint8   state               the wake-up chain state, for diagnostics
uint16  energy_uah          charge spent since boot
```

### ⛔ The size limit that decides the transport

A full inventory is `6 + 24 × 8` = **198 bytes**. The default ATT MTU is 23,
which leaves **20**, and BLE does **not** fragment notifications — it delivers
the first 20 bytes and reports success. Those 20 bytes are a structurally valid
inventory containing one object.

So: either the phone negotiates an MTU of at least 201, or the app must **read**
`Inventory` rather than rely on the notification. `sb_ble_fits()` on the device
and `fitsNotification()` in the app both exist to make this a loud failure
instead of a quiet one.

⭐ `Event` is 7 bytes on purpose. The live path has to work on a link that
negotiated nothing.

---

## What the app has to do that is not obvious

- **Show age, everywhere.** Any position older than a few minutes gets rendered
  as an approximation. This is the single most important UI decision in the
  product.
- **Degrade to compartments.** The map view must have a legible "somewhere in
  the right compartment" state. If the design only works when coordinates are
  exact, it will look broken in normal use.
- **Handle several inserts without pretending they are one bag.** A list of
  inserts, each with its own inventory. No merged "everything I own" view that
  implies knowledge nobody has.
- **Own the enrollment flow.** It is the setup cost of the whole product and the
  place where it will be abandoned. Ten objects at ten seconds each is the
  budget worth designing against.
- **Survive being out of range.** `ledger_seq` in, resync out. The bag keeps
  working when the phone is not there; that is the point of putting the
  intelligence in the insert.

## What is deliberately not specified here

Pairing and bonding, the encryption of the characteristics, OTA updates, and
anything to do with a cloud account. All of them are real work, none of them are
interesting design decisions at this stage, and guessing at them would add
volume without adding information.
