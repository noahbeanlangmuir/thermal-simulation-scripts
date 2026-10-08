"""Run a .FCStd through the project's real flow and read the results.

    tpre parse-fcstd -> [optional .inp patch] -> ccx -> tpost convert -> tpost csv

Every step's exit code is checked, and ccx output is scanned for *ERROR, so a
benchmark can never pass on stale or partial results (see S1, S2, S5).
"""

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))


class PipelineError(RuntimeError):
    pass


def _run(cmd, cwd, log):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    log.write_text(p.stdout + "\n--- stderr\n" + p.stderr)
    if p.returncode != 0:
        raise PipelineError(f"{' '.join(map(str, cmd))} exited {p.returncode}, see {log}")
    return p


@dataclass
class Result:
    workdir: Path

    @property
    def csv(self) -> pd.DataFrame:
        return pd.read_csv(self.workdir / "temperature.csv")

    @property
    def vtk_files(self):
        return sorted((self.workdir / "vtk").glob("*.vtk"))

    def nodes(self, index=-1):
        """(points [mm], temperature [K]) for an output increment."""
        import vtkmodules.all as vtk
        from vtkmodules.util import numpy_support

        r = vtk.vtkUnstructuredGridReader()
        r.SetFileName(str(self.vtk_files[index]))
        r.Update()
        out = r.GetOutput()
        pts = numpy_support.vtk_to_numpy(out.GetPoints().GetData())
        t = numpy_support.vtk_to_numpy(out.GetPointData().GetArray("NT"))
        return pts, t

    def region(self, lo, hi, index=-1):
        """Temperatures of nodes inside the axis-aligned box [lo, hi] (mm)."""
        pts, t = self.nodes(index)
        lo, hi = np.asarray(lo) - 1e-6, np.asarray(hi) + 1e-6
        mask = np.all((pts >= lo) & (pts <= hi), axis=1)
        return pts[mask], t[mask]

    def times(self):
        return self.csv["time [s]"].to_numpy(dtype=float)


def run_case(fcstd, workdir, inp_patch=None, clean=True, cavity_radiation=False,
             force=False) -> Result:
    """Run the documented flow. cavity_radiation/force map to the tpre flags."""
    workdir = Path(workdir).resolve()
    if clean and workdir.exists():
        shutil.rmtree(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    # tpre saves the .FCStd it is given (solver settings), so work on a copy
    local = workdir / Path(fcstd).name
    shutil.copy(fcstd, local)

    cmd = ["tpre", "parse-fcstd", "--fcstd", local, "--inp", workdir, "--log", workdir]
    if cavity_radiation:
        cmd.append("--cavity-radiation")
    if force:
        cmd.append("--force")
    _run(cmd, workdir, workdir / "01_parse.log")
    sim = json.loads((workdir / "simulation.json").read_text())
    job = Path(sim["Input file"]).stem
    inp = workdir / f"{job}.inp"
    if not inp.exists():
        raise PipelineError(f"tpre parse-fcstd exited 0 but wrote no {inp.name}")
    if inp_patch:
        inp_patch(inp)

    p = _run(["ccx", "-i", job], workdir, workdir / "02_ccx.log")
    if "*ERROR" in p.stdout or "*ERROR" in p.stderr:
        raise PipelineError(f"ccx reported an error, see {workdir / '02_ccx.log'}")

    _run(["tpost", "convert", "--frd", f"{job}.frd", "--vtk", "vtk"], workdir,
         workdir / "03_convert.log")
    _run(["tpost", "csv", "--vtk", "vtk", "--sta", f"{job}.sta",
          "--output", "temperature.csv"], workdir, workdir / "04_csv.log")
    return Result(workdir)


def patch_cavity_radiation(inp: Path) -> int:
    """Kept for callers of the validation API; the implementation now lives in
    the project (src/preprocessing/cavity_radiation.py, tpre --cavity-radiation)."""
    from preprocessing.cavity_radiation import patch_cavity_radiation as patch

    try:
        return patch(inp)
    except ValueError as e:
        raise PipelineError(str(e)) from e
