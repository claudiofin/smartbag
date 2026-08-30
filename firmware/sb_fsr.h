/* The taxel matrix: scanning it, and the reason the obvious way does not work.
 *
 * ⛔ THIS IS A PASSIVE RESISTIVE MATRIX WITH NO PER-TAXEL ISOLATION. Look at
 * hardware/netlist.py: 16 columns driven from U1, 6 rows read back, a 24-way
 * FFC, and not one diode among them. That is 96 sensors on 22 wires, which is
 * the entire reason the matrix is affordable — and it is also a circuit in
 * which current does not stay where you put it.
 *
 * ⭐ THE FAILURE HAS A NAME. Drive one column, leave the others floating, and
 * current from a pressed taxel can return through a *second* pressed taxel,
 * back up its column, and down through a *third* — arriving at a row that has
 * nothing on it. The matrix reports a taxel that is not there. Three real
 * contacts manufacture a fourth: it is the same sneak path that makes cheap
 * keyboards register phantom keys, and a bag full of objects is exactly the
 * many-simultaneous-contacts case that provokes it.
 *
 * ⚠️ So the scan mode is not a detail, it is the difference between a position
 * map and fiction. test_sb_fsr.c does not mock this: it solves the actual
 * resistive network and measures how wrong each mode is.
 *
 * ⛔ NO REGISTER WRITES HERE EITHER. The HAL below is three function pointers.
 * Which GPIO, which ADC, which mux — that is silicon-specific and unwritten.
 */
#ifndef SB_FSR_H
#define SB_FSR_H

#include <stdbool.h>
#include <stdint.h>

/* ⚠️ Must match FSR_COLS / FSR_ROWS in dimensions.py. tools/check.py enforces it. */
#define SB_FSR_COLS 16
#define SB_FSR_ROWS 6
#define SB_FSR_TAXELS (SB_FSR_COLS * SB_FSR_ROWS)
#define SB_FSR_MAX_BLOBS 8

#define SB_ADC_FULL_SCALE 4095u
#define SB_SENSE_OHMS 10000u
#define SB_TIA_FEEDBACK_OHMS 1000u

typedef enum { SB_FSR_HIZ, SB_FSR_LOW, SB_FSR_HIGH } sb_fsr_drive;

typedef enum {
    /* Unselected columns left floating. The cheapest thing to write, and the
     * one that ghosts. Kept because the test has to be able to provoke it. */
    SB_FSR_SCAN_NAIVE,
    /* Unselected columns actively driven to 0 V. Kills the phantoms — a sneak
     * path needs a floating node to develop a voltage on — but the grounded
     * columns now sit in parallel with the sense resistor, so every real taxel
     * reads low whenever anything else in its row is loaded. The test measures
     * how low: it is not a trim, it is a factor of six. */
    SB_FSR_SCAN_GROUNDED,
    /* ⛔ NEEDS HARDWARE THIS BOARD DOES NOT HAVE. Rows held at virtual ground by
     * a transimpedance amplifier, unselected columns at 0 V. Now every
     * non-selected taxel has zero volts across it and carries no current at
     * all, so the reading is exactly the selected taxel and nothing else.
     * That is the only one of the three that is correct — and it costs six
     * op-amps, or one plus an analog mux, neither of which is in
     * hardware/netlist.py. Selecting this mode in firmware on the board as
     * drawn changes the drive pattern and nothing else. */
    SB_FSR_SCAN_TIA,
} sb_fsr_mode;

typedef struct {
    void (*drive_column)(void *ctx, uint8_t col, sb_fsr_drive mode);
    uint16_t (*read_row)(void *ctx, uint8_t row);   /* raw ADC counts */
    void (*settle_us)(void *ctx, uint32_t us);
    void *ctx;
} sb_fsr_hal;

typedef struct {
    uint16_t g_us[SB_FSR_TAXELS];      /* conductance, microsiemens */
    uint16_t baseline_us[SB_FSR_TAXELS];
    bool calibrated;
} sb_fsr_frame;

typedef struct {
    uint8_t cells;
    uint32_t weight_us;                /* summed conductance: a mass proxy */
    /* ⛔ int32, and it took a test to find out why. Micrometres across a 225 mm
     * insert need 225000 counts; an int16 saturates at 32.8 mm, which is inside
     * the left compartment. Every object in the other two thirds of the bag
     * reported the same position, and it read as plausible because 32 mm is a
     * real place. The BLE layer rounds to the millimetres the wire format asks
     * for — the truncation belongs there, on purpose, not here by accident. */
    int32_t x_um, y_um;                 /* centroid, micrometres from corner */
    uint8_t compartment;                /* 0 left · 1 middle · 2 right */
} sb_fsr_blob;

/* Settling matters: the column has to charge the row capacitance of a 200 mm
 * flex before the ADC is allowed to believe it. */
#define SB_FSR_SETTLE_US 120u

void sb_fsr_scan(const sb_fsr_hal *hal, sb_fsr_mode mode, sb_fsr_frame *out);

/* Capture the unloaded matrix as the zero. An FSR's unpressed resistance drifts
 * with temperature and with how long it has been folded; the absolute value is
 * not worth trusting, the change from baseline is. */
void sb_fsr_calibrate(const sb_fsr_hal *hal, sb_fsr_mode mode,
                      sb_fsr_frame *out);

uint16_t sb_fsr_at(const sb_fsr_frame *f, uint8_t col, uint8_t row);

/* Conductance above baseline, floored at zero. */
uint16_t sb_fsr_delta(const sb_fsr_frame *f, uint8_t col, uint8_t row);

/* Connected components over taxels above `threshold_us` of delta, 4-connected.
 * ⭐ This is the step that turns a pressure image into things: the position map
 * wants one entry per object, and an object is a contiguous patch of load.
 * Returns the number of blobs written, largest first. */
int sb_fsr_blobs(const sb_fsr_frame *f, uint16_t threshold_us,
                 uint16_t pitch_x_um, uint16_t pitch_y_um,
                 sb_fsr_blob *out, int max);

#endif /* SB_FSR_H */
