"""Silent-failure audit (validation plan section 1).

Each check reproduces one suspected failure and reports CONFIRMED or NOT
REPRODUCED, plus the evidence it saw. Checks that need CalculiX, FreeCAD or
ParaView are listed as NEEDS TOOLCHAIN.

FreeCAD is stubbed (see _stubs.py), so this runs with plain Python + bash:
    python validation/silent/run_silent_audit.py
Results are written to validation/silent/results.md.
"""

import io
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(HERE))

import _stubs  # noqa: E402

_stubs.install(SRC)
logging.getLogger().addHandler(logging.NullHandler())  # keep stdout quiet

from preprocessing import parse_fcstd  # noqa: E402
from preprocessing import bisection  # noqa: E402
from preprocessing import report  # noqa: E402
from preprocessing.calculate_coef import calculate_film_coefficient  # noqa: E402

CONFIRMED = "CONFIRMED"
STATIC = "CONFIRMED (static)"
NOT_REPRODUCED = "NOT REPRODUCED"
TOOLCHAIN = "NEEDS TOOLCHAIN"

RESULTS = []


def check(sid, title, severity):
    def wrap(fn):
        def run():
            try:
                status, evidence = fn()
            except Exception as e:  # a crashing check is itself a finding
                status, evidence = "CHECK ERROR", f"{type(e).__name__}: {e}"
            RESULTS.append((sid, title, severity, status, evidence))

        run.sid = sid
        return run

    return wrap


