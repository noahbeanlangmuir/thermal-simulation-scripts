"""Ballpark: how fast does an aluminium block in a closed enclosure approach
the temperature of a PID-held heater element?

    python validation/cases/oven_lumped.py

Lumped network (each node one temperature; the block's internal spread was
shown to be < 0.03 K by the 3-D FEM case, so this is a good approximation):

    heater (fixed T, PID) --rad--> block, walls      --conv--> air
    block  <--rad--> walls, heater   <--conv--> air
    air    <--conv--> walls
    walls  --conduction through insulation + outside film--> room

Radiation: gray diffuse radiosity network with view factors from numerical
integration. Convection: textbook natural-convection correlations with
properties at film temperature (validation/reference.py). Air movement inside
the box is NOT resolved; the box air is one well-mixed node.

Checks before use (printed and saved):
  * the view-factor integrator reproduces the exact parallel-square value (B9)
  * the lumped model reproduces the validated 3-D FEM heater/block case
"""

import json
import math
import sys
from pathlib import Path

import numpy as np
from scipy.integrate import solve_ivp

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "validation"))
import reference  # noqa: E402

SIGMA = 5.670374419e-8
IN = 0.0254
OUT = ROOT / "validation" / "results" / "oven"


def f_to_k(f):
    return (f - 32) / 1.8 + 273.15


def k_to_f(k):
    return (k - 273.15) * 1.8 + 32


# ------------------------------------------------------------- view factors
def view_factor_facing(a1, b1, a2, b2, d, offset=(0.0, 0.0), n=16):
    """F from rectangle 1 (a1 x b1, plane x=0, normal +x) to rectangle 2
    (a2 x b2, plane x=d, normal -x, centre offset (dy, dz)). Gauss quadrature
    of F12 = 1/A1 * integral of d^2 / (pi r^4) dA1 dA2."""
    g, w = np.polynomial.legendre.leggauss(n)
    y1, z1 = g * a1 / 2, g * b1 / 2
    y2, z2 = offset[0] + g * a2 / 2, offset[1] + g * b2 / 2
    w1 = np.outer(w, w).ravel() * a1 * b1 / 4
    w2 = np.outer(w, w).ravel() * a2 * b2 / 4
    Y1, Z1 = (m.ravel() for m in np.meshgrid(y1, z1, indexing="ij"))
    Y2, Z2 = (m.ravel() for m in np.meshgrid(y2, z2, indexing="ij"))
    r2 = (Y1[:, None] - Y2[None, :]) ** 2 + (Z1[:, None] - Z2[None, :]) ** 2 + d * d
    k = d * d / (math.pi * r2 * r2)
    return float(w1 @ k @ w2) / (a1 * b1)


# --------------------------------------------------------------- convection
def h_nat(t_surface, t_air, orientation, length):
    """Natural convection coefficient [W/m2K]; handles cooled surfaces."""
    dt = t_surface - t_air
    if abs(dt) < 1e-3:
        return 1.0
    if dt < 0 and orientation != "vertical":  # a cold top behaves like a hot bottom
        orientation = {"horizontal_up": "horizontal_down", "horizontal_down": "horizontal_up"}[orientation]
    lo, hi = sorted((t_surface, t_air))
    return reference.h_textbook(lo - 273.15, hi - 273.15, orientation, length * 1000)


# ---------------------------------------------------------------- radiosity
def radiosity(T, eps, area, F, fixed):
    """Net radiative heat leaving each surface [W]. fixed[i]: black/known."""
    n = len(T)
    eb = SIGMA * np.asarray(T) ** 4
    A = np.zeros((n, n))
    b = np.zeros(n)
    for i in range(n):
        if fixed[i] or eps[i] >= 0.999:
            A[i, i] = 1.0
            b[i] = eb[i]
            continue
        rs = eps[i] * area[i] / (1 - eps[i])
        A[i, i] += rs
        b[i] = rs * eb[i]
        for j in range(n):
            if j != i:
                A[i, i] += area[i] * F[i][j]
                A[i, j] -= area[i] * F[i][j]
    J = np.linalg.solve(A, b)
    q = np.zeros(n)
    for i in range(n):
        q[i] = sum(area[i] * F[i][j] * (J[i] - J[j]) for j in range(n) if j != i)
    return q


