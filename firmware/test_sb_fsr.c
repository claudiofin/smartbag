/* The taxel matrix, tested against the circuit rather than against a mock.
 *
 * ⭐ WHY THERE IS A SOLVER IN A UNIT TEST. A mock HAL that hands back canned
 * numbers can only confirm that the driver copies them into an array. The
 * question worth asking about a passive matrix is not "does the loop iterate",
 * it is "does current go where you think it does" — and that question has an
 * answer only if the test contains the network. So this file builds the nodal
 * admittance matrix of the real thing: 16 columns, 6 rows, 96 resistors, a
 * sense resistor per row, and whatever the scan mode does to the drivers. Then
 * it solves it.
 *
 * ⛔ WHAT THAT TURNED UP is in test_ghosting(): with the columns floating, three
 * pressed taxels manufacture a fourth, and the driver cannot tell the
 * difference. That is not a bug in the driver. It is the board.
 */
#include "sb_fsr.h"

#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

#define VDRIVE 1.0
#define R_OPEN 10.0e6
#define R_PRESSED 2000.0
#define UNKNOWNS (SB_FSR_ROWS + SB_FSR_COLS)

typedef struct {
    double r[SB_FSR_COLS][SB_FSR_ROWS];   /* taxel resistance */
    sb_fsr_drive drive[SB_FSR_COLS];
    double v_row[SB_FSR_ROWS];            /* solved, after settle */
    double i_row[SB_FSR_ROWS];            /* only meaningful with a TIA */
    /* ⚠️ This flag is an ANALOG FRONT END, not a firmware setting. It says the
     * rows are held at virtual ground by an amplifier. No value written to a
     * register can make the board behave this way; a component can. */
    int tia;
    int solves;
} panel;

static void panel_init(panel *p)
{
    memset(p, 0, sizeof(*p));
    for (int c = 0; c < SB_FSR_COLS; c++) {
        p->drive[c] = SB_FSR_HIZ;
        for (int r = 0; r < SB_FSR_ROWS; r++) {
            p->r[c][r] = R_OPEN;
        }
    }
}

static void press(panel *p, int c, int r, double ohms)
{
    p->r[c][r] = ohms;
}

/* Gaussian elimination, partial pivoting. 21 unknowns at worst. */
static void solve(double a[UNKNOWNS][UNKNOWNS + 1], double *x, int n)
{
    for (int i = 0; i < n; i++) {
        int piv = i;
        for (int k = i + 1; k < n; k++) {
            if (fabs(a[k][i]) > fabs(a[piv][i])) {
                piv = k;
            }
        }
        for (int j = 0; j <= n; j++) {
            double t = a[i][j]; a[i][j] = a[piv][j]; a[piv][j] = t;
        }
        assert(fabs(a[i][i]) > 1e-18 && "singular network");
        for (int k = i + 1; k < n; k++) {
            double f = a[k][i] / a[i][i];
            for (int j = i; j <= n; j++) {
                a[k][j] -= f * a[i][j];
            }
        }
    }
    for (int i = n - 1; i >= 0; i--) {
        double s = a[i][n];
        for (int j = i + 1; j < n; j++) {
            s -= a[i][j] * x[j];
        }
        x[i] = s / a[i][i];
    }
}

/* Nodal analysis of the panel in its current drive state.
 *
 * Unknowns: every row, plus every Hi-Z column. Driven columns are known
 * voltages and move to the right-hand side. Each row sinks through Rs to
 * ground, which is the only thing tying the network to a reference. */
