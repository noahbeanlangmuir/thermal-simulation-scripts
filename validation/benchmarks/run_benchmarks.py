"""Accuracy benchmarks B2-B9 through the real tpre/ccx/tpost flow.

    python validation/benchmarks/run_benchmarks.py [B2 B3 ...]

Writes validation/results/<ID>.json and prints a one-line verdict per check.
Work directories go to $TSS_WORK (default ~/tss-work).
"""

import json
import math
import os
import shutil
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import fcmodel  # noqa: E402
import pipeline  # noqa: E402
import reference  # noqa: E402

WORK = Path(os.environ.get("TSS_WORK", Path.home() / "tss-work"))
RESULTS = HERE.parent / "results"
AMB = 298.15
SIGMA = 5.670374419e-8


def verdict(ok):
    return "PASS" if ok else "FAIL"


def fit_first_order(t, dT):
    """Least-squares fit of dT = A (1 - exp(-t/tau)); returns (A, tau)."""
    best = None
    for tau in np.geomspace(1, 1e5, 4000):
        g = 1 - np.exp(-t / tau)
        a = float(g @ dT / (g @ g))
        err = float(np.sum((dT - a * g) ** 2))
        if best is None or err < best[0]:
            best = (err, a, tau)
    return best[1], best[2]


# --------------------------------------------------------------------- B2
def lumped_model(name, mesh_size, output_frequency=1, time_end=3000.0):
    m = fcmodel.Model(name)
    m.box("Cube", (10, 10, 10))
    m.material("Copper", ["Cube"])
    m.initial_temperature(AMB)
    m.cflux("Heat", [m.faces("Cube")], 1.0)
    m.convection("Film", [m.faces("Cube")], 10.0, AMB)
    m.solver(time_end, 25.0, initial_step=1.0, output_frequency=output_frequency)
    m.mesh(mesh_size)
    return m


def b2():
    """Lumped copper cube: CFlux units/total power (S20), film units, timing (S6)."""
    k, rho, cp = fcmodel.MATERIALS["Copper"]
    area, vol, h, p = 6e-4, 1e-6, 10.0, 1.0
    rise = reference.lumped_rise(p, h, area)
    tau = reference.lumped_tau(rho, cp, vol, h, area)
    out = {"analytic": {"dT_ss": rise, "tau": tau}, "meshes": []}
    for size in (5.0, 2.5, 1.25):
        m = lumped_model(f"b2_{size}", size)
        f = m.save(WORK / "models" / f"b2_mesh{size}.FCStd")
        nodes = m.node_count()
        r = pipeline.run_case(f, WORK / f"b2_mesh{size}")
        t = r.times()
        dT = r.csv["max [K]"].to_numpy() - AMB
        a, tau_fit = fit_first_order(t, dT)
        expected = rise * (1 - np.exp(-t / tau))
        mask = t > 0.1 * tau
        max_err = float(np.max(np.abs(dT[mask] - expected[mask]) / expected[mask]))
        out["meshes"].append({
            "mesh_mm": size, "nodes": nodes, "dT_ss_fit": a, "tau_fit": tau_fit,
            "dT_ss_err_%": 100 * (a / rise - 1), "tau_err_%": 100 * (tau_fit / tau - 1),
            "max_curve_err_%": 100 * max_err,
        })
    errs = [abs(x["dT_ss_err_%"]) for x in out["meshes"]]
    terrs = [abs(x["tau_err_%"]) for x in out["meshes"]]
    out["pass"] = max(errs) <= 1.0 and max(terrs) <= 2.0
    out["summary"] = (
        f"dT_ss {rise:.2f} K analytic; worst error {max(errs):.2f} %, "
        f"tau worst {max(terrs):.2f} % over {len(errs)} meshes"
    )

    # S6: write results every 2nd increment; does tpost csv keep time/T aligned?
    m = lumped_model("b2_of2", 2.5, output_frequency=2)
    f = m.save(WORK / "models" / "b2_outfreq2.FCStd")
    s6 = {}
    try:
        r = pipeline.run_case(f, WORK / "b2_outfreq2")
        t = r.times()
        dT = r.csv["max [K]"].to_numpy() - AMB
        expected = rise * (1 - np.exp(-t / tau))
        mask = t > 0.1 * tau
        s6["max_curve_err_%"] = float(100 * np.max(np.abs(dT[mask] - expected[mask]) / expected[mask]))
        s6["rows"] = len(t)
        s6["status"] = "CONFIRMED" if s6["max_curve_err_%"] > 5 else "NOT REPRODUCED"
    except pipeline.PipelineError as e:
        s6["status"] = "CONFIRMED (loud)"
        s6["error"] = str(e)
        log = WORK / "b2_outfreq2" / "04_csv.log"
        if log.exists():
            s6["log_tail"] = log.read_text()[-400:]
    out["S6_output_frequency_2"] = s6

    # S5: re-run a shorter simulation on top of the previous results
    short = lumped_model("b2_short", 2.5, time_end=1000.0)
    f = short.save(WORK / "models" / "b2_short.FCStd")
    wd = WORK / "b2_mesh2.5"  # still holds the 3000 s run's vtk/ files
    s5 = {"vtk_before": len(list((wd / "vtk").glob("*.vtk")))}
    try:
        r = pipeline.run_case(f, wd, clean=False)
        s5["rows"] = len(r.csv)
        s5["max_time_in_csv"] = float(r.times().max())
        s5["status"] = "CONFIRMED" if r.times().max() > 1000.0 + 1e-6 else "NOT REPRODUCED"
    except pipeline.PipelineError as e:
        s5["status"] = "CONFIRMED (loud, cryptic)"
        s5["error"] = str(e)
        log = wd / "04_csv.log"
        s5["log_tail"] = log.read_text()[-300:] if log.exists() else ""
    out["S5_stale_vtk"] = s5
    return out


