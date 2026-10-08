"""Case study: fixed-temperature heater radiating across still air to an
aluminium block.

    python validation/cases/heater_block.py

Geometry (mm, z up = against gravity), placeholder values; edit PARAMS.

      heater          gap          block
     [5x25x25]  <--- 20 mm --->  [20x50x50]
     centred on the block's 50x50 face

Physics included
  * conduction inside both parts
  * surface-to-surface (cavity) radiation between all faces of both parts with
    CalculiX view factors; radiation not intercepted goes to the surroundings
    (FreeCAD only writes radiation-to-ambient, so the .inp is patched)
  * natural convection from every block face to still ambient air, film
    coefficients from the project's calculator, iterated on the block's rise

Not included (cannot be with this toolchain): air flow between the parts.
The heater's buoyant plume rises past the block instead of hitting it in this
side-by-side layout, and direct gas conduction across the gap is estimated
by hand below.
"""

import json
import os
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "validation" / "benchmarks"))
sys.path.insert(0, str(ROOT / "validation"))
sys.path.insert(0, str(ROOT / "src"))

import fcmodel  # noqa: E402
import pipeline  # noqa: E402
import reference  # noqa: E402
from preprocessing.calculate_coef import calculate_film_coefficient  # noqa: E402

PARAMS = {
    "ambient_C": 25.0,
    "heater_C": 150.0,
    "heater_size": (5.0, 25.0, 25.0),  # x (thickness), y, z
    "heater_emissivity": 0.9,
    "gap": 20.0,
    "block_size": (20.0, 50.0, 50.0),  # x (thickness), y, z
    "block_material": "Aluminium6061",
    "block_emissivities": {"bare": 0.09, "anodised": 0.85},
    "rise_guess_K": {"bare": 1.0, "anodised": 4.0},  # hand estimates, refined once
    "time_end_s": 6 * 3600.0,
    "max_step_s": 300.0,
    "mesh_mm": 3.0,
    "mesh_check_mm": 2.5,
}

WORK = Path(os.environ.get("TSS_WORK", Path.home() / "tss-work")) / "heater_block"
OUT = ROOT / "validation" / "results" / "heater_block"


def layout(p):
    hx, hy, hz = p["heater_size"]
    bx, by, bz = p["block_size"]
    block_pos = (hx + p["gap"], 0.0, 0.0)
    heater_pos = (0.0, (by - hy) / 2, (bz - hz) / 2)
    return heater_pos, block_pos


def film_coefficients(p, rise):
    """h per block face from the project's correlation at the given rise."""
    bx, by, bz = p["block_size"]
    t_amb = p["ambient_C"]
    rise = max(rise, 0.5)
    l_horizontal = reference.characteristic_length_horizontal(bx, by)  # A/P
    h_vert = calculate_film_coefficient(t_amb, t_amb + rise, "vertical", bz)
    h_up = calculate_film_coefficient(t_amb, t_amb + rise, "horizontal_up", l_horizontal)
    h_down = calculate_film_coefficient(t_amb, t_amb + rise, "horizontal_down", l_horizontal)
    return {"vertical": h_vert, "top": h_up, "bottom": h_down}


def build(p, eps_block, h, mesh_mm, name):
    amb = p["ambient_C"] + 273.15
    heater_pos, block_pos = layout(p)
    m = fcmodel.Model(name)
    m.box("Heater", p["heater_size"], heater_pos)
    m.box("Block", p["block_size"], block_pos)
    m.material("HeaterBody", ["Heater"], kind="Aluminium6061")
    m.material(p["block_material"], ["Block"])
    m.initial_temperature(amb)
    m.fixed_temperature("HeaterSetpoint", [m.faces("Heater")], p["heater_C"] + 273.15)
    m.convection("BlockSides", [m.faces("Block", "-x", "+x", "-y", "+y")], h["vertical"], amb)
    m.convection("BlockTop", [m.faces("Block", "+z")], h["top"], amb)
    m.convection("BlockBottom", [m.faces("Block", "-z")], h["bottom"], amb)
    m.radiation("HeaterRad", [m.faces("Heater")], p["heater_emissivity"], amb)
    m.radiation("BlockRad", [m.faces("Block")], eps_block, amb)
    m.solver(p["time_end_s"], p["max_step_s"], initial_step=5.0)
    m.mesh(mesh_mm, fuse=False)
    return m