# ------------------------------------------------------------------- model
DEFAULT = {
    "room_F": 77.0,
    "setpoint_F": 200.0,
    "heater_in": (4.0, 4.0),          # plate, both faces exposed, faces the block
    "heater_eps": 0.9,
    "block_in": (3.0, 2.0, 2.0),      # length x width x height
    "block_face_in": (3.0, 2.0),      # face toward the heater (side-on)
    "block_eps": 0.07,                # bare / machined aluminium
    "gap_in": 15.0,
    "box_in": (24.0, 16.0, 16.0),     # inside dimensions
    "wall_eps": 0.8,                  # painted / oxidised inner wall
    "wall_steel_mm": 1.0,
    "insulation_in": 1.0,             # mineral wool, k = 0.04 W/mK; 0 = bare sheet metal
    "k_insulation": 0.04,
    "h_outside": 8.0,                 # outside convection + radiation to room
    "hours": 24.0,
}


def build(p):
    hw, hh = p["heater_in"][0] * IN, p["heater_in"][1] * IN
    bl, bw, bh = (x * IN for x in p["block_in"])
    fa, fb = p["block_face_in"][0] * IN, p["block_face_in"][1] * IN
    lx, ly, lz = (x * IN for x in p["box_in"])
    a_h = hw * hh
    a_b1 = fa * fb
    a_b = 2 * (bl * bw + bl * bh + bw * bh)
    a_w = 2 * (lx * ly + lx * lz + ly * lz)
    f_hb = view_factor_facing(hw, hh, fa, fb, p["gap_in"] * IN)
    # surfaces: 0 heater front, 1 heater back, 2 block face, 3 block rest, 4 walls
    area = np.array([a_h, a_h, a_b1, a_b - a_b1, a_w])
    F = np.zeros((5, 5))
    F[0, 2] = f_hb
    F[0, 4] = 1 - f_hb
    F[1, 4] = 1.0
    F[2, 0] = a_h * f_hb / a_b1
    F[2, 4] = 1 - F[2, 0]
    F[3, 4] = 1.0
    for j in range(4):
        F[4, j] = area[j] * F[j, 4] / a_w
    F[4, 4] = 1 - F[4, :4].sum()
    eps = np.array([p["heater_eps"], p["heater_eps"], p["block_eps"], p["block_eps"], p["wall_eps"]])
    rho_cp_block = 2700 * 896
    vol_air = lx * ly * lz - bl * bw * bh
    c_air = 1.0 * vol_air * 1007  # ~1.0 kg/m3 at 90 C
    c_wall = a_w * (p["wall_steel_mm"] / 1000 * 7850 * 490
                    + 0.5 * p["insulation_in"] * IN * 100 * 840)
    t_ins = p["insulation_in"] * IN
    u_wall = 1 / (t_ins / p["k_insulation"] + 1 / p["h_outside"]) if t_ins > 0 else p["h_outside"]
    return dict(area=area, F=F, eps=eps, f_hb=f_hb, c_block=rho_cp_block * bl * bw * bh,
                c_air=c_air, c_wall=c_wall, ua=u_wall * a_w, a_w=a_w, lz=lz,
                bl=bl, bw=bw, bh=bh, hh=hh)