# --------------------------------------------------------------------- B3
def b3():
    """FR4 slab, fixed T on one face, uniform heat flux into the other."""
    k = fcmodel.MATERIALS["FR4"][0]
    thick, q = 2.0, 1000.0
    rise = q * thick / 1000 / k
    m = fcmodel.Model("b3")
    m.box("Slab", (20, 20, thick))
    m.material("FR4", ["Slab"])
    m.initial_temperature(AMB)
    m.fixed_temperature("Cold", [m.faces("Slab", "-z")], AMB)
    m.dflux("Flux", [m.faces("Slab", "+z")], q)
    m.solver(600.0, 10.0, initial_step=0.5)
    m.mesh(1.0)
    f = m.save(WORK / "models" / "b3_slab.FCStd")
    r = pipeline.run_case(f, WORK / "b3")
    pts, t = r.nodes()
    top = t[np.isclose(pts[:, 2], thick)]
    mid = t[np.isclose(pts[:, 2], thick / 2)]
    err = 100 * ((top.mean() - AMB) / rise - 1)
    err_mid = 100 * ((mid.mean() - AMB) / (rise / 2) - 1) if mid.size else float("nan")
    return {
        "analytic_rise": rise, "sim_rise": float(top.mean() - AMB),
        "err_%": err, "mid_plane_err_%": err_mid, "pass": abs(err) <= 0.5,
        "summary": f"top-face rise {top.mean() - AMB:.4f} K vs {rise:.4f} K ({err:+.3f} %)",
    }


def _rejected(fcstd, workdir):
    """True if tpre parse-fcstd refuses the model (exit != 0) with a model error."""
    try:
        pipeline.run_case(fcstd, workdir)
    except pipeline.PipelineError as e:
        log = (Path(workdir) / "01_parse.log")
        return "01_parse.log" in str(e) and log.exists() and "model error" in log.read_text()
    return False


