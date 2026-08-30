#!/usr/bin/env python3
"""Generate the symbol library, the schematic and the project file, from netlist.py.

⛔ THE SCHEMATIC IS GENERATED, not drawn. The board already was, and a hand-drawn
schematic next to a generated board is the classic way to end up with two
descriptions of one circuit that quietly disagree. Both come out of
`hardware/netlist.py`, so parity is a property of the build rather than
something to remember.

⭐ WIRED BY NET LABELS, not by geometry. Every pin gets a 5.08 mm stub ending in
a global label carrying the net name. Nothing has to be routed on the sheet, no
wire has to find its way around a symbol, and connectivity cannot depend on two
line segments happening to touch. It is a legitimate schematic style for a dense
board, and for a generated one it is the only sane choice.

⚠️ EVERYTHING SITS ON THE 1.27 mm GRID. Off-grid endpoints are an ERC warning
(`endpoint_off_grid`) and, worse, silently break connections in KiCad's editor.
The first draft placed symbols at round millimetres — 100.0 mm is not a multiple
of 1.27 — and every pin in the design came out off-grid.

Usage:  python3 hardware/generate_schematic.py
"""
import json
import os
import sys
import uuid as _uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import netlist as nl            # noqa: E402

NAME = "smartbag_core"
SCH = os.path.join(HERE, f"{NAME}.kicad_sch")
SYM = os.path.join(HERE, "smartbag.kicad_sym")
PRO = os.path.join(HERE, f"{NAME}.kicad_pro")
TABLE = os.path.join(HERE, "sym-lib-table")

G = 1.27                 # KiCad's connection grid
PITCH = 2 * G            # 2.54 mm between pins
STUB = 4 * G             # length of the wire from pin to label
ROOT = None              # sheet uuid, set in build()


def uid():
    return str(_uuid.uuid4())


def snap(v):
    return round(v / G) * G


def _sides(pins):
    """Split pins into (left, right). First half down the left, rest down the
    right — predictable beats pretty for a generated sheet."""
    half = (len(pins) + 1) // 2
    return pins[:half], pins[half:]


def symbol_def(name, pins):
    """One symbol: a box with the pins of the part class it stands for."""
    left, right = _sides(pins)
    rows = max(len(left), len(right))
    half_h = (rows - 1) * PITCH / 2 + PITCH
    half_w = 8 * G
    body = [f'\t(symbol "smartbag:{name}"',
            '\t\t(pin_names (offset 0.508)) (exclude_from_sim no)',
            '\t\t(in_bom yes) (on_board yes)',
            f'\t\t(property "Reference" "U" (at 0 {half_h + PITCH:.2f} 0)'
            ' (effects (font (size 1.27 1.27))))',
            f'\t\t(property "Value" "{name}" (at 0 {-half_h - PITCH:.2f} 0)'
            ' (effects (font (size 1.27 1.27))))',
            '\t\t(property "Footprint" "" (at 0 0 0)'
            ' (effects (font (size 1.27 1.27)) (hide yes)))',
            '\t\t(property "Datasheet" "" (at 0 0 0)'
            ' (effects (font (size 1.27 1.27)) (hide yes)))',
            f'\t\t(symbol "{name}_0_1"',
            f'\t\t\t(rectangle (start {-half_w:.2f} {half_h:.2f})'
            f' (end {half_w:.2f} {-half_h:.2f})',
            '\t\t\t\t(stroke (width 0.254) (type default))'
            ' (fill (type background))))',
            f'\t\t(symbol "{name}_1_1"']
    for column, side in ((left, "L"), (right, "R")):
        for i, (number, pname, etype, _net) in enumerate(column):
            y = half_h - PITCH - i * PITCH
            x = -half_w - PITCH if side == "L" else half_w + PITCH
            ang = 0 if side == "L" else 180
            body.append(
                f'\t\t\t(pin {etype} line (at {x:.2f} {y:.2f} {ang})'
                f' (length {PITCH:.2f})'
                f' (name "{pname}" (effects (font (size 1.27 1.27))))'
                f' (number "{number}" (effects (font (size 1.27 1.27)))))')
    body.append('\t\t))')
    return "\n".join(body) + "\n"


