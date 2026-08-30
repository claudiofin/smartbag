#!/usr/bin/env python3
"""Full-wave FDTD of one 60 GHz patch element, on the stackup the board declares.

⭐ THIS IS A REAL SIMULATION, not a formula. openEMS solves Maxwell's equations
on the actual geometry: ground plane, dielectric, patch, probe feed. It can
therefore disagree with the design, which is the only reason to run it.

⛔ WHAT IT DOES NOT COVER. One element in isolation, no array coupling, no flex
bend, no soldermask (the design leaves the patches bare, which is why), no
package or connector parasitics, and an assumed εr. It answers one question —
does a 1.2 mm patch on this stackup resonate where the design claims, and with
what match — and nothing else.

⚠️ The stackup thickness is the interesting variable. The board is 0.6 mm
because that is what the rigid islands are; nobody chose it for the antenna.
The sweep exists to find out what that costs.

Usage:  python3 rf/patch_sim.py [--sweep] [--cells 0.045]
"""
import os
import shutil
import sys
import tempfile

import numpy as np
from CSXCAD import ContinuousStructure
from openEMS import openEMS
from openEMS.physical_constants import C0

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import dimensions as dim          # noqa: E402

# ─── the design, from hardware/generate_pcb.py ────────────────────────────────
PATCH = 1.2          # mm, the square patch drawn on F.Cu
PITCH = 2.5          # mm, element spacing = lambda0/2 at 60 GHz
F0 = 60e9
BW = 25e9            # excitation bandwidth: 35..85 GHz

# Polyimide flex. εr and loss are the usual figures for a low-loss polyimide
# laminate at mmWave; they are assumptions, and the result moves with them.
EPS_R = 3.4
TAN_D = 0.008
COPPER = 0.018       # mm, 1/2 oz


def graded(edge, far, first, ratio=1.35, sign=1):
    """Cell positions from `edge` out to `far`, growing geometrically.

    ⛔ THE MESH JUMP IS WHAT MADE IT DIVERGE, not the boundaries and not the
    losses. Going straight from 0.03 mm cells over the patch to 0.47 mm cells in
    the far field is a 16:1 step, and FDTD is unstable across a jump like that:
    every run reported "Energy: ~ nan" from the first timestep. Bisecting it took
    three wrong hypotheses — PML over a conductor, the lossy dielectric, the
    port — before a uniform-mesh control case came out clean and a non-uniform
    one with the same everything else did not.

    ⭐ 1.35 per step is the usual openEMS guidance. It costs cells and buys a
    simulation that runs.
    """
    # ⚠️ The steps are RESCALED to land exactly on `far`. Appending the far
    # edge after the last geometric step leaves a stub cell — here 0.085 mm
    # after a 0.81 mm neighbour, a 9.6:1 ratio at the domain wall, and the run
    # diverges for the same reason as before. The join has to be exact, not
    # approximate.
    span = abs(far - edge)
    steps = []
    x, st = 0.0, first
    while x + st < span:
        x += st
        steps.append(st)
        st *= ratio
    if not steps:
        return np.array([far])
    scale = span / sum(steps)
    out, x = [], edge
    for st in steps:
        x += sign * st * scale
        out.append(x)
    out[-1] = far
    return np.array(out)


def _check_mesh(axis, lines, max_ratio=1.6, min_cell=0.004):
    """Refuse to run a mesh that will diverge.

    ⭐ THIS EXISTS BECAUSE THE FAILURE MODE IS SILENT. An FDTD run over a badly
    graded mesh does not error: it prints "Energy: ~ nan" in a log nobody reads
    and returns a spectrum of NaN. Three separate causes were hypothesised and
    disproved before a control case pinned it on the mesh. Checking the mesh
    before spending ninety seconds on it turns that into one line of output.
    """
    d = np.diff(lines)
    if d.min() < min_cell:
        raise ValueError(
            f"{axis} mesh has a {d.min() * 1000:.1f} um sliver cell — a line "
            "was inserted off the grid")
    ratio = float((d[1:] / d[:-1]).max())
    if ratio > max_ratio:
        raise ValueError(
            f"{axis} mesh grades {ratio:.1f}:1 between adjacent cells "
            f"(limit {max_ratio}); FDTD will diverge")


