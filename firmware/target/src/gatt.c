/* The GATT service: five characteristics carrying bytes sb_ble.c already makes.
 *
 * ⛔ THIS WAS THE LAST THING IN THE FIRMWARE THE HOST TESTS COULD NOT STAND IN
 * FOR. sb_ble.c encodes every payload and app/protocol.js decodes the same bytes
 * under 15 tests — both ends of the wire were written and checked against each
 * other, with nothing in between. A service definition is what turns two
 * agreeing codecs into a link.
 *
 * ⭐ SO THERE IS NO ENCODING IN THIS FILE. Every read handler calls into
 * ../sb_ble.c and hands back what it produced; the UUIDs are the ones
 * app/app.js already asks for. If a payload is ever wrong, it is wrong in a file
 * that has tests, not in this one.
 *
 * ⚠️ THE UUIDs ARE PLACEHOLDERS AND app/app.js SAYS SO TOO. 5342a0xx in the
 * Bluetooth base range is fine on a bench and is not an allocation; shipping
 * wants a real 128-bit base, and both sides have to change together.
 */
#include <zephyr/kernel.h>
#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/bluetooth/gatt.h>
#include <zephyr/bluetooth/uuid.h>
#include <zephyr/logging/log.h>

#include "smartbag.h"
#include "sb_ble.h"

/* ⚠️ Declared here rather than included: these are the two numbers the info
 * payload needs from outside the ledger, and both come from files this one has
 * no other business with. */
uint8_t sb_pmic_battery_pct(void);
uint8_t sb_fsr_faults(void);
#define SB_FIRMWARE_VERSION 0x0103      /* 1.3, as app/app.js expects */

LOG_MODULE_REGISTER(sb_gatt, CONFIG_LOG_DEFAULT_LEVEL);

#define SB_UUID(n) BT_UUID_DECLARE_16(0xa0##n)

/* 5342a000-…: the service, then inventory, position, event, enrollment, info. */
static struct bt_uuid_128 uuid_svc = BT_UUID_INIT_128(
	BT_UUID_128_ENCODE(0x5342a000, 0x0000, 0x1000, 0x8000, 0x00805f9b34fb));
static struct bt_uuid_128 uuid_inventory = BT_UUID_INIT_128(
	BT_UUID_128_ENCODE(0x5342a001, 0x0000, 0x1000, 0x8000, 0x00805f9b34fb));
static struct bt_uuid_128 uuid_position = BT_UUID_INIT_128(
	BT_UUID_128_ENCODE(0x5342a002, 0x0000, 0x1000, 0x8000, 0x00805f9b34fb));
static struct bt_uuid_128 uuid_event = BT_UUID_INIT_128(
	BT_UUID_128_ENCODE(0x5342a003, 0x0000, 0x1000, 0x8000, 0x00805f9b34fb));
static struct bt_uuid_128 uuid_enroll = BT_UUID_INIT_128(
	BT_UUID_128_ENCODE(0x5342a004, 0x0000, 0x1000, 0x8000, 0x00805f9b34fb));
static struct bt_uuid_128 uuid_info = BT_UUID_INIT_128(
	BT_UUID_128_ENCODE(0x5342a005, 0x0000, 0x1000, 0x8000, 0x00805f9b34fb));

/* ⚠️ One buffer, and every handler fills it fresh. The characteristics are read
 * one at a time over a single connection; a buffer each would cost 5 x 244 bytes
 * of RAM to describe a bag that has at most a dozen things in it. */
static uint8_t payload[247];

static const sb_device *device;
static const sb_config *config;
static sb_enroll *enroll;

static ssize_t read_encoded(struct bt_conn *conn,
			    const struct bt_gatt_attr *attr, void *buf,
			    uint16_t len, uint16_t offset, int n)
{
	ARG_UNUSED(conn);
	ARG_UNUSED(attr);
	if (n < 0) {
		return BT_GATT_ERR(BT_ATT_ERR_UNLIKELY);
	}
	return bt_gatt_attr_read(conn, attr, buf, len, offset, payload, (uint16_t)n);
}

static ssize_t read_inventory(struct bt_conn *conn,
			      const struct bt_gatt_attr *attr, void *buf,
			      uint16_t len, uint16_t offset)
{
	return read_encoded(conn, attr, buf, len, offset,
			    sb_ble_encode_inventory(device, payload,
						    sizeof(payload)));
}

/* ⛔ THE DEVICE DOES NOT STORE POSITIONS AND THAT IS NOT AN OMISSION. sb_map
 * holds when the bag was last measured and how much it has been shaken since —
 * the trust, not the answer. The points come from a radar sweep, and until one
 * has run there is nothing to report but the ledger.
 *
 * ⭐ WHICH IS EXACTLY WHAT GETS REPORTED, at confidence zero. sb_ble.c already
 * encodes a below-threshold object as a compartment and no point, and
 * app/app.js already draws that as a tinted third of the bag rather than a dot.
 * Both ends were written for this state; it is the state the bag is in for most
 * of its life, and it is the honest one before the sensing loop exists.
 */