PWR_FLAG_DEF = '''\t(symbol "smartbag:PWR_FLAG"
\t\t(power) (pin_numbers (hide yes)) (pin_names (offset 0) (hide yes))
\t\t(exclude_from_sim no) (in_bom no) (on_board yes)
\t\t(property "Reference" "#FLG" (at 0 2.54 0)
\t\t\t(effects (font (size 1.27 1.27)) (hide yes)))
\t\t(property "Value" "PWR_FLAG" (at 0 3.81 0)
\t\t\t(effects (font (size 1.27 1.27))))
\t\t(property "Footprint" "" (at 0 0 0)
\t\t\t(effects (font (size 1.27 1.27)) (hide yes)))
\t\t(symbol "PWR_FLAG_0_0"
\t\t\t(pin power_out line (at 0 0 90) (length 0)
\t\t\t\t(name "pwr" (effects (font (size 1.27 1.27))))
\t\t\t\t(number "1" (effects (font (size 1.27 1.27))))))
\t\t(symbol "PWR_FLAG_0_1"
\t\t\t(polyline (pts (xy 0 0) (xy 0 1.27) (xy -1.016 1.905) (xy 0 2.54)
\t\t\t\t(xy 1.016 1.905) (xy 0 1.27))
\t\t\t\t(stroke (width 0.254) (type default)) (fill (type none)))))
'''


def all_symbol_defs():
    out = {name: symbol_def(name, pins) for name, pins in nl.symbols().items()}
    out["PWR_FLAG"] = PWR_FLAG_DEF
    return out


def stub_and_label(x, y, direction, net):
    """A wire from a pin out to a global label carrying the net name."""
    ex = x + direction * STUB
    return [
        f'\t(wire (pts (xy {x:.2f} {y:.2f}) (xy {ex:.2f} {y:.2f}))'
        f' (stroke (width 0) (type default)) (uuid "{uid()}"))',
        f'\t(global_label "{net}" (shape bidirectional)'
        f' (at {ex:.2f} {y:.2f} {0 if direction > 0 else 180})'
        ' (fields_autoplaced yes)'
        f' (effects (font (size 1.27 1.27))'
        f' (justify {"left" if direction > 0 else "right"}))'
        f' (uuid "{uid()}"))']


def place_part(ref, value, sym, lib, fp, pins, x, y):
    left, right = _sides(pins)
    rows = max(len(left), len(right))
    half_h = (rows - 1) * PITCH / 2 + PITCH
    half_w = 8 * G
    out = [f'''\t(symbol (lib_id "smartbag:{sym}") (at {x:.2f} {y:.2f} 0) (unit 1)
\t\t(exclude_from_sim no) (in_bom yes) (on_board yes) (dnp no)
\t\t(uuid "{uid()}")
\t\t(property "Reference" "{ref}" (at {x:.2f} {y - half_h - PITCH:.2f} 0)
\t\t\t(effects (font (size 1.27 1.27))))
\t\t(property "Value" "{value}" (at {x:.2f} {y + half_h + PITCH:.2f} 0)
\t\t\t(effects (font (size 1.27 1.27))))
\t\t(property "Footprint" "{lib}:{fp}" (at {x:.2f} {y:.2f} 0)
\t\t\t(effects (font (size 1.27 1.27)) (hide yes)))
\t\t(instances (project "{NAME}" (path "/{ROOT}" (reference "{ref}") (unit 1))))
\t)''']
    # ⚠️ Symbol y grows downward on the sheet but upward inside the symbol
    # definition, so the pin at symbol-local +y lands at sheet y - offset.
    for column, side in ((left, -1), (right, 1)):
        for i, (_number, _pname, _etype, net) in enumerate(column):
            local_y = half_h - PITCH - i * PITCH
            px = x + side * (half_w + PITCH)
            py = y - local_y
            out += stub_and_label(px, py, side, net)
    return out, half_h


def place_flag(net, x, y, index):
    out = [f'''\t(symbol (lib_id "smartbag:PWR_FLAG") (at {x:.2f} {y:.2f} 0) (unit 1)
\t\t(exclude_from_sim no) (in_bom no) (on_board yes) (dnp no)
\t\t(uuid "{uid()}")
\t\t(property "Reference" "#FLG{index}" (at {x:.2f} {y + PITCH:.2f} 0)
\t\t\t(effects (font (size 1.27 1.27)) (hide yes)))
\t\t(property "Value" "PWR_FLAG" (at {x:.2f} {y - PITCH:.2f} 0)
\t\t\t(effects (font (size 1.27 1.27))))
\t\t(instances (project "{NAME}" (path "/{ROOT}" (reference "#FLG{index}") (unit 1))))
\t)''']
    out += stub_and_label(x, y, 1, net)
    return out


