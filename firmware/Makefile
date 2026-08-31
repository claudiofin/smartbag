# ⚠️ -Wall -Wextra -Werror on purpose: this is the one part of the project a
# compiler can actually check, so it may as well be strict.
CFLAGS ?= -std=c11 -Wall -Wextra -Werror -O2

BINS = test_smartbag test_sb_fsr test_sb_ble test_sb_power test_sb_sensors

test: $(BINS)
	./test_smartbag
	./test_sb_fsr
	./test_sb_ble
	./test_sb_power
	./test_sb_sensors

test_smartbag: test_smartbag.c smartbag.c smartbag.h
	$(CC) $(CFLAGS) -o $@ test_smartbag.c smartbag.c

# ⭐ -lm because the test contains a nodal solver: it simulates the resistive
# matrix rather than mocking it. See the header of test_sb_fsr.c.
test_sb_fsr: test_sb_fsr.c sb_fsr.c sb_fsr.h
	$(CC) $(CFLAGS) -o $@ test_sb_fsr.c sb_fsr.c -lm

test_sb_ble: test_sb_ble.c sb_ble.c smartbag.c sb_ble.h smartbag.h
	$(CC) $(CFLAGS) -o $@ test_sb_ble.c sb_ble.c smartbag.c

# ⭐ The golden vectors the phone side is tested against. Regenerate whenever a
# payload changes; app/test_protocol.mjs will fail if the two drift.
vectors: gen_vectors
	./gen_vectors > ../app/vectors.json
	@echo "wrote app/vectors.json"

gen_vectors: gen_vectors.c sb_ble.c smartbag.c sb_ble.h smartbag.h
	$(CC) $(CFLAGS) -o $@ gen_vectors.c sb_ble.c smartbag.c

test_sb_power: test_sb_power.c sb_power.c sb_power.h
	$(CC) $(CFLAGS) -o $@ test_sb_power.c sb_power.c

test_sb_sensors: test_sb_sensors.c sb_sensors.c sb_sensors.h sb_hal.h
	$(CC) $(CFLAGS) -o $@ test_sb_sensors.c sb_sensors.c

clean:
	rm -f $(BINS) gen_vectors

.PHONY: test clean vectors