static void panel_solve(panel *p)
{
    if (p->tia) {
        /* Rows pinned to 0 V. Every unselected column is also at 0 V, so every
         * taxel that is not on the driven column has zero volts across it and
         * carries nothing. No network to solve — that is the whole point. */
        for (int r = 0; r < SB_FSR_ROWS; r++) {
            double i = 0;
            for (int c = 0; c < SB_FSR_COLS; c++) {
                double vc = (p->drive[c] == SB_FSR_HIGH) ? VDRIVE : 0.0;
                i += vc / p->r[c][r];
            }
            p->i_row[r] = i;
        }
        p->solves++;
        return;
    }
    int idx[SB_FSR_COLS];
    int n = SB_FSR_ROWS;
    for (int c = 0; c < SB_FSR_COLS; c++) {
        idx[c] = (p->drive[c] == SB_FSR_HIZ) ? n++ : -1;
    }

    double a[UNKNOWNS][UNKNOWNS + 1];
    memset(a, 0, sizeof(a));

    for (int r = 0; r < SB_FSR_ROWS; r++) {
        a[r][r] += 1.0 / SB_SENSE_OHMS;
        for (int c = 0; c < SB_FSR_COLS; c++) {
            double g = 1.0 / p->r[c][r];
            a[r][r] += g;
            if (idx[c] >= 0) {
                a[r][idx[c]] -= g;
            } else {
                double vc = (p->drive[c] == SB_FSR_HIGH) ? VDRIVE : 0.0;
                a[r][UNKNOWNS] += g * vc;      /* known source term */
            }
        }
    }
    for (int c = 0; c < SB_FSR_COLS; c++) {
        if (idx[c] < 0) {
            continue;
        }
        int i = idx[c];
        for (int r = 0; r < SB_FSR_ROWS; r++) {
            double g = 1.0 / p->r[c][r];
            a[i][i] += g;
            a[i][r] -= g;
        }
    }

    /* The RHS column lives at index UNKNOWNS; compact it to n for the solver. */
    for (int i = 0; i < n; i++) {
        a[i][n] = a[i][UNKNOWNS];
    }
    double x[UNKNOWNS] = {0};
    solve(a, x, n);
    for (int r = 0; r < SB_FSR_ROWS; r++) {
        p->v_row[r] = x[r];
    }
    p->solves++;
}

/* ── HAL backed by the simulated panel ───────────────────────────────────── */
static void hal_drive(void *ctx, uint8_t col, sb_fsr_drive mode)
{
    ((panel *)ctx)->drive[col] = mode;
}
static void hal_settle(void *ctx, uint32_t us)
{
    (void)us;
    panel_solve((panel *)ctx);
}
static uint16_t hal_read(void *ctx, uint8_t row)
{
    panel *p = (panel *)ctx;
    double v = p->tia
        ? p->i_row[row] * SB_TIA_FEEDBACK_OHMS / VDRIVE
        : p->v_row[row] / VDRIVE;
    if (v < 0) v = 0;
    if (v > 1) v = 1;
    long raw = lround(v * SB_ADC_FULL_SCALE);
    return (uint16_t)raw;
}
static sb_fsr_hal make_hal(panel *p)
{
    sb_fsr_hal h = { hal_drive, hal_read, hal_settle, p };
    return h;
}

/* ── tests ───────────────────────────────────────────────────────────────── */
static int checks = 0;
#define CHECK(c) do { assert(c); checks++; } while (0)

static void test_single_taxel(void)
{
    panel p; panel_init(&p);
    press(&p, 5, 2, R_PRESSED);
    sb_fsr_hal h = make_hal(&p);

    for (int m = 0; m < 2; m++) {
        sb_fsr_frame f; memset(&f, 0, sizeof(f));
        sb_fsr_scan(&h, m ? SB_FSR_SCAN_GROUNDED : SB_FSR_SCAN_NAIVE, &f);
        uint16_t g = sb_fsr_at(&f, 5, 2);
        /* 1/2000 ohm = 500 uS; allow the ADC quantisation and the open-taxel
         * leakage that a real matrix also has. */
        CHECK(g > 480 && g < 520);
        for (int c = 0; c < SB_FSR_COLS; c++) {
            for (int r = 0; r < SB_FSR_ROWS; r++) {
                if (!(c == 5 && r == 2)) {
                    CHECK(sb_fsr_at(&f, (uint8_t)c, (uint8_t)r) < 20);
                }
            }
        }
    }
    /* One solve per column, per scan, and not one more: the settle is where the
     * power goes and the driver must not re-read. */
    CHECK(p.solves == 2 * SB_FSR_COLS);
}