def build():
    global ROOT
    ROOT = uid()
    defs = all_symbol_defs()
    out = [f'(kicad_sch\n\t(version 20250114)\n\t(generator "smartbag")'
           f'\n\t(generator_version "10.0")\n\t(uuid "{ROOT}")\n\t(paper "A0")'
           '\n\t(lib_symbols']
    out += [defs[k] for k in sorted(defs)]
    out.append('\t)')

    # Simple column flow. Wide columns because every pin carries a label.
    col_pitch, x0, y0, y_max = 88 * G, 40 * G, 40 * G, 620 * G
    x, y = x0, y0
    for ref, value, sym, lib, fp, pins, _bx, _by in nl.PARTS:
        rows = max(len(_sides(pins)[0]), len(_sides(pins)[1]))
        height = (rows - 1) * PITCH + 4 * PITCH
        if y + height > y_max:
            x, y = x + col_pitch, y0
        block, half_h = place_part(ref, value, sym, lib, fp, pins,
                                   snap(x), snap(y + half_of(rows)))
        out += block
        y += height + 6 * PITCH
    x += col_pitch
    for i, net in enumerate(nl.POWER_FLAGS):
        out += place_flag(net, snap(x), snap(y0 + i * 8 * PITCH), i)

    out.append('\t(sheet_instances (path "/" (page "1")))')
    out.append(')')
    return "\n".join(out) + "\n"


def half_of(rows):
    return (rows - 1) * PITCH / 2 + PITCH


def write_library():
    defs = all_symbol_defs()
    body = "".join(defs[k].replace('(symbol "smartbag:', '(symbol "')
                   for k in sorted(defs))
    with open(SYM, "w") as f:
        f.write('(kicad_symbol_lib\n\t(version 20241209)\n'
                '\t(generator "smartbag")\n' + body + ')\n')