# --------------------------------------------------------------------- B4/B5
PLATE = (100.0, 80.0, 1.6)
PKG = (10.0, 10.0, 2.0)
PKG_POS = (45.0, 35.0, 1.6)


def board_model(name, mesh_size, fuse=True, h=10.0, power=2.0, refs="fragments",
                load="cflux"):
    """refs='fragments': convection on the split faces of the fused shape, as a
    GUI user picks them. refs='boxes': convection on the original plate face,
    which also covers the hidden plate/package interface (finding S24)."""
    m = fcmodel.Model(name)
    m.box("Plate", PLATE)
    m.box("Package", PKG, PKG_POS)
    m.material("FR4", ["Plate"])
    m.material("Copper", ["Package"])  # isothermal package isolates plate spreading
    m.initial_temperature(AMB)
    if load == "cflux":
        m.cflux("Power", [m.faces("Package", "+z")], power)
    else:
        m.dflux("Power", [m.faces("Package", "+z")], power / (PKG[0] * PKG[1] * 1e-6))
    if fuse and refs == "fragments":
        m.fuse()
        z = PLATE[2]
        top = m.fragment_faces(lambda f: abs(f.CenterOfMass.z - z) < 1e-6 and f.Area > 1000)
        bottom = m.fragment_faces(lambda f: abs(f.CenterOfMass.z) < 1e-6)
        m.convection("Top", [top], h, AMB)
        m.convection("Bottom", [bottom], h, AMB)
    else:
        m.convection("Top", [m.faces("Plate", "+z")], h, AMB)
        m.convection("Bottom", [m.faces("Plate", "-z")], h, AMB)
    m.solver(20000.0, 400.0, initial_step=5.0)
    m.mesh(mesh_size, fuse=fuse)
    return m


def fin_reference(h=10.0, power=2.0, n=(201, 161)):
    """Independent 2-D finite-volume solution of the thin plate (fin) problem.

    k t lap(T) - 2 h (T - Tamb) + q'' = 0, package footprint held isothermal
    (copper) by giving it a very high conductivity. Biot (h t / k) = 0.05.
    """
    import scipy.sparse as sp
    import scipy.sparse.linalg as spla

    k = fcmodel.MATERIALS["FR4"][0]
    t = PLATE[2] / 1000
    lx, ly = PLATE[0] / 1000, PLATE[1] / 1000
    nx, ny = n
    dx, dy = lx / nx, ly / ny
    xc = (np.arange(nx) + 0.5) * dx * 1000
    yc = (np.arange(ny) + 0.5) * dy * 1000
    X, Y = np.meshgrid(xc, yc, indexing="ij")
    inpkg = (X >= PKG_POS[0]) & (X <= PKG_POS[0] + PKG[0]) & \
            (Y >= PKG_POS[1]) & (Y <= PKG_POS[1] + PKG[1])
    kt = np.where(inpkg, 1e4, k * t)  # W/K sheet conductance, package ~isothermal
    idx = np.arange(nx * ny).reshape(nx, ny)
    rows, cols, vals = [], [], []
    diag = np.full((nx, ny), 2 * h * dx * dy)
    rhs = np.full((nx, ny), 2 * h * dx * dy * 0.0)
    q_cell = power / inpkg.sum()
    rhs[inpkg] += q_cell
    for (di, dj, d, w) in ((1, 0, dx, dy), (-1, 0, dx, dy), (0, 1, dy, dx), (0, -1, dy, dx)):
        i0, i1 = max(0, -di), nx - max(0, di)
        j0, j1 = max(0, -dj), ny - max(0, dj)
        a = kt[i0:i1, j0:j1]
        b = kt[i0 + di:i1 + di, j0 + dj:j1 + dj]
        g = 2 * a * b / (a + b) * w / d
        diag[i0:i1, j0:j1] += g
        rows.append(idx[i0:i1, j0:j1].ravel())
        cols.append(idx[i0 + di:i1 + di, j0 + dj:j1 + dj].ravel())
        vals.append(-g.ravel())
    rows.append(idx.ravel()); cols.append(idx.ravel()); vals.append(diag.ravel())
    A = sp.csr_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))))
    T = spla.spsolve(A, rhs.ravel()).reshape(nx, ny)
    return float(T.max()), float(T[inpkg].mean())


