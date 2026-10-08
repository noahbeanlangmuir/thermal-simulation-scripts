import sys
import os
import shutil
import typer
import json
import subprocess
import logging
from pathlib import Path
from preprocessing.calculate_coef import calculate_film_coefficient
from preprocessing.common import get_config
from preprocessing import check_inp
from preprocessing.cavity_radiation import patch_cavity_radiation
from contextlib import redirect_stdout
from typing import Dict, Optional

# FREECAD_PATH points to sqashrootfs (extracted freecad appimage)
if not os.environ.get("FREECAD_PATH"):
    raise ImportError(
        "FREECAD_PATH is not set. Export it to the extracted FreeCAD 1.0 AppImage folder "
        "(e.g. export FREECAD_PATH=/usr/local/share/freecad), see validation/SETUP.md."
    )
freecad_path = Path(os.environ["FREECAD_PATH"])
# Importing FreeCAD puts its bundled bin dir first on PATH; remember the user's ccx
USER_CCX = shutil.which("ccx")
sys.path.insert(0, str(freecad_path / "usr/lib/python3.11/site-packages"))
sys.path.append(str(freecad_path / "usr/lib"))
try:
    import FreeCAD
    from femtools import ccxtools
except ImportError as e:
    raise ImportError(
        f"Could not import FreeCAD from FREECAD_PATH={freecad_path} ({e}). It must point "
        "to the extracted FreeCAD 1.0 py311 AppImage, see validation/SETUP.md."
    ) from e

log = logging.getLogger(__name__)


def get_initial_temperature(doc: FreeCAD) -> float:
    """Returns initial temperature constraint value in Kelvin."""
    for obj in doc.Objects:
        if obj.TypeId == "Fem::ConstraintInitialTemperature":
            return obj.initialTemperature.Value
    else:
        raise Exception("Initial temperature constraint not specified")


def get_heat_source(doc: FreeCAD) -> Dict:
    heat_source = {}
    body_sources = {}
    for obj in doc.Objects:
        if obj.TypeId == "Fem::ConstraintTemperature":
            if obj.CFlux:
                heat_source.update({obj.Label: obj.CFlux.Value / 1000000})
            if obj.Temperature:
                pass
                # FreeCad does not export obj.Temperature to .INP file when the CFLUX constraint is selected
                # but initial value is stored in .FCStd anyway. Support for Temperature constraint is not implemented for now
        if obj.TypeId == "Fem::ConstraintBodyHeatSource":
            body_sources.update({obj.Label: str(getattr(obj, "HeatSource", ""))})
    total_heat = sum(heat_source.values())
    heat_source.update({"Total": total_heat})
    if body_sources:
        heat_source.update({"Body heat sources (not in Total)": body_sources})
    return heat_source


def get_heat_flux(doc: FreeCAD) -> Dict:
    flux = {}
    for obj in doc.Objects:
        if obj.TypeId == "Fem::ConstraintHeatflux":
            if obj.FilmCoef and obj.ConstraintType == "Convection":
                flux.update({obj.Label: {"Film Coef": obj.FilmCoef}})
            if obj.Emissivity and obj.ConstraintType == "Radiation":
                flux.update({obj.Label: {"Emissivity": obj.Emissivity}})
    return flux


def open_fcstd(fcstd: str) -> FreeCAD:
    fcstd_path = Path(fcstd).resolve()
    return FreeCAD.openDocument(fcstd_path.as_posix())


def save_fcstd(doc: FreeCAD, fcstd: str) -> None:
    doc.save()
    # FreeCad creates backup files on save - remove this design's only
    path = Path(fcstd).resolve()
    for file in path.parent.iterdir():
        name = file.name
        own_backup = name == path.name + "1" or (
            name.startswith(path.stem + ".") and name.endswith(".FCBak")
        )
        if own_backup:
            file.unlink()