def write_project():
    """⚠️ The project file is not optional here. Without it kicad-cli does not
    read sym-lib-table, cannot resolve the generated library, and every symbol
    in the design comes back as a `lib_symbol_issues` warning."""
    # ⛔ THE DESIGN RULES ARE PART OF THE DESIGN. Left at KiCad's defaults, DRC
    # judged this board against a 0.2 mm/0.2 mm generic process and returned 108
    # track-width and 112 via/drill violations that say nothing about the layout
    # — only that the file never declared what it is. A 2-layer polyimide flex
    # carrying 60 GHz microstrip is an advanced process: 0.1 mm lines and spaces,
    # 0.3/0.15 vias. Stating that is not loosening the rules, it is supplying
    # the ones that apply.
    pro = {
        "board": {"design_settings": {
            "rules": {
                "min_clearance": 0.1,
                "min_track_width": 0.1,
                "min_via_diameter": 0.3,
                "min_through_hole_diameter": 0.15,
                "min_hole_clearance": 0.1,
                "min_hole_to_hole": 0.15,
                "min_copper_edge_clearance": 0.15,
                "min_silk_clearance": 0.0,
                "min_text_height": 0.4,
                "min_text_thickness": 0.05,
                "min_resolved_spokes": 1,
                "min_connection": 0.0,
                # ⚠️ 0.05 mm of mask web, not 0. Fine-pitch QFN and 0402 land
                # patterns genuinely cannot hold a wider web, and every fab that
                # takes 0.1 mm lines also takes a 0.05 mm web — but setting this
                # to zero would be switching the check off rather than declaring
                # the process.
                "solder_mask_min_width": 0.05,
                "solder_mask_to_copper_clearance": 0.0,
            },
            "track_width_list": [0.0, 0.1, 0.15, 0.3, 0.58, 1.4],
            # ⛔ 0.35, not 0.3. min_via_annular_width above is 0.1, and a 0.3 mm
            # pad on a 0.15 mm drill leaves 0.075 — the file was offering a via
            # size its own rules forbid, and nothing caught it until an
            # autorouter was handed the rules and asked to use them.
            "via_dimensions": [{"diameter": 0.0, "drill": 0.0},
                               {"diameter": 0.35, "drill": 0.15}],
            "defaults": {
                "board_outline_line_width": 0.1,
                "copper_line_width": 0.15,
                "silk_line_width": 0.12,
                "silk_text_size_h": 0.8, "silk_text_size_v": 0.8,
                "silk_text_thickness": 0.12,
            },
        }},
        # ⛔ THE NETCLASS IS NOT THE SAME THING AS THE MINIMUMS, and leaving it
        # out cost a routing attempt. `rules` above says what the process can
        # do; a netclass says what the design *uses*, and with none declared
        # KiCad supplies its generic 0.2 mm/0.2 mm/0.6 mm default. DRC never
        # complained — 0.2 is comfortably above a 0.1 minimum — so the gap was
        # invisible until the board was exported to a router, which routes to
        # the netclass and found a 0.4 mm-pitch QFN unescapable at 0.2 mm.
        "net_settings": {
            "classes": [
                {
                    "name": "Default",
                    "clearance": 0.1, "track_width": 0.1,
                    "via_diameter": 0.35, "via_drill": 0.15,
                    "microvia_diameter": 0.2, "microvia_drill": 0.1,
                    "diff_pair_width": 0.1, "diff_pair_gap": 0.15,
                    "diff_pair_via_gap": 0.15,
                    "priority": 2147483647,
                    "pcb_color": "rgba(0, 0, 0, 0.000)",
                    "schematic_color": "rgba(0, 0, 0, 0.000)",
                    "line_style": 0, "bus_width": 12, "wire_width": 6,
                },
                {
                    # ⚠️ The rails carry a 1 A charge current and a camera burst.
                    # 0.1 mm of 1 oz copper is about 0.5 A; three times the
                    # width is not decoration.
                    "name": "Power",
                    "clearance": 0.15, "track_width": 0.3,
                    "via_diameter": 0.45, "via_drill": 0.25,
                    "microvia_diameter": 0.2, "microvia_drill": 0.1,
                    "diff_pair_width": 0.1, "diff_pair_gap": 0.15,
                    "diff_pair_via_gap": 0.15,
                    "priority": 2,
                    "pcb_color": "rgba(0, 0, 0, 0.000)",
                    "schematic_color": "rgba(0, 0, 0, 0.000)",
                    "line_style": 0, "bus_width": 12, "wire_width": 6,
                },
                # ⛔ TWO RF CLASSES, NOT ONE, and the first version got this
                # wrong. 50 ohms is not a width, it is a width *on a substrate*:
                # rf/feed_loss.py puts it at 0.581 mm on the 0.25 mm antenna
                # islands and 1.395 mm on the 0.6 mm rigid stack. One class
                # applied the 60 GHz island number to a 2.4 GHz trace that never
                # goes near an island — a trace that would have been built at
                # less than half its correct width, and matched nothing.
                {
                    # ⚠️ Declaring this does not make the 60 GHz feeds
                    # buildable — see the RF section — it stops a router from
                    # silently drawing them at signal width, which would look
                    # like a solved problem.
                    "name": "RF_60G",
                    "clearance": 0.2, "track_width": 0.58,
                    "via_diameter": 0.45, "via_drill": 0.25,
                    "microvia_diameter": 0.2, "microvia_drill": 0.1,
                    "diff_pair_width": 0.58, "diff_pair_gap": 0.2,
                    "diff_pair_via_gap": 0.2,
                    "priority": 1,
                    "pcb_color": "rgba(0, 0, 0, 0.000)",
                    "schematic_color": "rgba(0, 0, 0, 0.000)",
                    "line_style": 0, "bus_width": 12, "wire_width": 6,
                },
                {
                    # ⛔ 0.2, not 0.25, and DRC had to say so. A netclass
                    # clearance applies at the *pad* as well as along the trace,
                    # and this net lands on a 0.4 mm-pitch QFN where pad-to-pad
                    # is 0.2 mm by construction. Asking for 0.25 made the
                    # package itself illegal — three violations that were not
                    # about the layout at all. Wider RF clearance has to come
                    # from a custom rule that exempts pads, not from the class.
                    "name": "RF_24G",
                    "clearance": 0.2, "track_width": 1.4,
                    "via_diameter": 0.45, "via_drill": 0.25,
                    "microvia_diameter": 0.2, "microvia_drill": 0.1,
                    "diff_pair_width": 1.4, "diff_pair_gap": 0.25,
                    "diff_pair_via_gap": 0.25,
                    "priority": 1,
                    "pcb_color": "rgba(0, 0, 0, 0.000)",
                    "schematic_color": "rgba(0, 0, 0, 0.000)",
                    "line_style": 0, "bus_width": 12, "wire_width": 6,
                },
            ],
            "meta": {"version": 4},
            "net_colors": None,
            "netclass_assignments": None,
            "netclass_patterns": (
                [{"netclass": "Power", "pattern": n}
                 for n in ("VBAT", "VQI", "VDD_3V3", "VDD_1V8", "SW1", "SW2")]
                + [{"netclass": "RF_60G", "pattern": n}
                   for n in ("ANT_A1", "ANT_A2")]
                + [{"netclass": "RF_24G", "pattern": "BLE_ANT"}]
            ),
        },
        "libraries": {"pinned_footprint_libs": [], "pinned_symbol_libs": []},
        "meta": {"filename": f"{NAME}.kicad_pro", "version": 3},
        "schematic": {"legacy_lib_dir": "", "legacy_lib_list": []},
        "sheets": [], "text_variables": {},
    }
    with open(PRO, "w") as f:
        json.dump(pro, f, indent=2)
    with open(TABLE, "w") as f:
        f.write('(sym_lib_table\n\t(version 7)\n\t(lib (name "smartbag")'
                '(type "KiCad")(uri "${KIPRJMOD}/smartbag.kicad_sym")'
                '(options "")(descr "SmartBag part classes"))\n)\n')


if __name__ == "__main__":
    write_library()
    write_project()
    with open(SCH, "w") as f:
        f.write(build())
    n = nl.nets()
    print(f"OK  {SYM}  ({len(all_symbol_defs())} symbols)")
    print(f"OK  {SCH}  ({len(nl.PARTS)} parts, {len(n)} nets)")