def b4_b5():
    """Board with a hot package: fused vs unfused (S21), mesh convergence (B5),
    independent 3-D gmsh/Elmer reference (B4).

    The 2-D fin solution is kept for information only: it assumes the board is
    isothermal through its thickness, which fails under a 10x10 mm source on
    k=0.3 FR4 (~53 K/W through-thickness resistance), so it reads ~30 % low.
    """
    fin_2d, _ = fin_reference()
    ref_max, _ = elmer_board(WORK / "b4_elmer_ref", 2.0)
    out = {"reference_elmer_dTmax": ref_max, "fin_2d_estimate_dTmax": fin_2d, "meshes": []}
    for size in (8.0, 4.0, 2.0):
        m = board_model(f"b4_{size}", size)
        f = m.save(WORK / "models" / f"b4_fused_{size}.FCStd")
        r = pipeline.run_case(f, WORK / f"b4_fused_{size}")
        _, tp = r.region(PKG_POS, np.add(PKG_POS, PKG))
        dTmax = float(r.csv["max [K]"].iloc[-1] - AMB)
        prev = float(r.csv["max [K]"].iloc[-6] - AMB)
        out["meshes"].append({"mesh_mm": size, "nodes": m.node_count(), "dTmax": dTmax,
                              "dT_pkg_mean": float(tp.mean() - AMB),
                              "still_rising_K": dTmax - prev})
    # GCI on the three meshes (refinement ratio 2)
    f1, f2, f3 = (x["dTmax"] for x in reversed(out["meshes"]))  # fine, medium, coarse
    ratio = (f3 - f2) / (f2 - f1) if f2 != f1 else float("inf")
    p = math.log(abs(ratio)) / math.log(2) if ratio > 0 and ratio != float("inf") else 2.0
    gci = 1.25 * abs((f2 - f1) / f1) / (2**p - 1) * 100
    extrap = f1 + (f1 - f2) / (2**p - 1)
    out["B5"] = {"observed_order": p, "GCI_fine_%": gci, "extrapolated_dTmax": extrap,
                 "pass": gci < 5}
    err = 100 * (f1 / ref_max - 1)
    out["B4"] = {"fine_dTmax": f1, "reference": ref_max, "err_%": err, "pass": abs(err) < 5}
    # S21: same board, parts selected as a plain compound (not fused)
    m = board_model("b4_unfused", 4.0, fuse=False)
    f = m.save(WORK / "models" / "b4_unfused.FCStd")
    s21 = {"detected_by_tpre": _rejected(f, WORK / "b4_unfused_check")}
    try:
        r = pipeline.run_case(f, WORK / "b4_unfused", force=True)
        _, tpl = r.region((0, 0, 0), PLATE)
        s21["dTmax"] = float(r.csv["max [K]"].iloc[-1] - AMB)
        s21["plate_dTmax"] = float(tpl.max() - AMB)
        silent = s21["dTmax"] > 3 * f1
        s21["status"] = ("DETECTED (tpre stops)" if s21["detected_by_tpre"] else "CONFIRMED")             if silent else "NOT REPRODUCED"
        log = (WORK / "b4_unfused" / "01_parse.log").read_text()
        s21["warned"] = "warn" in log.lower() or "error" in log.lower()
    except pipeline.PipelineError as e:
        s21["status"] = "CONFIRMED (loud)"
        s21["error"] = str(e)
    out["S21_unfused"] = s21
    # S24: convection referenced on the original plate face (covers the hidden
    # plate/package interface) instead of the split face of the fused shape
    m = board_model("b4_boxrefs", 4.0, refs="boxes")
    f = m.save(WORK / "models" / "b4_boxrefs.FCStd")
    detected = _rejected(f, WORK / "b4_boxrefs_check")
    r = pipeline.run_case(f, WORK / "b4_boxrefs", force=True)
    box_dT = float(r.csv["max [K]"].iloc[-1] - AMB)
    split_dT = f2  # 4 mm mesh, split-face references
    diff = 100 * (box_dT / split_dT - 1)
    out["S24_box_face_refs"] = {
        "dTmax_box_refs": box_dT, "dTmax_split_refs": split_dT, "diff_%": diff,
        "detected_by_tpre": detected,
        "status": ("DETECTED (tpre stops)" if detected else "CONFIRMED") if abs(diff) > 1
        else "NOT REPRODUCED",
    }
    out["pass"] = out["B4"]["pass"] and out["B5"]["pass"]
    out["summary"] = (f"fine-mesh dTmax {f1:.2f} K vs 3-D Elmer {ref_max:.2f} K "
                      f"({err:+.1f} %); GCI {gci:.2f} %; unfused: {s21.get('status')}; "
                      f"box-face refs {diff:+.1f} %")
    return out