def simulate(h_mm, patch_mm=PATCH, cell=0.045, steps=30000, verbose=0):
    """Return (freq array, S11 in dB) for a probe-fed square patch."""
    fdtd = openEMS(NrTS=steps, EndCriteria=1e-4)
    fdtd.SetGaussExcite(F0, BW)
    # ⛔ PML EVERYWHERE DIVERGED. The ground plane and the substrate are
    # truncated at the domain wall, and a perfect conductor running into an
    # absorbing layer is the classic openEMS instability: the run reported
    # "Energy: ~ nan" from the first timestep and never recovered.
    #
    # ⭐ The stable arrangement for a patch is the physical one: the bottom is
    # the ground plane, so make the boundary PEC and let it BE the ground; the
    # sides truncate substrate and metal, so MUR; only the top is open space,
    # and that is where the PML belongs.
    #   order: xmin xmax ymin ymax zmin zmax
    fdtd.SetBoundaryCond(['MUR', 'MUR', 'MUR', 'MUR', 'PEC', 'PML_8'])

    csx = ContinuousStructure()
    fdtd.SetCSX(csx)
    mesh = csx.GetGrid()
    mesh.SetDeltaUnit(1e-3)

    air = 3.0                      # mm of air above the patch, inside the PML
    half = patch_mm / 2
    x_ext = PITCH * 2.0   # room for the MUR walls to sit in
    # ⚠️ SNAPPED TO THE FINE GRID. An inset of -0.55*half is not a multiple of
    # the cell size, so inserting the two feed lines split neighbouring cells
    # into 0.01 mm slivers — an 8.6:1 local ratio, and the run diverged exactly
    # as before. The probe moves to the nearest grid line instead.
    feed_x = -round(half * 0.55 / (cell / 2)) * (cell / 2)
    # (the port box spans one fine cell either side, so it lands on grid)

    sub = csx.AddMaterial('polyimide', epsilon=EPS_R,
                          kappa=2 * np.pi * F0 * EPS_R * 8.854e-12 * TAN_D)
    sub.AddBox([-x_ext, -x_ext, 0], [x_ext, x_ext, h_mm], priority=1)

    # ⚠️ The ground plane IS the zmin boundary (PEC), not a copper box below
    # z = 0. A box would need its own cells and would put metal into the graded
    # region for no benefit.


    # ⚠️ A ZERO-THICKNESS SHEET, not an 18 um box. The copper thickness is
    # irrelevant to a 60 GHz resonance — but a 18 um cell wedged between 60 um
    # substrate cells is a 3.3:1 jump, and the mesh check refuses it. Modelling
    # thin metal as a sheet is standard FDTD practice for exactly this reason.
    patch = csx.AddMetal('patch')
    patch.AddBox([-half, -half, h_mm], [half, half, h_mm], priority=10)

    port = fdtd.AddLumpedPort(1, 50, [feed_x - cell / 2, -cell / 2, 0],
                              [feed_x + cell / 2, cell / 2, h_mm],
                              'z', 1.0, priority=20)

    # ⭐ Uniform and fine over the patch, graded outward from there. The patch
    # edge sets the resonance, so it gets the small cells; everything past the
    # element pitch only has to not reflect.
    # ⚠️ The fine block must END exactly on the grid, or the graded section
    # starts a fraction of a cell away and opens a sliver right at the join —
    # which is what the 8.6:1 ratio turned out to be, not the feed line.
    step = cell / 2
    n_fine = int(round((half + PITCH / 2) / step))
    fine_half = n_fine * step
    fine = np.linspace(-fine_half, fine_half, 2 * n_fine + 1)
    xs = np.unique(np.concatenate([
        graded(-fine_half, -x_ext, step, sign=-1), fine,
        graded(fine_half, x_ext, step, sign=1)]))
    ys = np.unique(np.concatenate([
        graded(-fine_half, -x_ext, step, sign=-1), fine,
        graded(fine_half, x_ext, step, sign=1)]))
    # Through the substrate at the same fine step, then graded into the air.
    n_sub = max(6, int(round(h_mm / (cell / 2))))
    zs = np.unique(np.concatenate([
        np.linspace(0, h_mm, n_sub + 1),
        graded(h_mm, h_mm + air, h_mm / n_sub, sign=1)]))
    for axis, lines in (('x', xs), ('y', ys), ('z', zs)):
        _check_mesh(axis, lines)
        mesh.AddLine(axis, lines)

    tmp = tempfile.mkdtemp(prefix="patch_")
    # ⛔ openEMS CHANGES THE WORKING DIRECTORY into the simulation folder and
    # does not change back. Deleting that folder afterwards left the process
    # with no cwd at all, and the next `os.path.abspath` — a plain savetxt —
    # died with FileNotFoundError from inside posixpath.
    cwd = os.getcwd()
    try:
        fdtd.Run(tmp, cleanup=True, verbose=verbose)
        os.chdir(cwd)
        f = np.linspace(F0 - BW, F0 + BW, 601)
        port.CalcPort(tmp, f)
        inc = np.abs(port.uf_inc)
        # ⚠️ Test for zero and for NaN, NOT against an absolute magnitude. The
        # port voltage spectrum is ~1e-15 in openEMS's units, so the first guard
        # here (`> 1e-12`) rejected every healthy run and reported a wiring
        # fault that did not exist.
        if not np.isfinite(inc).all() or inc.max() == 0.0:
            raise RuntimeError("port produced no usable spectrum: the run "
                               "diverged, or the port box does not span from "
                               "the ground plane to the patch")
        return f, 20 * np.log10(np.abs(port.uf_ref / port.uf_inc) + 1e-12)
    finally:
        os.chdir(cwd)
        shutil.rmtree(tmp, ignore_errors=True)