static void test_ghosting(void)
{
    /* The classic sneak path. Press an L: (c1,r1), (c1,r2), (c2,r2).
     * Nothing is on (c2,r1) — and with the columns floating, the matrix
     * reports it anyway, because current leaving driven column c2 through
     * (c2,r2) can climb back up floating column c1 and come down (c1,r1). */
    const int c1 = 3, c2 = 4, r1 = 1, r2 = 2;
    panel p; panel_init(&p);
    press(&p, c1, r1, R_PRESSED);
    press(&p, c1, r2, R_PRESSED);
    press(&p, c2, r2, R_PRESSED);
    sb_fsr_hal h = make_hal(&p);

    sb_fsr_frame naive; memset(&naive, 0, sizeof(naive));
    sb_fsr_scan(&h, SB_FSR_SCAN_NAIVE, &naive);
    uint16_t ghost = sb_fsr_at(&naive, c2, r1);
    uint16_t real = sb_fsr_at(&naive, c2, r2);
    printf("  ghosting: phantom taxel reads %u uS against a real %u uS "
           "(%.0f%% of it)\n", ghost, real, 100.0 * ghost / real);
    /* ⛔ Not a rounding error. It is a substantial fraction of a real press. */
    CHECK(ghost > 100);

    sb_fsr_frame grounded; memset(&grounded, 0, sizeof(grounded));
    sb_fsr_scan(&h, SB_FSR_SCAN_GROUNDED, &grounded);
    uint16_t no_ghost = sb_fsr_at(&grounded, c2, r1);
    printf("  grounded: same phantom reads %u uS\n", no_ghost);
    CHECK(no_ghost < 20);

    /* ⚠️ And here is what grounding costs. The unselected columns now sink
     * current that used to reach the sense resistor, so every real taxel reads
     * low. The phantom is gone; the magnitudes are no longer trustworthy. */
    uint16_t real_g = sb_fsr_at(&grounded, c2, r2);
    printf("  grounded: the real taxel reads %u uS instead of 500 uS "
           "(%.0f%% low)\n", real_g, 100.0 * (500.0 - real_g) / 500.0);
    CHECK(real_g < 500);
}

static void test_tia_is_exact(void)
{
    /* ⭐ Same L-shaped press that ghosts. With the rows at virtual ground the
     * matrix reports exactly three taxels at exactly their own conductance —
     * no phantom, no attenuation, no dependence on what else is pressed.
     * This is the control case that makes the other two numbers mean
     * something: the matrix is not inherently unreadable, this board's front
     * end cannot read it. */
    const int c1 = 3, c2 = 4, r1 = 1, r2 = 2;
    panel p; panel_init(&p);
    press(&p, c1, r1, R_PRESSED);
    press(&p, c1, r2, R_PRESSED);
    press(&p, c2, r2, R_PRESSED);
    p.tia = 1;
    sb_fsr_hal h = make_hal(&p);
    sb_fsr_frame f; memset(&f, 0, sizeof(f));
    sb_fsr_scan(&h, SB_FSR_SCAN_TIA, &f);

    printf("  TIA: the three real taxels read %u %u %u uS, phantom %u uS\n",
           sb_fsr_at(&f, c1, r1), sb_fsr_at(&f, c1, r2),
           sb_fsr_at(&f, c2, r2), sb_fsr_at(&f, c2, r1));
    CHECK(sb_fsr_at(&f, c1, r1) > 480 && sb_fsr_at(&f, c1, r1) < 520);
    CHECK(sb_fsr_at(&f, c1, r2) > 480 && sb_fsr_at(&f, c1, r2) < 520);
    CHECK(sb_fsr_at(&f, c2, r2) > 480 && sb_fsr_at(&f, c2, r2) < 520);
    CHECK(sb_fsr_at(&f, c2, r1) < 20);
}