# --------------------------------------------------------------------- B9
def view_factor_parallel_squares(a, c):
    x = y = a / c
    return 2 / (math.pi * x * y) * (
        math.log(math.sqrt((1 + x**2) * (1 + y**2) / (1 + x**2 + y**2)))
        + x * math.sqrt(1 + y**2) * math.atan(x / math.sqrt(1 + y**2))
        + y * math.sqrt(1 + x**2) * math.atan(y / math.sqrt(1 + x**2))
        - x * math.atan(x) - y * math.atan(y)
    )


def b9():
    """Cavity radiation between two parallel black plates (needed for the
    heater/block case): hot plate fixed, cold plate floats; only the facing
    faces radiate. Steady state: T_B^4 = F T_A^4 + (1 - F) T_amb^4."""
    a, gap, th = 50.0, 20.0, 2.0
    ta = 423.15
    F = view_factor_parallel_squares(a, gap)
    tb_exact = (F * ta**4 + (1 - F) * AMB**4) ** 0.25
    out = {"view_factor": F, "TB_exact_K": tb_exact, "meshes": []}
    for size in (5.0, 2.5):
        m = fcmodel.Model(f"b9_{size}")
        m.box("Hot", (a, a, th), (0, 0, 0))
        m.box("Cold", (a, a, th), (0, 0, th + gap))
        m.material("Aluminium6061", ["Hot", "Cold"])
        m.initial_temperature(AMB)
        m.fixed_temperature("HotT", [m.faces("Hot")], ta)
        m.radiation("Rad", [m.faces("Hot", "+z"), m.faces("Cold", "-z")], 1.0, AMB)
        m.solver(40000.0, 500.0, initial_step=10.0)
        m.mesh(size, fuse=False)
        f = m.save(WORK / "models" / f"b9_{size}.FCStd")
        r = pipeline.run_case(f, WORK / f"b9_{size}", cavity_radiation=True)
        n_cr = {"n": json.loads((r.workdir / "simulation.json").read_text())["Cavity radiation faces"]}
        _, tc = r.region((0, 0, th + gap), (a, a, 2 * th + gap))
        _, tc_prev = r.region((0, 0, th + gap), (a, a, 2 * th + gap), index=-6)
        tb = float(tc.mean())
        out["meshes"].append({"mesh_mm": size, "CR_faces": n_cr.get("n"), "TB_sim_K": tb,
                              "rise_err_%": 100 * ((tb - AMB) / (tb_exact - AMB) - 1),
                              "still_rising_K": tb - float(tc_prev.mean())})
    worst = max(abs(x["rise_err_%"]) for x in out["meshes"])
    out["pass"] = worst < 3
    out["summary"] = (f"F={F:.4f}; cold plate {out['meshes'][-1]['TB_sim_K'] - 273.15:.2f} C "
                      f"vs exact {tb_exact - 273.15:.2f} C; worst rise error {worst:.2f} %")
    return out