def generate_inp(inp: str) -> Path:
    """Write the .inp for the active analysis; returns its path."""
    fea = ccxtools.FemToolsCcx()
    fea.update_objects()
    mesh = getattr(fea, "mesh", None)
    inp_file = Path(inp) / f"{getattr(mesh, 'Name', 'FEMMeshGmsh')}.inp"
    # never leave an older .inp that could be solved by mistake
    if inp_file.exists():
        inp_file.unlink()
    logging.info(f"Setting up working directory: {inp}")
    fea.setup_working_dir(inp)
    logging.info("Setting up CCX solver...")
    fea.setup_ccx()
    logging.info("Checking prerequisites...")
    message = fea.check_prerequisites()
    if message:
        raise RuntimeError(f"FreeCAD prerequisite check failed, no .inp written: {message}")
    fea.purge_results()
    logging.info("Writing .inp file...")
    # Remove stdout
    with open(os.devnull, "w") as devnull:
        with redirect_stdout(devnull):
            fea.write_inp_file()
    written = Path(getattr(fea, "inp_file_name", "") or inp_file)
    if not written.exists():
        raise RuntimeError(f"FreeCAD reported success but {written} was not written")
    logging.info(f"Successfully generated {written}")
    return written


def set_coef(fcstd: str, coef_type: str, coef_value: float, coef_name: str) -> None:
    """Save coef with given type and value to .FCStd."""
    doc = open_fcstd(fcstd)
    # Check if requested name exists in constraints
    if coef_name:
        match_count = 0
        for obj in doc.Objects:
            if obj.TypeId != "Fem::ConstraintHeatflux":
                continue
            if obj.Label == coef_name:
                match_count += 1
        if match_count == 0:
            raise Exception(f"{coef_name} label not in heat flux objects")
    # Set coefficients
    for obj in doc.Objects:
        if obj.TypeId == "Fem::ConstraintHeatflux":
            if coef_name and obj.Label != coef_name:
                continue
            if coef_type == "film":
                obj.ConstraintType = "Convection"
                obj.FilmCoef = coef_value
            if coef_type == "emissivity":
                obj.ConstraintType = "Radiation"
                obj.Emissivity = coef_value
    save_fcstd(doc, fcstd)


def calc_film_coefs(fcstd: str, config_path: str) -> None:
    """Calculate & set new film coefficients for the middle value of a given temperature range."""
    # Get config temp
    config = get_config(config_path)

    # Calculate coeffs for the middle value of temperature range
    temp_mid: float = (
        float(config["temperature"]["max"] + config["temperature"]["min"]) / 2
    )
    doc = open_fcstd(fcstd)
    # Conversion from Kelvin to Celsius
    temp_initial = get_initial_temperature(doc) - 273.15
    ambients = {
        obj.Label: float(getattr(obj, "AmbientTemp", 0) or 0)
        for obj in doc.Objects
        if obj.TypeId == "Fem::ConstraintHeatflux"
    }
    logging.info("Calculating film coefficients...")
    for coef_name in config["film"]:
        if ambients.get(coef_name, 0) > 0:
            temp_fluid = ambients[coef_name] - 273.15
        else:
            temp_fluid = temp_initial
            logging.warning(
                f"{coef_name}: no ambient temperature set on the heat flux constraint, "
                f"using the initial temperature {temp_initial:.2f} C as the air temperature"
            )
        film = calculate_film_coefficient(
            temp_fluid,
            temp_mid,
            config["film"][coef_name][1],
            config["film"][coef_name][0],
        )
        set_coef(fcstd, "film", film, coef_name)
        logging.info(f"{coef_name} = {film}")


def set_solver(doc: FreeCAD) -> Dict:
    """Sets solver parameters & checks timings correctness."""
    solver_configuration = {}
    for obj in doc.Objects:
        if obj.TypeId != "Fem::FemSolverObjectPython":
            continue
        changes = []
        obj.AnalysisType = "thermomech"
        obj.ThermoMechType = "pure heat transfer"
        if obj.ThermoMechSteadyState:
            changes.append("steady state -> transient (tpost needs a time history)")
            logging.warning(
                "Solver was set to steady state; switching to a transient run because the "
                "post-processing needs a time history. Make Time End long enough to settle."
            )
        obj.ThermoMechSteadyState = False
        if getattr(obj, "OutputFrequency", 1) != 1:
            changes.append(f"OutputFrequency {obj.OutputFrequency} -> 1")
            logging.warning(
                f"OutputFrequency was {obj.OutputFrequency}; set to 1 because tpost csv "
                "pairs every result increment with the time steps in the .sta file."
            )
            obj.OutputFrequency = 1
        min_required_steps = int(10000 * (obj.TimeEnd / obj.TimeMaximumStep))
        if min_required_steps > obj.IterationsMaximum:
            logging.info(f"Increased simulation increments to {min_required_steps}")
            obj.IterationsMaximum = min_required_steps

        solver_configuration.update({"ThermoMechType": obj.ThermoMechType})
        solver_configuration.update(
            {"ThermoMechSteadyState": str(obj.ThermoMechSteadyState)}
        )
        solver_configuration.update({"Time End": obj.TimeEnd})
        solver_configuration.update({"Time Initial Step": obj.TimeInitialStep})
        solver_configuration.update({"Time Minimum Step": obj.TimeMinimumStep})
        solver_configuration.update({"Time Maximum Step": obj.TimeMaximumStep})
        solver_configuration.update({"Iterations Maximum": obj.IterationsMaximum})
        if changes:
            solver_configuration.update({"Changed by tpre": changes})
    if not solver_configuration:
        raise Exception("Solver object not Found. Add ccx solver in .FCStd")
    return solver_configuration