static void test_blobs(void)
{
    panel p; panel_init(&p);
    /* two objects: a 2x2 patch on the left, a heavier 3x2 on the right */
    for (int c = 1; c <= 2; c++) {
        for (int r = 1; r <= 2; r++) {
            press(&p, c, r, R_PRESSED);
        }
    }
    for (int c = 12; c <= 14; c++) {
        for (int r = 2; r <= 3; r++) {
            press(&p, c, r, R_PRESSED / 2);
        }
    }
    sb_fsr_hal h = make_hal(&p);
    sb_fsr_frame f; memset(&f, 0, sizeof(f));
    p.tia = 1;
    sb_fsr_scan(&h, SB_FSR_SCAN_TIA, &f);

    sb_fsr_blob b[SB_FSR_MAX_BLOBS];
    /* pitch from dimensions.py: 225 mm / 16 and 78 mm / 6 */
    int n = sb_fsr_blobs(&f, 100, 14062, 13000, b, SB_FSR_MAX_BLOBS);
    printf("  blobs: %d found; heaviest %u uS in compartment %u at "
           "x=%.1f mm\n", n, b[0].weight_us, b[0].compartment,
           b[0].x_um / 1000.0);
    CHECK(n == 2);
    CHECK(b[0].weight_us > b[1].weight_us);       /* heaviest first */
    CHECK(b[0].compartment == 2);                  /* the right-hand object */
    CHECK(b[1].compartment == 0);
    CHECK(b[0].cells == 6 && b[1].cells == 4);
    /* ⛔ The assertion that found the int16 truncation. Columns 12..14 sit at
     * 190 mm, not at 32 mm, and 32 mm was what the struct could hold. */
    CHECK(b[0].x_um > 185000 && b[0].x_um < 195000);
    CHECK(b[0].y_um > 35000 && b[0].y_um < 43000);
    CHECK(b[1].x_um > 24000 && b[1].x_um < 33000);
}

static void test_diagonal_stays_two(void)
{
    /* ⚠️ Two objects touching only at a corner are 14 mm apart. 8-connected
     * labelling would merge them into one and the app would show one object
     * where there are two. */
    panel p; panel_init(&p);
    press(&p, 6, 2, R_PRESSED);
    press(&p, 7, 3, R_PRESSED);
    sb_fsr_hal h = make_hal(&p);
    p.tia = 1;
    sb_fsr_frame f; memset(&f, 0, sizeof(f));
    sb_fsr_scan(&h, SB_FSR_SCAN_TIA, &f);
    sb_fsr_blob b[SB_FSR_MAX_BLOBS];
    CHECK(sb_fsr_blobs(&f, 100, 14062, 13000, b, SB_FSR_MAX_BLOBS) == 2);
}

static void test_baseline(void)
{
    /* An unloaded matrix is not zero: 96 taxels at 10 Mohm leak. Calibration
     * is what makes the threshold mean something. */
    panel p; panel_init(&p);
    sb_fsr_hal h = make_hal(&p);
    p.tia = 1;
    sb_fsr_frame f; memset(&f, 0, sizeof(f));
    sb_fsr_calibrate(&h, SB_FSR_SCAN_TIA, &f);
    CHECK(f.calibrated);
    for (int c = 0; c < SB_FSR_COLS; c++) {
        for (int r = 0; r < SB_FSR_ROWS; r++) {
            CHECK(sb_fsr_delta(&f, (uint8_t)c, (uint8_t)r) == 0);
        }
    }
    press(&p, 8, 4, R_PRESSED);
    sb_fsr_scan(&h, SB_FSR_SCAN_TIA, &f);
    CHECK(sb_fsr_delta(&f, 8, 4) > 300);
    CHECK(sb_fsr_delta(&f, 8, 3) == 0);
}

static void test_no_double_drive(void)
{
    /* After a scan every column must be parked. A column left high through a
     * pressed taxel draws half a milliamp for as long as the bag is shut. */
    panel p; panel_init(&p);
    press(&p, 2, 2, R_PRESSED);
    sb_fsr_hal h = make_hal(&p);
    sb_fsr_frame f; memset(&f, 0, sizeof(f));
    sb_fsr_scan(&h, SB_FSR_SCAN_GROUNDED, &f);
    for (int c = 0; c < SB_FSR_COLS; c++) {
        CHECK(p.drive[c] == SB_FSR_HIZ);
    }
}

int main(void)
{
    printf("sb_fsr: scanning a passive matrix, simulated as a circuit\n");
    test_single_taxel();
    test_ghosting();
    test_tia_is_exact();
    test_blobs();
    test_diagonal_stays_two();
    test_baseline();
    test_no_double_drive();
    printf("%d checks passed\n", checks);
    return 0;
}