# --------------------------------------------------------------------- B6
ELMER_SIF = """Header
  Mesh DB "." "board"
End
Simulation
  Coordinate System = Cartesian
  Coordinate Scaling = 0.001
  Simulation Type = Steady state
  Steady State Max Iterations = 1
  Output Intervals = 1
  Post File = "board.vtu"
End
Constants
  Stefan Boltzmann = 5.670374419e-08
End
Body 1
  Target Bodies(1) = 1
  Equation = 1
  Material = 1
End
Body 2
  Target Bodies(1) = 2
  Equation = 1
  Material = 2
End
Solver 1
  Equation = Heat Equation
  Procedure = "HeatSolve" "HeatSolver"
  Variable = Temperature
  Linear System Solver = Iterative
  Linear System Iterative Method = BiCGStab
  Linear System Preconditioning = ILU1
  Linear System Max Iterations = 5000
  Linear System Convergence Tolerance = 1.0e-12
  Steady State Convergence Tolerance = 1.0e-8
End
Equation 1
  Active Solvers(1) = 1
End
Material 1
  Heat Conductivity = {k_plate}
  Density = 1850
  Heat Capacity = 1100
End
Material 2
  Heat Conductivity = {k_pkg}
  Density = 8960
  Heat Capacity = 385
End
Boundary Condition 1
  Target Boundaries(2) = 1 2
  Heat Transfer Coefficient = {h}
  External Temperature = {amb}
End
Boundary Condition 2
  Target Boundaries(1) = 3
  Heat Flux BC = Logical True
  Heat Flux = {q}
End
"""


def elmer_board(workdir, mesh_size, h=10.0, power=2.0):
    """Independent model: gmsh (own geometry/mesh) -> ElmerGrid -> ElmerSolver."""
    import glob
    import subprocess
    import gmsh
    import vtkmodules.all as vtk
    from vtkmodules.util import numpy_support

    workdir = Path(workdir)
    shutil.rmtree(workdir, ignore_errors=True)
    workdir.mkdir(parents=True)
    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    gmsh.model.add("board")
    plate = gmsh.model.occ.addBox(0, 0, 0, *PLATE)
    pkg = gmsh.model.occ.addBox(*PKG_POS, *PKG)
    gmsh.model.occ.fragment([(3, plate)], [(3, pkg)])
    gmsh.model.occ.synchronize()
    vols = {"plate": [], "pkg": []}
    for d, t in gmsh.model.getEntities(3):
        z = gmsh.model.occ.getCenterOfMass(d, t)[2]
        vols["plate" if z < PLATE[2] else "pkg"].append(t)
    top, bottom, pkg_top = [], [], []
    for d, t in gmsh.model.getEntities(2):
        x, y, z = gmsh.model.occ.getCenterOfMass(d, t)
        area = gmsh.model.occ.getMass(d, t)
        if abs(z - PLATE[2]) < 1e-6 and area > 1000:
            top.append(t)
        elif abs(z) < 1e-6:
            bottom.append(t)
        elif abs(z - (PKG_POS[2] + PKG[2])) < 1e-6:
            pkg_top.append(t)
    gmsh.model.addPhysicalGroup(3, vols["plate"], 1)
    gmsh.model.addPhysicalGroup(3, vols["pkg"], 2)
    gmsh.model.addPhysicalGroup(2, top, 1)
    gmsh.model.addPhysicalGroup(2, bottom, 2)
    gmsh.model.addPhysicalGroup(2, pkg_top, 3)
    gmsh.option.setNumber("Mesh.MeshSizeMax", mesh_size)
    gmsh.option.setNumber("Mesh.ElementOrder", 2)
    gmsh.option.setNumber("Mesh.MshFileVersion", 2.2)
    gmsh.model.mesh.generate(3)
    n_nodes = len(gmsh.model.mesh.getNodes()[0])
    gmsh.write(str(workdir / "board.msh"))
    gmsh.finalize()
    k_plate, k_pkg = fcmodel.MATERIALS["FR4"][0], fcmodel.MATERIALS["Copper"][0]
    q = power / (PKG[0] * PKG[1] * 1e-6)
    (workdir / "case.sif").write_text(
        ELMER_SIF.format(k_plate=k_plate, k_pkg=k_pkg, h=h, amb=AMB, q=q))
    (workdir / "ELMERSOLVER_STARTINFO").write_text("case.sif\n1\n")
    for cmd, log in ((["ElmerGrid", "14", "2", "board.msh", "-autoclean"], "elmergrid.log"),
                     (["ElmerSolver", "case.sif"], "elmersolver.log")):
        p = subprocess.run(cmd, cwd=workdir, capture_output=True, text=True,
                           env={**os.environ, "OMP_NUM_THREADS": "1"})
        (workdir / log).write_text(p.stdout + p.stderr)
        if p.returncode != 0:
            raise pipeline.PipelineError(f"{cmd[0]} exited {p.returncode}, see {workdir / log}")
    vtus = sorted(glob.glob(str(workdir / "**" / "*.vtu"), recursive=True))
    if not vtus:
        raise pipeline.PipelineError(f"Elmer produced no .vtu in {workdir}")
    rd = vtk.vtkXMLUnstructuredGridReader()
    rd.SetFileName(vtus[-1])
    rd.Update()
    t = numpy_support.vtk_to_numpy(rd.GetOutput().GetPointData().GetArray("temperature"))
    return float(t.max() - AMB), n_nodes