def run(p, eps_block, h, mesh_mm, tag):
    m = build(p, eps_block, h, mesh_mm, tag)
    f = m.save(WORK / "models" / f"{tag}.FCStd")
    r = pipeline.run_case(f, WORK / tag, cavity_radiation=True)
    counts = {"cr": json.loads((r.workdir / "simulation.json").read_text())["Cavity radiation faces"]}
    _, block_pos = layout(p)
    hi = np.add(block_pos, p["block_size"])
    series = []
    for i, _ in enumerate(r.vtk_files):
        _, t = r.region(block_pos, hi, index=i)
        series.append((t.mean(), t.max(), t.min()))
    series = np.array(series) - 273.15
    return {
        "result": r, "nodes": m.node_count(), "cr_faces": counts.get("cr"),
        "time": r.times(), "block_mean": series[:, 0], "block_max": series[:, 1],
        "block_min": series[:, 2],
    }


def time_to(fraction, t, y, y0):
    target = y0 + fraction * (y[-1] - y0)
    idx = np.argmax(y >= target)
    return float(t[idx]) if y[idx] >= target else float("nan")


def face_map(res, p, ax, title):
    """Temperature map of the block face that looks at the heater."""
    _, block_pos = layout(p)
    pts, t = res["result"].nodes()
    on_face = np.isclose(pts[:, 0], block_pos[0])
    tc = t[on_face] - 273.15
    tcf = ax.tricontourf(pts[on_face, 1], pts[on_face, 2], tc, levels=20, cmap="inferno")
    hx, hy, hz = p["heater_size"]
    heater_pos, _ = layout(p)
    ax.add_patch(__import__("matplotlib").patches.Rectangle(
        (heater_pos[1], heater_pos[2]), hy, hz, fill=False, ls="--", ec="cyan", lw=1))
    ax.set_aspect("equal")
    ax.set_xlabel("y [mm]")
    ax.set_ylabel("z [mm] (up)")
    ax.set_title(title, fontsize=9)
    return tcf


