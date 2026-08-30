#include "sb_fsr.h"

#include <string.h>

/* raw ADC counts -> conductance of the taxel, in microsiemens.
 *
 * The row sits on a sense resistor to ground, so the divider is
 * Vrow = Vdrive * Rs / (Rs + Rtaxel), which inverts to
 * Rtaxel = Rs * (full - raw) / raw, and 1/Rtaxel is what we want.
 *
 * ⭐ CONDUCTANCE, NOT RESISTANCE, and not "force". An FSR's conductance is
 * roughly proportional to applied load, so conductance is the quantity that
 * adds up the way a mass does — two taxels under one object can be summed.
 * Resistance cannot. Calling it grams would be the invented step. */
static uint16_t raw_to_us(uint16_t raw, sb_fsr_mode mode)
{
    if (mode == SB_FSR_SCAN_TIA) {
        /* The row never moves, so there is no divider to invert: the
         * amplifier output is proportional to the taxel current, and the
         * taxel current is proportional to its conductance. */
        uint32_t g = (uint32_t)raw * 1000000u
                     / (SB_ADC_FULL_SCALE * SB_TIA_FEEDBACK_OHMS);
        return g > 0xFFFFu ? 0xFFFFu : (uint16_t)g;
    }
    if (raw == 0) {
        return 0;                      /* open: nothing on this taxel */
    }
    if (raw >= SB_ADC_FULL_SCALE) {
        return 0xFFFFu;                /* rail: saturated */
    }
    uint64_t num = (uint64_t)raw * 1000000u;
    uint64_t den = (uint64_t)SB_SENSE_OHMS * (SB_ADC_FULL_SCALE - raw);
    uint64_t g = (num + den / 2) / den;
    return g > 0xFFFFu ? 0xFFFFu : (uint16_t)g;
}

void sb_fsr_scan(const sb_fsr_hal *hal, sb_fsr_mode mode, sb_fsr_frame *out)
{
    for (uint8_t c = 0; c < SB_FSR_COLS; c++) {
        /* Park every column first, then raise exactly one. The order matters:
         * raising the new column before dropping the old one shorts two drivers
         * through whatever is pressed between them. */
        for (uint8_t k = 0; k < SB_FSR_COLS; k++) {
            hal->drive_column(hal->ctx, k,
                              mode == SB_FSR_SCAN_NAIVE ? SB_FSR_HIZ
                                                        : SB_FSR_LOW);
        }
        hal->drive_column(hal->ctx, c, SB_FSR_HIGH);
        hal->settle_us(hal->ctx, SB_FSR_SETTLE_US);

        for (uint8_t r = 0; r < SB_FSR_ROWS; r++) {
            out->g_us[r * SB_FSR_COLS + c] =
                raw_to_us(hal->read_row(hal->ctx, r), mode);
        }
    }
    /* Leave the matrix cold. ⚠️ A column left driven high through a pressed
     * taxel is a permanent milliamp, which is the whole sleep budget. */
    for (uint8_t k = 0; k < SB_FSR_COLS; k++) {
        hal->drive_column(hal->ctx, k, SB_FSR_HIZ);
    }
}

void sb_fsr_calibrate(const sb_fsr_hal *hal, sb_fsr_mode mode,
                      sb_fsr_frame *out)
{
    sb_fsr_scan(hal, mode, out);
    memcpy(out->baseline_us, out->g_us, sizeof(out->baseline_us));
    out->calibrated = true;
}

uint16_t sb_fsr_at(const sb_fsr_frame *f, uint8_t col, uint8_t row)
{
    return f->g_us[row * SB_FSR_COLS + col];
}

uint16_t sb_fsr_delta(const sb_fsr_frame *f, uint8_t col, uint8_t row)
{
    uint16_t v = sb_fsr_at(f, col, row);
    if (!f->calibrated) {
        return v;
    }
    uint16_t b = f->baseline_us[row * SB_FSR_COLS + col];
    return v > b ? (uint16_t)(v - b) : 0u;
}