class LogCapture(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append(record)

    def __enter__(self):
        root = logging.getLogger()
        self._old = root.level
        root.setLevel(logging.DEBUG)
        root.addHandler(self)
        return self

    def __exit__(self, *exc):
        root = logging.getLogger()
        root.removeHandler(self)
        root.setLevel(self._old)

    def at_least(self, level):
        return [r for r in self.records if r.levelno >= level]


def base_doc(path, objects=None):
    objs = objects or [
        _stubs.solver(),
        _stubs.material("FR4", 0.3),
        _stubs.initial_temperature(298.15),
        _stubs.heat_flux("top"),
    ]
    doc = _stubs.Doc(objs, path=str(path))
    _stubs.CURRENT_DOC["doc"] = doc
    return doc


class FakePopen:
    def __init__(self, *a, **k):
        pass

    def communicate(self):
        return (b"\nThis is Version 2.20\n\n", None)


# --------------------------------------------------------------------------- S1
@check("S1", "Prerequisite failure still exits OK; stale .inp kept", "S-Blocker")
def s1():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        stale = d / "FEMMeshGmsh.inp"
        stale.write_text("** stale input from a previous run\n")
        old_mtime = stale.stat().st_mtime
        base_doc(d / "design.FCStd")
        _stubs.FakeFea.prerequisite_message = "Missing mesh object"
        _stubs.FakeFea.inp_written = 0
        real_popen = parse_fcstd.subprocess.Popen
        parse_fcstd.subprocess.Popen = FakePopen
        try:
            with LogCapture() as logs:
                parse_fcstd.main(str(d / "design.FCStd"), str(d), str(d))
        finally:
            parse_fcstd.subprocess.Popen = real_popen
            _stubs.FakeFea.prerequisite_message = ""
        errors = [r.getMessage() for r in logs.at_least(logging.ERROR)]
        sim_json = (d / "simulation.json").exists()
        unchanged = stale.stat().st_mtime == old_mtime
    if sim_json and unchanged and _stubs.FakeFea.inp_written == 0:
        return CONFIRMED, (
            f"main() returned normally (CLI exit 0); logged {errors}; "
            "simulation.json written; stale FEMMeshGmsh.inp left in place for ccx"
        )
    return NOT_REPRODUCED, f"sim_json={sim_json} unchanged={unchanged}"


# ------------------------------------------------------------------- S2 / S3
def _find_coef_harness(stale_csv_max_c, timeout=90):
    """Run the real find_coef.sh with stubbed tools on PATH.

    ccx, ccx2paraview and tpost always fail. tpre bisect-temperature runs the
    real bisection code. Returns (rc, iterations, bisect rcs, stderr, files).
    """
    bash = shutil.which("bash")
    tmp = Path(tempfile.mkdtemp(prefix="find_coef_"))
    designs, stubs = tmp / "designs", tmp / "bin"
    designs.mkdir()
    stubs.mkdir()
    (designs / "config.json").write_text(
        json.dumps(
            {
                "film": {"top": [20, "horizontal_up"]},
                "temperature": {"max": 160, "min": 20, "tolerance": 2},
            }
        )
    )
    if stale_csv_max_c is not None:
        rows = [",time [s],max [K],max [C]"]
        for i, t in enumerate([30.0, 40.0, stale_csv_max_c]):
            rows.append(f"{i},{i * 10.0},{t + 273.15},{t}")
        (designs / "temperature.csv").write_text("\n".join(rows) + "\n")

    def stub(name, body):
        (stubs / name).write_text("#!/bin/bash\n" + body + "\n", newline="\n")

    stub("ccx", "exit 1")
    stub("ccx2paraview", "exit 1")
    stub("tpost", "exit 1")
    stub(
        "jq",
        'key=max; case "$2" in *min*) key=min;; esac\n'
        '"$PYTHON" -c "import json,sys; '
        "print(json.load(open(sys.argv[1]))['temperature'][sys.argv[2]])\" "
        '"$3" "$key"',
    )
    stub(
        "tpre",
        'cmd=$1; shift\n'
        'case "$cmd" in\n'
        "  calc-film-coefs)\n"
        '    n=$(( $(cat "$HARNESS/iterations" 2>/dev/null || echo 0) + 1 ))\n'
        '    echo $n > "$HARNESS/iterations"\n'
        '    if [ "$n" -gt 25 ]; then kill -TERM $PPID; exit 1; fi ;;\n'
        "  bisect-temperature)\n"
        '    while [ $# -gt 0 ]; do case "$1" in --config) cfg=$2; shift 2;; '
        "--csv) csv=$2; shift 2;; *) shift;; esac; done\n"
        '    "$PYTHON" -c "import sys, logging; logging.basicConfig(level=logging.INFO); '
        "sys.path.insert(0, sys.argv[3]); from preprocessing import bisection; "
        'bisection.bisect_temperature(sys.argv[1], sys.argv[2])" '
        '"$cfg" "$csv" "$SRC" 2>>"$HARNESS/bisect_stderr.txt"\n'
        "    rc=$?\n"
        '    echo $rc >> "$HARNESS/bisect_rc"\n'
        "    exit $rc ;;\n"
        "esac\n"
        "exit 0",
    )
    env = dict(os.environ)
    env.pop("ITERATION", None)
    env.update(
        PATH=str(stubs) + os.pathsep + env["PATH"],
        PYTHON=Path(sys.executable).as_posix(),
        SRC=SRC.as_posix(),
        HARNESS=tmp.as_posix(),
    )
    script = (SRC / "preprocessing" / "find_coef.sh").as_posix()
    start = time.time()
    try:
        proc = subprocess.run(
            [bash, script, "design.FCStd", designs.as_posix()],
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        rc = proc.returncode
    except subprocess.TimeoutExpired:
        rc = "timeout"
    elapsed = time.time() - start

    def read(name):
        p = tmp / name
        return p.read_text() if p.exists() else ""

    iterations = int(read("iterations").strip() or 0)
    bisect_rcs = read("bisect_rc").split()
    stderr = read("bisect_stderr.txt")
    config = json.loads((designs / "config.json").read_text())
    temp_config_left = (designs / "temp_config.json").exists()
    shutil.rmtree(tmp, ignore_errors=True)
    return rc, iterations, bisect_rcs, stderr, config, temp_config_left, elapsed


@check("S2", "find_coef.sh converges on stale data when ccx fails", "S-Blocker")
def s2():
    rc, its, rcs, err, config, left, _ = _find_coef_harness(stale_csv_max_c=50.0)
    conv = re.findall(r"CONVERGENCE T = ([\d.]+)", err)
    if rc == 0 and conv:
        return CONFIRMED, (
            f"ccx/ccx2paraview/tpost failed on every iteration, yet the loop reported "
            f"'CONVERGENCE T = {conv[-1]}' after {its} iterations and exited {rc}. "
            f"Result saved to config.json: {'bisected_temp' in config}; "
            f"temp_config.json left: {left} (S3: result lost)"
        )
    return NOT_REPRODUCED, f"rc={rc} iterations={its} bisect rcs={rcs}"


@check("S3a", "Python crash in bisection loops forever (exit 1 == retry)", "S-Major")
def s3a():
    rc, its, rcs, err, *_ = _find_coef_harness(stale_csv_max_c=None)
    last_err = err.strip().splitlines()[-1] if err.strip() else ""
    if its >= 25 and set(rcs) == {"1"}:
        return CONFIRMED, (
            f"bisection crashed every time ({last_err}); exit code 1 was treated as "
            f"'no convergence'; harness had to kill the loop after {its} iterations"
        )
    return NOT_REPRODUCED, f"rc={rc} iterations={its} bisect rcs={rcs}"


@check("S3b", "Out-of-range bisection result makes find_coef.sh exit 0", "S-Major")
def s3b():
    rc, its, rcs, err, *_ = _find_coef_harness(stale_csv_max_c=200.0)
    if rc == 0 and rcs and rcs[-1] == "2":
        return CONFIRMED, (
            "bisection exited 2 ('above the upper bound'), find_coef.sh exited 0, "
            "so CI or a wrapping script sees success"
        )
    return NOT_REPRODUCED, f"rc={rc} bisect rcs={rcs}"


# --------------------------------------------------------------------------- S7
@check("S7", "tpost preview/animation/generate-gltf ignore pvpython exit code", "S-Major")
def s7():
    text = (SRC / "postprocessing" / "main.py").read_text()
    calls = re.findall(r"subprocess\.run\((.*)\)", text)
    unchecked = [c for c in calls if "check=True" not in c]
    if unchecked:
        return STATIC, f"{len(unchecked)} subprocess.run(...) calls without check=True"
    return NOT_REPRODUCED, ""


# --------------------------------------------------------------------------- S8
@check("S8", "glTF colour range and scale-bar labels disagree", "S-Major")
def s8():
    gltf = (SRC / "postprocessing" / "generate_gltf.py").read_text()
    svg = (SRC / "postprocessing" / "generate_svg_palette.py").read_text()
    m = re.search(r"temperature_displayer\([^)]*?([\d.]+),\s*([\d.]+)\)", gltf)
    tmax = re.search(r"^tmax = (\d+)", svg, re.M)
    tmin = re.search(r"^tmin = (\d+)", svg, re.M)
    if m and tmax and tmin:
        lo, hi = float(m.group(1)) - 273.15, float(m.group(2)) - 273.15
        if (lo, hi) != (float(tmin.group(1)), float(tmax.group(1))):
            return STATIC, (
                f"glTF colours mapped to {lo:.0f}-{hi:.0f} C (hardcoded, function "
                f"args ignored); scale bar labelled {tmin.group(1)}-{tmax.group(1)} C. "
                f"A 150 C node is drawn as {100 * 150 / hi:.0f}% of the colour range, "
                "but the legend reads it as the top of the scale"
            )
    return NOT_REPRODUCED, ""


# --------------------------------------------------------------------------- S9
@check("S9", "Steady-state analysis silently forced to transient", "S-Major")
def s9():
    slv = _stubs.solver(steady=True)
    with LogCapture() as logs:
        parse_fcstd.set_solver(_stubs.Doc([slv]))
    warnings = logs.at_least(logging.WARNING)
    infos = [r.getMessage() for r in logs.records]
    if slv.ThermoMechSteadyState is False and not warnings:
        return CONFIRMED, (
            "ThermoMechSteadyState True -> False with no warning; "
            f"IterationsMaximum 100 -> {slv.IterationsMaximum} ({infos})"
        )
    return NOT_REPRODUCED, f"steady={slv.ThermoMechSteadyState}"


# -------------------------------------------------------------------------- S10
@check("S10", "Multi-material and body heat source misreported", "S-Major")
def s10():
    doc = _stubs.Doc(
        [
            _stubs.material("FR4", 0.3),
            _stubs.material("Copper", 390),
            _stubs.Obj(
                "Fem::ConstraintBodyHeatSource", "U1_power", HeatSource=1.0e6
            ),
        ]
    )
    mat = parse_fcstd.get_material(doc)
    src = parse_fcstd.get_heat_source(doc)
    if mat.get("Name:") == "Copper" and src.get("Total") == 0:
        return CONFIRMED, (
            f"2 materials (FR4, Copper) reported as one: {mat.get('Name:')}; "
            f"body heat source ignored, report shows Total = {src['Total']} W"
        )
    return NOT_REPRODUCED, f"material={mat} heat={src}"


# -------------------------------------------------------------------------- S11
@check("S11", "Film coefficients use initial temperature as ambient", "S-Major")
def s11():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        flux = _stubs.heat_flux("top", film=0.0, ambient_k=298.15)
        base_doc(
            d / "design.FCStd",
            [_stubs.solver(), _stubs.initial_temperature(313.15), flux],
        )
        cfg = d / "config.json"
        cfg.write_text(
            json.dumps(
                {
                    "film": {"top": [20, "horizontal_up"]},
                    "temperature": {"min": 20, "max": 160},
                }
            )
        )
        parse_fcstd.calc_film_coefs(str(d / "design.FCStd"), str(cfg))
    h_initial = calculate_film_coefficient(40.0, 90.0, "horizontal_up", 20)
    h_ambient = calculate_film_coefficient(25.0, 90.0, "horizontal_up", 20)
    if abs(flux.FilmCoef - h_initial) < 1e-9:
        return CONFIRMED, (
            f"initial T 40 C, constraint ambient 25 C: h = {flux.FilmCoef:.2f} W/m2K "
            f"computed from 40 C; with the real ambient it is {h_ambient:.2f} "
            f"({100 * (flux.FilmCoef / h_ambient - 1):+.1f} %)"
        )
    return NOT_REPRODUCED, f"h={flux.FilmCoef}"


# -------------------------------------------------------------------------- S12
@check("S12", "Bisection accepts a run that has not reached steady state", "S-Major")
def s12():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        csv = d / "temperature.csv"
        rows = [",time [s],max [K],max [C]"]
        temps = [25 + 2.0 * i for i in range(33)]  # still rising 2 K/step
        for i, t in enumerate(temps):
            rows.append(f"{i},{i * 10.0},{t + 273.15},{t}")
        csv.write_text("\n".join(rows) + "\n")
        cfg = d / "config.json"
        cfg.write_text(
            json.dumps(
                {"film": {}, "temperature": {"min": 20, "max": 160, "tolerance": 2}}
            )
        )
        os.environ.update(ITERATION="1", TMIN="20", TMAX="160")
        try:
            with LogCapture() as logs:
                try:
                    bisection.bisect_temperature(str(cfg), str(csv))
                    code = None
                except SystemExit as e:
                    code = e.code
        finally:
            for k in ("ITERATION", "TMIN", "TMAX"):
                os.environ.pop(k, None)
    warned = logs.at_least(logging.WARNING)
    if code == 0 and not warned:
        return CONFIRMED, (
            f"final max T {temps[-1]} C still rising {temps[-1] - temps[-2]} K per "
            "output step; bisection declared convergence (exit 0) with no "
            "steady-state warning"
        )
    return NOT_REPRODUCED, f"exit={code}"


# -------------------------------------------------------------------------- S13
@check("S13", "Film coefficient: cryptic orientation error, no Ra range check", "S-Minor")
def s13():
    try:
        calculate_film_coefficient(25.0, 65.0, "Vertical", 50.0)
        typo = "accepted"
    except Exception as e:
        typo = type(e).__name__
    with LogCapture() as logs:
        calculate_film_coefficient(25.0, 30.0, "vertical", 3.0)  # Ra ~ 1e2
    warned = logs.at_least(logging.WARNING)
    if typo != "ValueError" and not warned:
        return CONFIRMED, (
            f"orientation 'Vertical' -> {typo}; Ra ~1e2 (valid range 1e4-1e9) "
            "accepted without warning. See B1 table for bias vs textbook"
        )
    return NOT_REPRODUCED, f"typo={typo} warned={bool(warned)}"


# -------------------------------------------------------------------------- S14
@check("S14", "Saving deletes every *.FCStd1/*.FCBak in the folder", "S-Major")
def s14():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        victims = [d / "other_board.FCBak", d / "other_board.FCStd1"]
        for v in victims:
            v.write_text("someone's backup")
        doc = base_doc(d / "design.FCStd")
        parse_fcstd.save_fcstd(doc, str(d / "design.FCStd"))
        gone = [v.name for v in victims if not v.exists()]
    if gone:
        return CONFIRMED, f"deleted unrelated backups: {gone}"
    return NOT_REPRODUCED, ""


# -------------------------------------------------------------------------- S15
@check("S15", "tpre report overwrites README.md in the target dir", "S-Major")
def s15():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        (d / "README.md").write_text("# My project notes\nimportant\n")
        (d / "simulation.json").write_text(json.dumps({"Design": "x"}))
        (d / "config.json").write_text(json.dumps({}))
        report.main(str(d / "simulation.json"), str(d / "config.json"), str(d))
        content = (d / "README.md").read_text()
    if "important" not in content:
        return CONFIRMED, "existing README.md replaced by the simulation report"
    return NOT_REPRODUCED, ""


# -------------------------------------------------------------------------- S16
@check("S16", "FREECAD_PATH unset only prints, fails later", "S-Minor")
def s16():
    code = (
        "import sys, types; t = types.ModuleType('typer'); t.run = lambda f: None; "
        "sys.modules['typer'] = t; sys.path.insert(0, sys.argv[1]); "
        "from preprocessing import parse_fcstd; parse_fcstd.open_fcstd('x.FCStd')"
    )
    env = dict(os.environ)
    env.pop("FREECAD_PATH", None)
    p = subprocess.run(
        [sys.executable, "-c", code, str(SRC)], env=env, capture_output=True, text=True
    )
    last = p.stderr.strip().splitlines()[-1] if p.stderr.strip() else ""
    if "FREECAD_PATH is not set" in p.stdout and "NameError" in p.stderr:
        return CONFIRMED, (
            f"import printed a hint and continued; failed later with '{last}'. "
            "(On Python 3.11 the NameError fires at import time from annotations)"
        )
    return NOT_REPRODUCED, f"stdout={p.stdout!r} stderr={last!r}"


# -------------------------------------------------------------------------- S17
@check("S17", "compare-csv only calls plt.show(); nothing saved headless", "S-Minor")
def s17():
    text = (SRC / "postprocessing" / "plot_comparison.py").read_text()
    if "plt.show()" in text and "savefig" not in text:
        return STATIC, "no savefig; on a headless box/WSL without a display the plot is lost"
    return NOT_REPRODUCED, ""


# -------------------------------------------------------------------------- S18
@check("S18", "plot-meas console script points to a missing module", "S-Minor")
def s18():
    toml = (ROOT / "pyproject.toml").read_text()
    m = re.search(r'plot-meas\s*=\s*"([\w.]+):', toml)
    if m:
        module = SRC / (m.group(1).replace(".", "/") + ".py")
        if not module.exists():
            return STATIC, f"{m.group(1)} does not exist; `plot-meas` crashes on start"
    return NOT_REPRODUCED, ""


# -------------------------------------------------------------------------- S22
@check("S22", "README documents commands that do not exist", "S-Minor")
def s22():
    readme = (ROOT / "README.md").read_text()

    def commands(path):
        text = path.read_text()
        names = re.findall(r"@app\.command\([^)]*\)\s*\ndef (\w+)", text)
        return {n.replace("_", "-") for n in names}

    known = {
        "tpre": commands(SRC / "preprocessing" / "main.py"),
        "tpost": commands(SRC / "postprocessing" / "main.py"),
    }
    missing = sorted(
        {
            f"{tool} {cmd}"
            for tool, cmd in re.findall(r"`?(tpre|tpost) ([a-z][\w-]*)", readme)
            if cmd not in known[tool]
        }
    )
    if missing:
        return STATIC, f"documented but not defined: {missing}"
    return NOT_REPRODUCED, ""


# ------------------------------------------------------------- toolchain-only
TOOLCHAIN_ONLY = [
    ("S4", "Hardcoded FEMMeshGmsh name", "S-Major"),
    ("S5", "Stale .vtk files mixed into new CSV", "S-Blocker"),
    ("S6", ".sta/.vtk misalignment when output frequency != 1", "S-Blocker"),
    ("S19", "Blender loop duplicates frames when pcbooth fails", "S-Minor"),
    ("S20", "CFlux total power vs mesh density", "S-Blocker"),
    ("S21", "Non-conformal mesh: no conduction between solids", "S-Blocker"),
]


def main():
    checks = [
        s1, s2, s3a, s3b, s7, s8, s9, s10, s11, s12, s13, s14, s15, s16, s17,
        s18, s22,
    ]
    for c in checks:
        with redirect_stdout(io.StringIO()):
            c()
    for sid, title, sev in TOOLCHAIN_ONLY:
        RESULTS.append((sid, title, sev, TOOLCHAIN, "requires ccx/FreeCAD/ParaView"))

    def key(r):
        m = re.match(r"S(\d+)(\w*)", r[0])
        return int(m.group(1)), m.group(2)

    RESULTS.sort(key=key)
    lines = [
        "# Silent-failure audit results",
        "",
        "Generated by `python validation/silent/run_silent_audit.py`. "
        "FreeCAD is stubbed; ccx/ParaView-dependent checks are pending.",
        "",
        "| ID | Finding | Severity | Status | Evidence |",
        "|---|---|---|---|---|",
    ]
    for sid, title, sev, status, ev in RESULTS:
        ev = ev.replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {sid} | {title} | {sev} | {status} | {ev} |")
    out = "\n".join(lines) + "\n"
    (HERE / "results.md").write_text(out, encoding="utf-8")
    for sid, title, sev, status, _ in RESULTS:
        print(f"{sid:5} {status:20} {sev:10} {title}")


if __name__ == "__main__":
    main()
