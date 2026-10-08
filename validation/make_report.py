"""Assemble validation/REPORT.md from the result files.

    python validation/make_report.py

Inputs: results/B*.json (run_benchmarks.py), results/heater_block/summary.json
(cases/heater_block.py), silent/results.md (run_silent_audit.py) and the B1
table from reference.py.
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RES = HERE / "results"
sys.path.insert(0, str(HERE))


def load(name):
    p = RES / name
    return json.loads(p.read_text()) if p.exists() else None


def fmt(v, nd=2):
    return f"{v:.{nd}f}" if isinstance(v, (int, float)) else str(v)


def accuracy_section():
    rows = ["| ID | What it checks | Result | Verdict |", "|---|---|---|---|"]
    desc = {
        "B2": "Lumped copper block: heat-load units and total power (S20), film units, transient timing",
        "B3": "1-D conduction through an FR4 slab: conductivity and heat-flux units",
        "B4": "Board with a 2 W package vs an independent 3-D gmsh/Elmer model; mesh convergence (B5)",
        "B6": "Same board solved by CalculiX (project flow) and by Elmer (independent gmsh mesh)",
        "B9": "Surface-to-surface radiation between parallel plates vs exact view factor",
    }
    for bid in ("B2", "B3", "B4", "B6", "B9"):
        d = load(f"{bid}.json")
        if d is None:
            rows.append(f"| {bid} | {desc[bid]} | not run | – |")
            continue
        v = "PASS" if d.get("pass") else "FAIL"
        rows.append(f"| {bid} | {desc[bid]} | {d.get('summary', '')} | **{v}** |")
    out = "\n".join(rows)
    b2 = load("B2.json")
    if b2 and "meshes" in b2:
        out += "\n\n**B2 per mesh**\n\n| mesh [mm] | nodes | ΔT_ss error | τ error | worst point on curve |\n|---|---|---|---|---|\n"
        for m in b2["meshes"]:
            out += (f"| {m['mesh_mm']} | {m['nodes']} | {m['dT_ss_err_%']:+.2f} % | "
                    f"{m['tau_err_%']:+.2f} % | {m['max_curve_err_%']:.2f} % |\n")
    b4 = load("B4.json")
    if b4 and "meshes" in b4:
        out += "\n**B4/B5 per mesh**\n\n| mesh [mm] | nodes | ΔT max [K] | still rising at end [K] |\n|---|---|---|---|\n"
        for m in b4["meshes"]:
            out += f"| {m['mesh_mm']} | {m['nodes']} | {m['dTmax']:.2f} | {m['still_rising_K']:.3f} |\n"
        b5 = b4.get("B5", {})
        out += (f"\nGCI (fine mesh) {fmt(b5.get('GCI_fine_%'))} %, observed order "
                f"{fmt(b5.get('observed_order'))}, extrapolated ΔT max "
                f"{fmt(b5.get('extrapolated_dTmax'))} K; independent 3-D Elmer reference "
                f"{fmt(b4.get('reference_elmer_dTmax'))} K. A 2-D thin-fin hand model gives "
                f"{fmt(b4.get('fin_2d_estimate_dTmax'))} K: it ignores through-thickness resistance "
                f"under the package, so it is not a valid reference for a bare-FR4 board.\n")
    b6 = load("B6.json")
    if b6 and "meshes" in b6:
        out += "\n**B6 per mesh**\n\n| mesh [mm] | CalculiX ΔT max | Elmer ΔT max | difference |\n|---|---|---|---|\n"
        for m in b6["meshes"]:
            out += f"| {m['mesh_mm']} | {m['ccx_dTmax']:.2f} K | {m['elmer_dTmax']:.2f} K | {m['diff_%']:+.2f} % |\n"
    return out


def toolchain_findings():
    rows = ["| ID | Finding | Status | Evidence |", "|---|---|---|---|"]
    b2, b4 = load("B2.json") or {}, load("B4.json") or {}
    s6 = b2.get("S6_output_frequency_2")
    if s6:
        ev = s6.get("error") or f"worst curve error {fmt(s6.get('max_curve_err_%'))} %"
        rows.append(f"| S6 | Output every 2nd increment breaks `tpost csv` time/temperature pairing | {s6['status']} | {ev} |")
    s5 = b2.get("S5_stale_vtk")
    if s5:
        ev = s5.get("error") or f"CSV reaches t={fmt(s5.get('max_time_in_csv'))} s for a 1000 s run"
        rows.append(f"| S5 | Re-running into a folder with old `.vtk` files | {s5['status']} | {ev} |")
    if b2.get("meshes"):
        worst = max(abs(m["dT_ss_err_%"]) for m in b2["meshes"])
        rows.append(f"| S20 | Heat load total power vs mesh density | "
                    f"{'NOT REPRODUCED' if worst < 1 else 'CONFIRMED'} | total power correct on 3 meshes "
                    f"(worst {worst:.2f} %); FreeCAD splits it equally per node, not by area |")
    tc = load("toolchain_checks.json") or {}
    s21 = b4.get("S21_unfused")
    if s21:
        ev = s21.get("error") or (f"package ΔT {fmt(s21.get('dTmax'))} K vs {fmt(b4['B4']['fine_dTmax'])} K fused; "
                                  f"any warning: {s21.get('warned')}")
        bo = tc.get("S21_board_only")
        if bo:
            ev += (f"; the board stays at {bo['board_dTmax']:.2f} K rise while the isolated package reaches "
                   f"{bo['package_dTmean']:.0f} K: no heat crosses the interface")
        rows.append(f"| S21 | Parts meshed as a plain compound (not fused) | {s21['status']} | {ev} |")
    s4 = tc.get("S4")
    if s4:
        rows.append(f"| S4 | Mesh object not named `FEMMeshGmsh` | {s4['status']} | tpre wrote {s4['inp_written']} (exit {s4['tpre_rc']}); "
                    f"README's `ccx FEMMeshGmsh` exits {s4['readme_ccx_rc']}: `{s4['readme_ccx_msg'].strip()}`. Loud by hand, hidden inside find_coef.sh (S2) |")
    s24 = b4.get("S24_box_face_refs")
    if s24:
        rows.append(f"| S24 | Convection referenced on the original board face also cools the hidden board/package interface | "
                    f"{s24['status']} | ΔT max {s24['dTmax_box_refs']:.2f} K vs {s24['dTmax_split_refs']:.2f} K ({s24['diff_%']:+.1f} %) |")
    return "\n".join(rows)


def heater_section():
    s = load("heater_block/summary.json")
    if not s:
        return "_not run_"
    p = s["params"]
    lines = [
        f"Heater {p['heater_size']} mm held at {p['heater_C']} °C (ε {p['heater_emissivity']}), "
        f"{p['gap']} mm still-air gap, {p['block_material']} block {p['block_size']} mm, "
        f"ambient {p['ambient_C']} °C, {p['time_end_s'] / 3600:.0f} h simulated. Placeholder values.",
        "",
        "| Block finish | ε | Final block mean | Spread on block | 63 % of rise | 95 % of rise | Still rising at end | Heat into block |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for lbl, v in s["variants"].items():
        lines.append(
            f"| {lbl} | {v['emissivity']} | {v['final_block_mean_C']:.2f} °C | {v['face_spread_K']:.3f} K | "
            f"{v['t63_min']:.0f} min | {v['t95_min']:.0f} min | {v['end_slope_K_per_h']:.3f} K/h | "
            f"~{v['approx_heat_into_block_W']:.3f} W |")
    mc = s.get("mesh_check", {})
    lines += ["", f"Mesh check (anodised): rise {fmt(mc.get('coarse_rise'))} K at {mc.get('coarse_mm')} mm vs "
              f"{fmt(mc.get('fine_rise'))} K at {mc.get('fine_mm')} mm ({fmt(mc.get('diff_%'))} %).",
              "", "Direct gas conduction across the gap (not modelled, hand estimate): " +
              ", ".join(f"{k} ~{v:.3f} W" for k, v in s.get("gas_conduction_estimate_W", {}).items()),
              "", "![warm-up](results/heater_block/warmup.png)", "",
              "![face map](results/heater_block/face_map.png)"]
    return "\n".join(lines)


def oven_section():
    s = load("oven/summary.json")
    if not s:
        return "_not run_"
    a, b, c = s["assumptions"], s["baseline"], s["checks"]
    lines = [
        f"Bare {a['block_in']} in aluminium block (ε {a['block_eps']}), {a['gap_in']:g} in from a "
        f"{a['heater_in']} in plate element held at {a['setpoint_F']:g} °F by PID, inside a closed "
        f"{a['box_in']} in box with {a['insulation_in']:g} in mineral wool, room {a['room_F']:g} °F, no fan. "
        "Heater size, box size and insulation are assumptions.",
        "",
        f"Model checks: view-factor integrator vs exact {c['view_factor']['err_%']:.1e} %; lumped model vs the "
        "validated 3-D FEM case: " + ", ".join(
            f"{k} rise {v['diff_%']:+.1f} %, t63 {v['lumped_t63_min']:.0f} vs {v['fem_t63_min']:.0f} min"
            for k, v in c["vs_fem"].items()) + ".",
        "",
        "| Case | Block final | Box air final | Heater power | 63 % | 95 % | Within 5 °F of 200 °F |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in s["sensitivity"]:
        w5 = f"{r['hours_to_within_5F']:.1f} h" if r["hours_to_within_5F"] else "never"
        lines.append(f"| {r['case']} | {r['block_final_F']:.0f} °F | {r['air_final_F']:.0f} °F | "
                     f"{r['heater_W']:.0f} W | {r['t63_h']:.1f} h | {r['t95_h']:.1f} h | {w5} |")
    lines += ["", "![enclosure warm-up](results/oven/block_warmup.png)"]
    return "\n".join(lines)


def main():
    import reference

    silent = (HERE / "silent" / "results.md").read_text(encoding="utf-8")
    silent_table = silent[silent.index("| ID |"):]
    summary_md = (HERE / "SUMMARY.md").read_text(encoding="utf-8") if (HERE / "SUMMARY.md").exists() else ""
    report = f"""# Validation report: thermal-simulation-scripts

Generated by `python validation/make_report.py` from the files in `validation/results/`.
Plan: see the approved validation plan; setup: [SETUP.md](SETUP.md); friction: [friction_log.md](friction_log.md).

{summary_md}

## 1. Accuracy (code verification)

{accuracy_section()}

### B1: film coefficient calculator vs textbook (bias, not pass/fail)

{reference._b1_table()}

## 2. Silent failures

### Found by the audit script (FreeCAD stubbed, real bash/Python)

Rows marked NEEDS TOOLCHAIN are answered in the next table (S19 needs Blender/PCBooth and was not run).

{silent_table}

### Found with the real toolchain

{toolchain_findings()}

## 3. Case study: heater, still air, aluminium block (3-D FEM, open air)

{heater_section()}

## 4. Case study: 3x2x2 in block in a closed box with a 200 °F PID element (lumped model)

{oven_section()}
"""
    (HERE / "REPORT.md").write_text(report, encoding="utf-8")
    print(f"wrote {HERE / 'REPORT.md'}")


if __name__ == "__main__":
    main()
