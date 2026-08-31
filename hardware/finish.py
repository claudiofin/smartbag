#!/usr/bin/env python3
"""Close the last few connections by hand, with DRC as the judge.

⛔ FREEROUTING RECOMMENDS THIS AND THEN CANNOT DO IT. When the autorouter stops
improving it says so: "it is very likely that autorouter can't improve the
result much further. It is recommended to stop it and finish the board
manually." Manually is fine — but a person drawing four tracks and eyeballing
them is exactly the step this project has avoided everywhere else.

⭐ SO THE CANDIDATES ARE DRAWN BLIND AND DRC DECIDES. For each unconnected pad
this tries a handful of shapes — straight, and both L-bends, on the pad's own
layer and through a via to another — applies one, runs a full DRC, and keeps it
only if the board came out with FEWER unconnected pads and NO new violations.
Anything else is reverted. Nothing here can make the board worse; the worst it
can do is fail to help.

⚠️ It is deliberately dumb. It does not route around obstacles, it does not
rip up, it tries seven shapes and reports what stuck. The clever version of this
is the autorouter that already ran.

Usage:
  <kicad-python> hardware/finish.py hardware/smartbag_core.kicad_pcb
"""
import os
import re
import subprocess
import sys
import tempfile

import pcbnew

W = pcbnew.FromMM(0.1)


def drc(path):
    """(violations, unconnected) from a real DRC run."""
    with tempfile.NamedTemporaryFile(suffix=".rpt", delete=False) as f:
        rpt = f.name
    subprocess.run(["kicad-cli", "pcb", "drc", "--schematic-parity",
                    "--severity-error", "-o", rpt, path],
                   capture_output=True)
    t = open(rpt).read()
    os.unlink(rpt)
    v = re.search(r"Found (\d+) DRC violations", t)
    u = re.search(r"Found (\d+) unconnected pads", t)
    return (int(v.group(1)) if v else 999, int(u.group(1)) if u else 999)


def unconnected_pairs(path):
    """[(pad_xy, target_xy, netcode, layer)] straight out of the DRC report."""
    with tempfile.NamedTemporaryFile(suffix=".rpt", delete=False) as f:
        rpt = f.name
    subprocess.run(["kicad-cli", "pcb", "drc", "--schematic-parity",
                    "--severity-all", "-o", rpt, path], capture_output=True)
    lines = open(rpt).read().splitlines()
    os.unlink(rpt)
    out = []
    for i, l in enumerate(lines):
        if not l.startswith("[unconnected_items]"):
            continue
        a, b = lines[i + 2], lines[i + 3]
        # ⚠️ EITHER ORDER. DRC prints the two ends of an unconnected pair in
        # whatever order it found them, and the first version of this only
        # looked for the pad on the first line — so it silently skipped half
        # the work and reported the rest as done.
        #
        # ⚠️ Only pad-to-copper pairs. A zone island short of a via is a
        # stitching problem and hardware/stitch.py owns it.
        if "Zone" in a or "Zone" in b:
            continue
        pat = r"@\(([\d.]+) mm, ([\d.]+) mm\).*Pad \S+ \[([^\]]+)\]"
        pa, pb = re.search(pat, a), re.search(pat, b)
        pad, other = (pa, b) if pa else (pb, a)
        if not pad:
            continue
        po = re.search(r"@\(([\d.]+) mm, ([\d.]+) mm\)", other)
        if po:
            out.append(((float(pad.group(1)), float(pad.group(2))),
                        (float(po.group(1)), float(po.group(2))),
                        pad.group(3)))
    return out


def add_track(board, a, b, layer, net):
    t = pcbnew.PCB_TRACK(board)
    t.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(a[0]), pcbnew.FromMM(a[1])))
    t.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(b[0]), pcbnew.FromMM(b[1])))
    t.SetWidth(W)
    t.SetLayer(layer)
    t.SetNetCode(net)
    board.Add(t)
    return t


def add_via(board, p, net):
    v = pcbnew.PCB_VIA(board)
    v.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(p[0]), pcbnew.FromMM(p[1])))
    v.SetWidth(pcbnew.FromMM(0.25))
    v.SetDrill(pcbnew.FromMM(0.1))
    v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
    v.SetNetCode(net)
    board.Add(v)
    return v


def candidates(board, a, b, net):
    """Shapes to try, each a list of items already added to the board."""
    corner1 = (b[0], a[1])
    corner2 = (a[0], b[1])
    out = []
    for layer in (pcbnew.F_Cu, pcbnew.In2_Cu, pcbnew.B_Cu):
        for path in ([a, b], [a, corner1, b], [a, corner2, b]):
            items = []
            if layer != pcbnew.F_Cu:
                items.append(add_via(board, a, net))
                items.append(add_via(board, b, net))
            for p, q in zip(path, path[1:]):
                items.append(add_track(board, p, q, layer, net))
            out.append(items)
            yield items
            for it in items:
                board.Remove(it)


def main(path):
    base_v, base_u = drc(path)
    print(f"start: {base_v} violations, {base_u} unconnected")
    fixed = 0
    import shutil
    # ⛔ A PRISTINE COPY, KEPT ON DISK. The first version reverted by reloading
    # the board from `path` — which by then contained the failed candidate it
    # was trying to undo. Three rejected tracks accumulated into the file and
    # the tool reported the damage as the starting state.
    pristine = path + ".finish-backup"
    shutil.copy(path, pristine)

    for a, b, netname in unconnected_pairs(path):
        board = pcbnew.LoadBoard(path)
        net = board.GetNetcodeFromNetname(netname)
        if net == 0:
            continue
        kept = False
        for _items in candidates(board, a, b, net):
            board.Save(path)
            v, u = drc(path)
            if v <= base_v and u < base_u:
                print(f"  {netname}: joined ({v} violations, {u} unconnected)")
                base_v, base_u = v, u
                fixed += 1
                kept = True
                break
            shutil.copy(pristine, path)      # revert, from the copy
            board = pcbnew.LoadBoard(path)
        if kept:
            shutil.copy(path, pristine)      # the new baseline
        else:
            shutil.copy(pristine, path)
            print(f"  {netname}: no shape fits — left for a human")
    os.unlink(pristine)
    print(f"done: {base_v} violations, {base_u} unconnected, {fixed} joined")


if __name__ == "__main__":
    main(sys.argv[1])