def rhs_factory(p, m, t_heater, t_room, open_air=False):
    bl, bw, bh = m["bl"], m["bw"], m["bh"]
    l_hor = bl * bw / (2 * (bl + bw))
    a_vert = 2 * (bl + bw) * bh
    a_hor = bl * bw
    a_h = m["area"][0]

    def flows(tb, ta, tw):
        q = radiosity([t_heater, t_heater, tb, tb, tw], m["eps"], m["area"], m["F"],
                      fixed=[False, False, False, False, open_air])
        q_conv_b = (h_nat(tb, ta, "vertical", bh) * a_vert * (tb - ta)
                    + h_nat(tb, ta, "horizontal_up", l_hor) * a_hor * (tb - ta)
                    + h_nat(tb, ta, "horizontal_down", l_hor) * a_hor * (tb - ta))
        q_conv_h = 2 * h_nat(t_heater, ta, "vertical", m["hh"]) * a_h * (t_heater - ta)
        q_conv_w = h_nat(tw, ta, "vertical", m["lz"]) * m["a_w"] * (tw - ta)
        return q, q_conv_b, q_conv_h, q_conv_w

    def rhs(_t, y):
        tb, ta, tw = y
        q, qb, qh, qw = flows(tb, ta, tw)
        d_tb = (-(q[2] + q[3]) - qb) / m["c_block"]
        if open_air:
            return [d_tb, 0.0, 0.0]
        d_ta = (qb + qh + qw) / m["c_air"]
        d_tw = (-q[4] - qw - m["ua"] * (tw - t_room)) / m["c_wall"]
        return [d_tb, d_ta, d_tw]

    return rhs, flows


def simulate(p, open_air=False, t_heater=None, t_room=None):
    m = build(p)
    t_heater = t_heater or f_to_k(p["setpoint_F"])
    t_room = t_room or f_to_k(p["room_F"])
    rhs, flows = rhs_factory(p, m, t_heater, t_room, open_air)
    t_end = p["hours"] * 3600
    sol = solve_ivp(rhs, (0, t_end), [t_room] * 3, method="LSODA", rtol=1e-7, atol=1e-6,
                    t_eval=np.linspace(0, t_end, 1441))
    tb, ta, tw = sol.y
    q, qb, qh, qw = flows(tb[-1], ta[-1], tw[-1])
    heater_w = q[0] + q[1] + qh
    return {"t": sol.t, "block": tb, "air": ta, "wall": tw, "model": m,
            "heater_power_W": float(heater_w), "t_heater": t_heater, "t_room": t_room}


def times_to(res, fractions=(0.632, 0.9, 0.95)):
    t, y = res["t"], res["block"]
    y0, y1 = y[0], y[-1]
    out = {}
    for f in fractions:
        target = y0 + f * (y1 - y0)
        idx = int(np.argmax(y >= target))
        out[f"t{int(round(f * 100))}_h"] = float(t[idx] / 3600)
    return out


def time_within(res, kelvin):
    hit = np.nonzero(res["block"] >= res["t_heater"] - kelvin)[0]
    return float(res["t"][hit[0]] / 3600) if hit.size else None


# ------------------------------------------------------------------ checks
def check_view_factor():
    vf = view_factor_facing(0.05, 0.05, 0.05, 0.05, 0.02, n=24)
    x = 2.5
    exact = 2 / (math.pi * x * x) * (
        math.log(math.sqrt((1 + x * x) ** 2 / (1 + 2 * x * x)))
        + 2 * x * math.sqrt(1 + x * x) * math.atan(x / math.sqrt(1 + x * x))
        - 2 * x * math.atan(x))
    return {"numeric": vf, "exact": exact, "err_%": 100 * (vf / exact - 1)}


def check_against_fem():
    """Re-create the validated 3-D FEM case (results/heater_block) in open air."""
    fem = json.loads((ROOT / "validation/results/heater_block/summary.json").read_text())
    out = {}
    for label, v in fem["variants"].items():
        p = dict(DEFAULT)
        p.update(heater_in=(25 / 25.4, 25 / 25.4), heater_eps=0.9,
                 block_in=(50 / 25.4, 20 / 25.4, 50 / 25.4), block_face_in=(50 / 25.4, 50 / 25.4),
                 block_eps=v["emissivity"], gap_in=20 / 25.4, box_in=(1000, 1000, 1000),
                 hours=6.0)
        res = simulate(p, open_air=True, t_heater=423.15, t_room=298.15)
        rise = float(res["block"][-1] - 298.15)
        fem_rise = v["final_block_mean_C"] - 25.0
        out[label] = {"lumped_rise_K": rise, "fem_rise_K": fem_rise,
                      "diff_%": 100 * (rise / fem_rise - 1),
                      "lumped_t63_min": times_to(res)["t63_h"] * 60, "fem_t63_min": v["t63_min"]}
    return out


