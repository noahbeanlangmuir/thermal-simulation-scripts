"""Toolchain checks not covered by the benchmarks.

S4:  a mesh object not named FEMMeshGmsh (e.g. after switching to Netgen or
     renaming) changes the .inp name; the README / find_coef.sh commands then
     point at a file that does not exist.
S21: re-read the unfused B4 run and report board-only temperatures (nodes
     strictly inside the board, so the package's bottom face is excluded).

    python validation/benchmarks/check_s4_s21.py   (after run_benchmarks.py B4)
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import fcmodel  # noqa: E402
import pipeline  # noqa: E402

WORK = Path(os.environ.get("TSS_WORK", Path.home() / "tss-work"))
RES = HERE.parent / "results"


def s4():
    m = fcmodel.Model("s4")
    m.box("Slab", (20, 20, 2))
    m.material("FR4", ["Slab"])
    m.initial_temperature(298.15)
    m.fixed_temperature("Cold", [m.faces("Slab", "-z")], 298.15)
    m.dflux("Flux", [m.faces("Slab", "+z")], 1000.0)
    m.solver(60.0, 10.0, initial_step=1.0)
    m.mesh(2.0, name="FEMMeshNetgen")
    f = m.save(WORK / "models" / "s4.FCStd")
    wd = WORK / "s4"
    shutil.rmtree(wd, ignore_errors=True)
    wd.mkdir(parents=True)
    shutil.copy(f, wd)
    p = subprocess.run(["tpre", "parse-fcstd", "--fcstd", f.name], cwd=wd,
                       capture_output=True, text=True)
    inps = sorted(x.name for x in wd.glob("*.inp"))
    sim = wd / "simulation.json"
    reported = json.loads(sim.read_text()).get("Input file") if sim.exists() else None
    told = f"ccx {Path(reported).stem}" in (p.stdout + p.stderr) if reported else False
    q = subprocess.run(["ccx", "FEMMeshGmsh"], cwd=wd, capture_output=True, text=True)
    out = (q.stdout + q.stderr).strip().splitlines()
    fixed = reported in inps and told  # tpre names the file and prints the command
    return {
        "tpre_rc": p.returncode, "inp_written": inps, "simulation_json_input_file": reported,
        "tpre_prints_ccx_command": told, "readme_ccx_rc": q.returncode,
        "readme_ccx_msg": next((l for l in out if "rror" in l or "not" in l), out[-1] if out else ""),
        "status": "NOT REPRODUCED" if fixed else
        ("CONFIRMED" if inps and "FEMMeshGmsh.inp" not in inps else "NOT REPRODUCED"),
    }


def s21_board_only():
    r = pipeline.Result(WORK / "b4_unfused")
    plate = (100.0, 80.0, 1.6)
    _, tb = r.region((0, 0, 0), (plate[0], plate[1], plate[2] - 0.05))
    _, tp = r.region((45, 35, 1.6 + 0.05), (55, 45, 3.6))
    return {"board_dTmax": float(tb.max() - 298.15), "package_dTmean": float(tp.mean() - 298.15),
            "end_time_s": float(r.times()[-1])}


if __name__ == "__main__":
    res = {"S4": s4()}
    if (WORK / "b4_unfused").exists():
        res["S21_board_only"] = s21_board_only()
    (RES / "toolchain_checks.json").write_text(json.dumps(res, indent=2))
    print(json.dumps(res, indent=2))