def summarise(f, s11):
    i = int(np.argmin(s11))
    f_res, depth = f[i] / 1e9, s11[i]
    below = f[s11 < -10] / 1e9
    bw = (below.max() - below.min()) if len(below) else 0.0
    return f_res, depth, bw


def textbook_patch(h_mm, eps_r=EPS_R, f=F0):
    """Transmission-line-model patch length: the number to check against.

    ⭐ THE SIMULATION HAS TO BE VALIDATED BEFORE IT IS BELIEVED. A negative
    result — "the antenna as drawn does not work" — is only worth stating if the
    same setup reproduces a case that theory says should work. This is that
    case, computed by the standard transmission-line model.
    """
    c = 299792458.0
    w = c / (2 * f) * np.sqrt(2 / (eps_r + 1)) * 1e3
    h = h_mm
    e_eff = (eps_r + 1) / 2 + (eps_r - 1) / 2 * (1 + 12 * h / w) ** -0.5
    dl = (0.412 * h * ((e_eff + 0.3) * (w / h + 0.264))
          / ((e_eff - 0.258) * (w / h + 0.8)))
    return c / (2 * f * np.sqrt(e_eff)) * 1e3 - 2 * dl


def main():
    a = sys.argv[1:]
    cell = float(a[a.index("--cells") + 1]) if "--cells" in a else 0.05
    steps = int(a[a.index("--steps") + 1]) if "--steps" in a else 60000

    print("60 GHz patch element, full-wave FDTD (openEMS)")
    print(f"  polyimide eps_r {EPS_R}, tan d {TAN_D}, cell {cell} mm, "
          f"{steps} max timesteps\n")

    # ── validation ───────────────────────────────────────────────────────────
    h_ref = 0.127
    l_ref = textbook_patch(h_ref)
    f_ref, s_ref = simulate(h_ref, patch_mm=l_ref, cell=cell, steps=steps)
    fr, dr, br = summarise(f_ref, s_ref)
    off = abs(fr - 60.0)
    print("  validation: a patch sized by the transmission-line model")
    print(f"    {l_ref:.2f} mm on {h_ref} mm substrate -> {fr:.1f} GHz, "
          f"{dr:.1f} dB, {br:.1f} GHz of -10 dB bandwidth")
    trusted = off < 6.0 and dr < -6.0
    print("    " + ("setup reproduces a working patch, so a bad result below "
                    "means the design, not the solver"
                    if trusted else
                    "⛔ the setup does NOT reproduce a working patch. Nothing "
                    "below is trustworthy."))

    # ── the design as drawn ──────────────────────────────────────────────────
    print(f"\n  {'substrate':>10}  {'patch':>7}  {'f_res':>9}  {'S11':>8}  "
          f"{'-10 dB BW':>10}")
    cases = [(dim.BOARD_T, PATCH, "rigid stack"),
             (dim.ANTENNA_SUBSTRATE_T, PATCH, "antenna islands, as specified")]
    if "--sweep" in a:
        cases += [(h, PATCH, "thinner board") for h in (0.4, 0.25, 0.127)]
        cases += [(0.127, l_ref, "thin + resized")]
    rows = []
    for h, w, label in cases:
        f, s11 = simulate(h, patch_mm=w, cell=cell, steps=steps)
        f_res, depth, bw = summarise(f, s11)
        rows.append((h, w, f_res, depth, bw, label))
        print(f"  {h:>8.3f} mm  {w:>5.2f} mm  {f_res:>6.1f} GHz  "
              f"{depth:>6.1f} dB  {bw:>7.1f} GHz   {label}")
        np.savetxt(os.path.join(HERE, f"s11_h{h:.3f}_w{w:.2f}.csv"),
                   np.column_stack([f, s11]), delimiter=",",
                   header="f_Hz,S11_dB", comments="")

    print()
    h, w, f_res, depth, bw, _ = rows[1]
    if depth > -10.0 or abs(f_res - 60.0) > 3.0:
        print(f"  ⛔ The specified antenna stackup ({h} mm) does not work: "
              f"{depth:.1f} dB at {f_res:.1f} GHz.")
    else:
        print(f"  ⭐ The specified antenna stackup ({h} mm) matches at "
              f"{f_res:.1f} GHz, {depth:.1f} dB, {bw:.1f} GHz of bandwidth.")
        print(f"     On the full {rows[0][0]} mm rigid stack the same patch "
              f"gives {rows[0][3]:.1f} dB at {rows[0][2]:.1f} GHz — which is "
              "why the")
        print("     islands are specified thinner.")


if __name__ == "__main__":
    main()