static ssize_t read_position(struct bt_conn *conn,
			     const struct bt_gatt_attr *attr, void *buf,
			     uint16_t len, uint16_t offset)
{
	sb_ble_position pos[SB_MAX_OBJECTS];
	int n = 0;

	for (int i = 0; i < device->ledger.count && n < SB_MAX_OBJECTS; i++) {
		if (!device->ledger.items[i].present) {
			continue;
		}
		pos[n].object_id = device->ledger.items[i].id;
		pos[n].x_um = 0;
		pos[n].y_um = 0;
		pos[n].compartment = 1;          /* the middle third, unless measured */
		pos[n].confidence = 0;           /* below SB_CONFIDENCE_FLOOR */
		n++;
	}
	return read_encoded(conn, attr, buf, len, offset,
			    sb_ble_encode_position(device, config, pos, n,
						   (uint32_t)k_uptime_get_32(),
						   payload, sizeof(payload)));
}

static ssize_t read_info(struct bt_conn *conn, const struct bt_gatt_attr *attr,
			 void *buf, uint16_t len, uint16_t offset)
{
	return read_encoded(conn, attr, buf, len, offset,
			    sb_ble_encode_device_info(device,
						      (uint32_t)k_uptime_get_32(),
						      sb_pmic_battery_pct(),
						      SB_FIRMWARE_VERSION,
						      sb_fsr_faults(), payload,
						      sizeof(payload)));
}

/* ⛔ ENROLMENT IS A WRITE, AND ITS ANSWER CAN BE "NO". sb_enroll_write() refuses
 * a label the insert cannot tell apart from one it already knows, and that
 * refusal is the interesting case — accepting it would make two objects
 * interchangeable for good. The decision is sb_ble.c's; this only carries it. */
static ssize_t write_enroll(struct bt_conn *conn,
			    const struct bt_gatt_attr *attr, const void *buf,
			    uint16_t len, uint16_t offset, uint8_t flags)
{
	ARG_UNUSED(conn);
	ARG_UNUSED(attr);
	ARG_UNUSED(flags);
	if (offset != 0) {
		return BT_GATT_ERR(BT_ATT_ERR_INVALID_OFFSET);
	}
	int n = sb_enroll_write(enroll, (sb_device *)device, buf, len,
				(uint32_t)k_uptime_get_32(), payload,
				sizeof(payload));
	if (n < 0) {
		return BT_GATT_ERR(BT_ATT_ERR_WRITE_NOT_PERMITTED);
	}
	return len;
}

static void ccc_changed(const struct bt_gatt_attr *attr, uint16_t value)
{
	ARG_UNUSED(attr);
	LOG_INF("notifications %s", value == BT_GATT_CCC_NOTIFY ? "on" : "off");
}

BT_GATT_SERVICE_DEFINE(smartbag_svc,
	BT_GATT_PRIMARY_SERVICE(&uuid_svc),

	BT_GATT_CHARACTERISTIC(&uuid_inventory.uuid,
			       BT_GATT_CHRC_READ | BT_GATT_CHRC_NOTIFY,
			       BT_GATT_PERM_READ, read_inventory, NULL, NULL),
	BT_GATT_CCC(ccc_changed, BT_GATT_PERM_READ | BT_GATT_PERM_WRITE),

	BT_GATT_CHARACTERISTIC(&uuid_position.uuid,
			       BT_GATT_CHRC_READ | BT_GATT_CHRC_NOTIFY,
			       BT_GATT_PERM_READ, read_position, NULL, NULL),
	BT_GATT_CCC(ccc_changed, BT_GATT_PERM_READ | BT_GATT_PERM_WRITE),

	BT_GATT_CHARACTERISTIC(&uuid_event.uuid, BT_GATT_CHRC_NOTIFY,
			       BT_GATT_PERM_NONE, NULL, NULL, NULL),
	BT_GATT_CCC(ccc_changed, BT_GATT_PERM_READ | BT_GATT_PERM_WRITE),

	BT_GATT_CHARACTERISTIC(&uuid_enroll.uuid,
			       BT_GATT_CHRC_WRITE | BT_GATT_CHRC_NOTIFY,
			       BT_GATT_PERM_WRITE, NULL, write_enroll, NULL),
	BT_GATT_CCC(ccc_changed, BT_GATT_PERM_READ | BT_GATT_PERM_WRITE),

	BT_GATT_CHARACTERISTIC(&uuid_info.uuid, BT_GATT_CHRC_READ,
			       BT_GATT_PERM_READ, read_info, NULL, NULL),
);

static const struct bt_data ad[] = {
	BT_DATA_BYTES(BT_DATA_FLAGS, (BT_LE_AD_GENERAL | BT_LE_AD_NO_BREDR)),
	BT_DATA(BT_DATA_NAME_COMPLETE, CONFIG_BT_DEVICE_NAME,
		sizeof(CONFIG_BT_DEVICE_NAME) - 1),
};

int sb_gatt_start(const sb_device *d, const sb_config *cfg, sb_enroll *e)
{
	device = d;
	config = cfg;
	enroll = e;
	/* ⚠️ Connectable advertising costs 12 mW for a millisecond a second, which
	 * is 12 uW of the 0.14 mW budget in thermal/budget.py — the second largest
	 * term in it, and the reason this is not faster. */
	return bt_le_adv_start(BT_LE_ADV_CONN_FAST_1, ad, ARRAY_SIZE(ad), NULL, 0);
}

/* Called by main() when something happened the app should hear about. */
void sb_gatt_notify_event(sb_ble_event_type type, uint16_t object_id,
			  uint32_t now_ms)
{
	int n = sb_ble_encode_event(type, object_id, now_ms, payload,
				    sizeof(payload));
	if (n > 0) {
		bt_gatt_notify(NULL, &smartbag_svc.attrs[7], payload, (uint16_t)n);
	}
}
