"""Minimal stand-ins for FreeCAD, femtools and typer.

They let src/preprocessing modules be imported and exercised without a
FreeCAD install. Only the attributes the code under test touches exist.
"""

import os
import sys
import types


class Quantity:
    def __init__(self, value):
        self.Value = value

    def __bool__(self):
        return bool(self.Value)


class Obj:
    def __init__(self, type_id, label="", **attrs):
        self.TypeId = type_id
        self.Label = label
        for k, v in attrs.items():
            setattr(self, k, v)


class Doc:
    def __init__(self, objects, path=None):
        self.Objects = objects
        self.path = path
        self.saved = 0

    def save(self):
        self.saved += 1
        if self.path:
            with open(self.path, "w") as f:
                f.write("fake fcstd\n")


class FakeFea:
    """femtools.ccxtools.FemToolsCcx with a configurable prerequisite result."""

    prerequisite_message = ""
    inp_written = 0

    def update_objects(self):
        pass

    def setup_working_dir(self, path):
        pass

    def setup_ccx(self):
        pass

    def check_prerequisites(self):
        return FakeFea.prerequisite_message

    def purge_results(self):
        pass

    def write_inp_file(self):
        FakeFea.inp_written += 1


CURRENT_DOC = {"doc": None}


def install(src_dir):
    os.environ.setdefault("FREECAD_PATH", "/nonexistent/freecad")

    freecad = types.ModuleType("FreeCAD")
    freecad.openDocument = lambda path: CURRENT_DOC["doc"]
    freecad.Version = lambda: ["1", "0", "0", "", "", "", "", "stub"]
    sys.modules["FreeCAD"] = freecad

    femtools = types.ModuleType("femtools")
    ccxtools = types.ModuleType("femtools.ccxtools")
    ccxtools.FemToolsCcx = FakeFea
    femtools.ccxtools = ccxtools
    sys.modules["femtools"] = femtools
    sys.modules["femtools.ccxtools"] = ccxtools

    typer = types.ModuleType("typer")
    typer.run = lambda f: None
    sys.modules.setdefault("typer", typer)

    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))


def solver(steady=False, time_end=600.0, max_step=10.0, iterations=100):
    return Obj(
        "Fem::FemSolverObjectPython",
        "SolverCcxTools",
        AnalysisType="thermomech",
        ThermoMechType="pure heat transfer",
        ThermoMechSteadyState=steady,
        TimeEnd=time_end,
        TimeInitialStep=1.0,
        TimeMinimumStep=1e-5,
        TimeMaximumStep=max_step,
        IterationsMaximum=iterations,
    )


def material(name, k):
    return Obj(
        "App::MaterialObjectPython",
        name,
        Material={
            "Name": name,
            "Density": "1850 kg/m^3",
            "ThermalConductivity": f"{k} W/m/K",
            "ThermalExpansionCoefficient": "1.4e-05 m/m/K",
            "SpecificHeat": "1100 J/kg/K",
        },
    )


def initial_temperature(kelvin):
    return Obj(
        "Fem::ConstraintInitialTemperature",
        "InitialTemperature",
        initialTemperature=Quantity(kelvin),
    )


def heat_flux(label, film=10.0, ambient_k=298.15):
    return Obj(
        "Fem::ConstraintHeatflux",
        label,
        ConstraintType="Convection",
        FilmCoef=film,
        Emissivity=0.0,
        AmbientTemp=ambient_k,
    )