def b6():
    """Cross-code: the B4 board with a uniform heat flux on the package top,
    solved by the project flow (FreeCAD/gmsh -> CalculiX, run to steady state)
    and by an independent gmsh -> Elmer model built without FreeCAD."""
    out = {"meshes": []}
    for size in (4.0, 2.0):
        m = board_model(f"b6_ccx_{size}", size, load="dflux")
        f = m.save(WORK / "models" / f"b6_ccx_{size}.FCStd")
        r = pipeline.run_case(f, WORK / f"b6_ccx_{size}")
        ccx = float(r.csv["max [K]"].iloc[-1] - AMB)
        elmer, n = elmer_board(WORK / f"b6_elmer_{size}", size)
        out["meshes"].append({"mesh_mm": size, "ccx_dTmax": ccx, "elmer_dTmax": elmer,
                              "ccx_nodes": m.node_count(), "elmer_nodes": n,
                              "diff_%": 100 * (ccx / elmer - 1)})
    fine = out["meshes"][-1]
    out["pass"] = abs(fine["diff_%"]) <= 3
    out["summary"] = (f"{fine['mesh_mm']} mm mesh: ccx dTmax {fine['ccx_dTmax']:.2f} K vs "
                      f"Elmer {fine['elmer_dTmax']:.2f} K ({fine['diff_%']:+.2f} %)")
    return out


BENCHMARKS = {"B2": b2, "B3": b3, "B4": b4_b5, "B6": b6, "B9": b9}


def main(ids):
    RESULTS.mkdir(exist_ok=True)
    for bid in ids or BENCHMARKS:
        try:
            res = BENCHMARKS[bid]()
        except Exception as e:  # report and continue with the others
            import traceback
            res = {"pass": False, "summary": f"ERROR {type(e).__name__}: {e}",
                   "traceback": traceback.format_exc()}
        (RESULTS / f"{bid}.json").write_text(json.dumps(res, indent=2, default=float))
        print(f"{bid}: {verdict(res.get('pass'))}  {res.get('summary')}", flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