def get_material(doc: FreeCAD) -> Dict:
    """Get parameters of every material object in the .FCStd."""
    materials = {}
    for obj in doc.Objects:
        if obj.TypeId != "App::MaterialObjectPython":
            continue
        m = obj.Material
        name = m.get("Name") or obj.Label
        materials[name] = (
            f"conductivity {m.get('ThermalConductivity', '?')}, "
            f"density {m.get('Density', '?')}, "
            f"specific heat {m.get('SpecificHeat', '?')}, "
            f"expansion {m.get('ThermalExpansionCoefficient', '?')}"
        )

    if not materials:
        raise Exception("Material object not Found. Add material constraint in .FCStd")
    return materials


def ccx_version(ccx: Optional[str]) -> str:
    if not ccx:
        return "not found on PATH"
    out = subprocess.Popen(args=[ccx, "-v"], stdout=subprocess.PIPE).communicate()[0]
    return out.decode("utf-8").removeprefix("\nThis is Version ").removesuffix("\n\n").strip()


def main(
    fcstd: str,
    inp: str,
    log: str,
    cavity_radiation: bool = False,
    force: bool = False,
) -> None:
    inp_path = Path(inp).resolve()
    log_path = Path(log).resolve()
    doc = open_fcstd(fcstd)
    # Get tools versions
    freecad_version = FreeCAD.Version()
    freecad_version = f"{freecad_version[0]}.{freecad_version[1]}.{freecad_version[2]} @{freecad_version[7]}"
    bundled_ccx = freecad_path / "usr/bin/ccx"
    if USER_CCX is None:
        logging.warning(
            "ccx is not on your PATH, so you cannot run the solver."
            + (f" FreeCAD bundles one: {bundled_ccx}" if bundled_ccx.exists() else "")
        )
    # Generate simulation.json
    params: Dict = {}
    params["Solver Configuration"] = set_solver(doc)
    params["Design"] = Path(fcstd).resolve().stem
    params["Tools"] = {
        "FreeCad": freecad_version,
        "CalculiX": ccx_version(USER_CCX),
        "CalculiX path": USER_CCX or "",
    }
    params["Heat Dissipation"] = get_heat_flux(doc)
    params["Heat Source"] = get_heat_source(doc)
    params["Material"] = get_material(doc)
    params["Initial Temperature"] = get_initial_temperature(doc)

    save_fcstd(doc, fcstd)
    # Generate inp from updated .FCStd
    inp_file = generate_inp(inp_path.as_posix())
    params["Input file"] = inp_file.name

    if cavity_radiation:
        n = patch_cavity_radiation(inp_file)
        logging.info(f"Cavity radiation: {n} faces exchange radiation with each other")
        params["Cavity radiation faces"] = n

    result = check_inp.check(inp_file)
    result.log()
    params["Checks"] = {**result.info, "errors": result.errors, "warnings": result.warnings}

    # Save simulation.json
    with open((log_path / "simulation.json").as_posix(), "w") as f:
        json.dump(params, f, indent=4)

    if result.errors and not force:
        inp_file.unlink()
        raise SystemExit(
            f"{len(result.errors)} model error(s) above: {inp_file.name} was removed so it "
            "cannot be solved by mistake. Fix the model, or re-run with --force to keep it."
        )
    logging.info(f"Next: ccx {inp_file.stem}")


if __name__ == "__main__":
    typer.run(main)