def main():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    p = PARAMS
    OUT.mkdir(parents=True, exist_ok=True)
    summary = {"params": p, "variants": {}}
    finals = {}
    for label, eps in p["block_emissivities"].items():
        rise_guess, history = p["rise_guess_K"][label], []
        for it in range(2):  # guess, then one correction of the film coefficients
            h = film_coefficients(p, rise_guess)
            res = run(p, eps, h, p["mesh_mm"], f"{label}_it{it}")
            rise = float(res["block_mean"][-1] - p["ambient_C"])
            history.append({"assumed_rise": rise_guess, "h": h, "sim_rise": rise})
            if abs(rise - rise_guess) / max(rise, 0.1) < 0.1:
                break
            rise_guess = rise
        t, y = res["time"], res["block_mean"]
        slope = (y[-1] - y[-6]) / (t[-1] - t[-6]) * 3600  # K/h at the end
        summary["variants"][label] = {
            "emissivity": eps, "nodes": res["nodes"], "cavity_faces": res["cr_faces"],
            "film_iterations": history,
            "final_block_mean_C": float(y[-1]), "final_block_max_C": float(res["block_max"][-1]),
            "final_block_min_C": float(res["block_min"][-1]),
            "face_spread_K": float(res["block_max"][-1] - res["block_min"][-1]),
            "t63_min": time_to(0.632, t, y, p["ambient_C"]) / 60,
            "t95_min": time_to(0.95, t, y, p["ambient_C"]) / 60,
            "end_slope_K_per_h": float(slope),
        }
        finals[label] = res

    # mesh check on the anodised case
    label = "anodised"
    h = summary["variants"][label]["film_iterations"][-1]["h"]
    fine = run(p, p["block_emissivities"][label], h, p["mesh_check_mm"], f"{label}_fine")
    coarse_rise = summary["variants"][label]["final_block_mean_C"] - p["ambient_C"]
    fine_rise = float(fine["block_mean"][-1] - p["ambient_C"])
    summary["mesh_check"] = {
        "coarse_mm": p["mesh_mm"], "fine_mm": p["mesh_check_mm"],
        "coarse_rise": coarse_rise, "fine_rise": fine_rise,
        "diff_%": 100 * (coarse_rise / fine_rise - 1),
    }

    # hand estimate of direct gas conduction across the gap (not in the model)
    hy, hz = p["heater_size"][1:]
    k_air = 0.028
    g_air = k_air * (hy * hz * 1e-6) / (p["gap"] * 1e-3)
    summary["gas_conduction_estimate_W"] = {
        lbl: g_air * (p["heater_C"] - v["final_block_mean_C"])
        for lbl, v in summary["variants"].items()
    }
    # heat actually reaching the block at the end = what it loses at steady state
    bx, by, bz = p["block_size"]
    for lbl, v in summary["variants"].items():
        hh = v["film_iterations"][-1]["h"]
        rise = v["final_block_mean_C"] - p["ambient_C"]
        a_vert = 2 * (by * bz + bx * bz) * 1e-6
        a_hor = bx * by * 1e-6
        conv = (hh["vertical"] * a_vert + (hh["top"] + hh["bottom"]) * a_hor) * rise
        t_s, t_a = v["final_block_mean_C"] + 273.15, p["ambient_C"] + 273.15
        rad = v["emissivity"] * reference_sigma() * (a_vert + 2 * a_hor) * (t_s**4 - t_a**4)
        v["approx_heat_into_block_W"] = conv + rad

    # ---- plots
    fig, ax = plt.subplots(figsize=(7, 4.2))
    for lbl, res in finals.items():
        ax.plot(res["time"] / 60, res["block_mean"], label=f"{lbl} (ε={p['block_emissivities'][lbl]}) mean")
        ax.fill_between(res["time"] / 60, res["block_min"], res["block_max"], alpha=0.25)
    ax.set_xlabel("time [min]")
    ax.set_ylabel("block temperature [°C]")
    ax.set_title(f"Block warm-up, heater fixed at {p['heater_C']:.0f} °C, {p['gap']:.0f} mm gap, "
                 f"ambient {p['ambient_C']:.0f} °C", fontsize=9)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(OUT / "warmup.png", dpi=150)

    fig, axes = plt.subplots(1, 2, figsize=(9, 4))
    for ax, (lbl, res) in zip(axes, finals.items()):
        tcf = face_map(res, p, ax, f"{lbl}: face toward heater at {p['time_end_s'] / 3600:.0f} h")
        fig.colorbar(tcf, ax=ax, label="°C", shrink=0.85)
    fig.tight_layout()
    fig.savefig(OUT / "face_map.png", dpi=150)

    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, default=float))
    for lbl, v in summary["variants"].items():
        print(f"{lbl:9} eps={v['emissivity']}: block {v['final_block_mean_C']:.2f} C "
              f"(face spread {v['face_spread_K']:.2f} K), t63 {v['t63_min']:.0f} min, "
              f"t95 {v['t95_min']:.0f} min, ~{v['approx_heat_into_block_W']:.3f} W in")
    print(f"mesh check: {summary['mesh_check']}")
    print(f"gas conduction estimate (W): {summary['gas_conduction_estimate_W']}")


def reference_sigma():
    return 5.670374419e-8


if __name__ == "__main__":
    main()