int sb_fsr_blobs(const sb_fsr_frame *f, uint16_t threshold_us,
                 uint16_t pitch_x_um, uint16_t pitch_y_um,
                 sb_fsr_blob *out, int max)
{
    bool hot[SB_FSR_TAXELS];
    bool seen[SB_FSR_TAXELS];
    for (uint8_t r = 0; r < SB_FSR_ROWS; r++) {
        for (uint8_t c = 0; c < SB_FSR_COLS; c++) {
            uint16_t i = (uint16_t)(r * SB_FSR_COLS + c);
            hot[i] = sb_fsr_delta(f, c, r) >= threshold_us;
            seen[i] = false;
        }
    }

    sb_fsr_blob found[SB_FSR_TAXELS];
    int n = 0;
    uint16_t stack[SB_FSR_TAXELS];

    for (uint16_t s = 0; s < SB_FSR_TAXELS; s++) {
        if (!hot[s] || seen[s]) {
            continue;
        }
        /* Flood fill, 4-connected. ⚠️ 8-connected would merge two objects that
         * touch only at a corner, and at a 14 mm taxel pitch a corner touch is
         * a whole centimetre of separation. */
        int sp = 0;
        stack[sp++] = s;
        seen[s] = true;
        uint64_t wsum = 0, wx = 0, wy = 0;
        uint8_t cells = 0;

        while (sp > 0) {
            uint16_t i = stack[--sp];
            uint8_t c = (uint8_t)(i % SB_FSR_COLS);
            uint8_t r = (uint8_t)(i / SB_FSR_COLS);
            uint32_t w = sb_fsr_delta(f, c, r);
            wsum += w;
            wx += (uint64_t)w * ((uint32_t)c * pitch_x_um + pitch_x_um / 2);
            wy += (uint64_t)w * ((uint32_t)r * pitch_y_um + pitch_y_um / 2);
            cells++;

            if (c > 0 && hot[i - 1] && !seen[i - 1]) {
                seen[i - 1] = true; stack[sp++] = (uint16_t)(i - 1);
            }
            if (c + 1 < SB_FSR_COLS && hot[i + 1] && !seen[i + 1]) {
                seen[i + 1] = true; stack[sp++] = (uint16_t)(i + 1);
            }
            if (r > 0 && hot[i - SB_FSR_COLS] && !seen[i - SB_FSR_COLS]) {
                seen[i - SB_FSR_COLS] = true;
                stack[sp++] = (uint16_t)(i - SB_FSR_COLS);
            }
            if (r + 1 < SB_FSR_ROWS && hot[i + SB_FSR_COLS]
                && !seen[i + SB_FSR_COLS]) {
                seen[i + SB_FSR_COLS] = true;
                stack[sp++] = (uint16_t)(i + SB_FSR_COLS);
            }
        }

        if (wsum == 0 || n >= SB_FSR_TAXELS) {
            continue;
        }
        uint32_t x_um = (uint32_t)(wx / wsum);
        uint32_t y_um = (uint32_t)(wy / wsum);
        uint32_t span_um = (uint32_t)SB_FSR_COLS * pitch_x_um;
        found[n].cells = cells;
        found[n].weight_us = (uint32_t)(wsum > 0xFFFFFFFFu ? 0xFFFFFFFFu : wsum);
        found[n].x_um = (int32_t)x_um;
        found[n].y_um = (int32_t)y_um;
        found[n].compartment = (uint8_t)(x_um < span_um / 3 ? 0
                                         : x_um < 2 * span_um / 3 ? 1 : 2);
        n++;
    }

    /* Largest first: a caller with room for four blobs should get the four
     * that matter, not the four with the lowest index. */
    for (int i = 1; i < n; i++) {
        sb_fsr_blob key = found[i];
        int j = i - 1;
        while (j >= 0 && found[j].weight_us < key.weight_us) {
            found[j + 1] = found[j];
            j--;
        }
        found[j + 1] = key;
    }

    int emit = n < max ? n : max;
    for (int i = 0; i < emit; i++) {
        out[i] = found[i];
    }
    return emit;
}