# -------------------------------------------------------------------- main
def main():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    OUT.mkdir(parents=True, exist_ok=True)
    report = {"assumptions": DEFAULT, "checks": {}}
    report["checks"]["view_factor"] = check_view_factor()
    print("view factor check:", report["checks"]["view_factor"])
    report["checks"]["vs_fem"] = check_against_fem()
    print("lumped vs 3-D FEM:", json.dumps(report["checks"]["vs_fem"], indent=1))

    base = simulate(DEFAULT)
    m = base["model"]
    report["baseline"] = {
        "view_factor_heater_to_block": m["f_hb"],
        "block_final_F": k_to_f(base["block"][-1]), "air_final_F": k_to_f(base["air"][-1]),
        "wall_final_F": k_to_f(base["wall"][-1]),
        "heater_power_at_end_W": base["heater_power_W"],
        "wall_UA_W_per_K": m["ua"],
        **times_to(base),
        "hours_to_within_5F_of_setpoint": time_within(base, 5 / 1.8),
    }
    print("baseline:", json.dumps(report["baseline"], indent=1))

    # sensitivity: insulation, heater size, finish
    sweeps = []
    cases = [("baseline (4x4 in heater, 1 in insulation, bare)", {})]
    cases += [(f"insulation {x} in", {"insulation_in": x}) for x in (0.0, 2.0, 4.0)]
    cases += [(f"heater {s:g}x{s:g} in", {"heater_in": (s, s)}) for s in (8.0, 12.0)]
    cases += [("heater 12x12 in + 4 in insulation", {"heater_in": (12.0, 12.0), "insulation_in": 4.0})]
    cases += [(f"block eps {e}", {"block_eps": e}) for e in (0.04, 0.12, 0.85)]
    cases += [("perfectly insulated box", {"k_insulation": 1e-6, "hours": 120.0})]
    curves = {}
    for name, change in cases:
        p = dict(DEFAULT)
        p.update(change)
        if change.get("insulation_in", 0) >= 4:
            p["hours"] = max(p["hours"], 72.0)
        r = simulate(p)
        row = {"case": name, "block_final_F": k_to_f(r["block"][-1]),
               "air_final_F": k_to_f(r["air"][-1]), "heater_W": r["heater_power_W"],
               **times_to(r), "hours_to_within_5F": time_within(r, 5 / 1.8)}
        sweeps.append(row)
        curves[name] = r
        print(f"{name:48} block {row['block_final_F']:6.1f} F  air {row['air_final_F']:6.1f} F  "
              f"heater {row['heater_W']:6.1f} W  t63 {row['t63_h']:5.2f} h  t95 {row['t95_h']:5.2f} h  "
              f"within 5F: {row['hours_to_within_5F']}")
    report["sensitivity"] = sweeps

    fig, ax = plt.subplots(figsize=(10, 4.6))
    for name in ("baseline (4x4 in heater, 1 in insulation, bare)", "insulation 0.0 in",
                 "heater 12x12 in", "heater 12x12 in + 4 in insulation", "perfectly insulated box"):
        r = curves[name]
        ax.plot(r["t"] / 3600, k_to_f(r["block"]), label=name)
    ax.axhline(DEFAULT["setpoint_F"], color="k", ls="--", lw=0.8, label="heater setpoint 200 °F")
    ax.set_xlim(0, 24)
    ax.set_xlabel("time [h]")
    ax.set_ylabel("block temperature [°F]")
    ax.set_title("3x2x2 in bare aluminium block, 15 in from a 200 °F PID heater, closed box "
                 "(lumped model)", fontsize=9)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=7, loc="upper left", bbox_to_anchor=(1.01, 1.0))
    fig.tight_layout()
    fig.savefig(OUT / "block_warmup.png", dpi=150)
    (OUT / "summary.json").write_text(json.dumps(report, indent=2, default=float))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
