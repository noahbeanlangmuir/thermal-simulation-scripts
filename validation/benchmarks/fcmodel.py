"""Build FreeCAD FEM thermal models from scripts.

Benchmarks and case studies describe geometry and boundary conditions in
Python; this module turns them into a .FCStd that the normal tpre/ccx/tpost
flow consumes, exactly as if a user had built it in the FreeCAD GUI.

Requires FREECAD_PATH (see validation/SETUP.md). Lengths in mm, temperatures
in K, power in W, film coefficients in W/m^2/K, heat flux in W/m^2.
"""

import os
import sys
from pathlib import Path

_fc = os.environ.get("FREECAD_PATH")
if not _fc:
    raise RuntimeError("FREECAD_PATH is not set (see validation/SETUP.md)")
sys.path.insert(0, f"{_fc}/usr/lib/python3.11/site-packages")
sys.path.append(f"{_fc}/usr/lib")

import FreeCAD as App  # noqa: E402
import ObjectsFem  # noqa: E402
from femmesh.gmshtools import GmshTools  # noqa: E402

MATERIALS = {
    # name: (k W/m/K, rho kg/m^3, cp J/kg/K)
    "Copper": (390.0, 8960.0, 385.0),
    "Aluminium6061": (167.0, 2700.0, 896.0),
    "FR4": (0.3, 1850.0, 1100.0),
    "MoldCompound": (0.9, 1900.0, 900.0),
}

# Part::Box face names by side
BOX_FACES = {"-x": "Face1", "+x": "Face2", "-y": "Face3", "+y": "Face4",
             "-z": "Face5", "+z": "Face6"}


class Model:
    def __init__(self, name):
        self.doc = App.newDocument(name)
        self.analysis = ObjectsFem.makeAnalysis(self.doc, "Analysis")
        self.boxes = {}
        self.mesh_obj = None
        self.fragments = None

    def _add(self, obj):
        self.analysis.addObject(obj)
        return obj

    # ------------------------------------------------------------- geometry
    def box(self, name, size, pos=(0, 0, 0)):
        b = self.doc.addObject("Part::Box", name)
        b.Length, b.Width, b.Height = size
        b.Placement.Base = App.Vector(*pos)
        self.boxes[name] = b
        self.doc.recompute()
        return b

    def faces(self, box_name, *sides):
        """Reference tuple for the given sides of a box, e.g. faces('A', '+z')."""
        sides = sides or tuple(BOX_FACES)
        return (self.boxes[box_name], tuple(BOX_FACES[s] for s in sides))

    def fuse(self):
        """Join all boxes with BooleanFragments (shared faces, conformal mesh).

        Call before adding constraints that should reference the *split*
        faces of the fused shape (see fragment_faces).
        """
        import BOPTools.SplitFeatures as SF

        self.fragments = SF.makeBooleanFragments(name="Fragments")
        self.fragments.Objects = list(self.boxes.values())
        self.fragments.Mode = "CompSolid"
        self.doc.recompute()
        return self.fragments

    def fragment_faces(self, predicate):
        """Faces of the fused shape for which predicate(face) is true, e.g.
        lambda f: abs(f.CenterOfMass.z - 1.6) < 1e-6 and f.Area > 1000.
        Each face shared by two solids appears once."""
        names = []
        for i, f in enumerate(self.fragments.Shape.Faces, start=1):
            if predicate(f):
                names.append(f"Face{i}")
        if not names:
            raise ValueError("no fragment faces matched")
        return (self.fragments, tuple(names))

    # ------------------------------------------------------------ materials
    def material(self, name, solids, kind=None, k=None, rho=None, cp=None):
        kind = kind or name
        k0, rho0, cp0 = MATERIALS.get(kind, (None, None, None))
        k, rho, cp = k or k0, rho or rho0, cp or cp0
        m = ObjectsFem.makeMaterialSolid(self.doc, name)
        m.Material = {
            "Name": name,
            "ThermalConductivity": f"{k} W/m/K",
            "Density": f"{rho} kg/m^3",
            "SpecificHeat": f"{cp} J/kg/K",
            "ThermalExpansionCoefficient": "2.3e-05 m/m/K",
            "YoungsModulus": "70000 MPa",
            "PoissonRatio": "0.33",
        }
        m.References = [(self.boxes[s], "Solid1") for s in solids]
        return self._add(m)

    # -------------------------------------------------- boundary conditions
    def initial_temperature(self, kelvin):
        c = ObjectsFem.makeConstraintInitialTemperature(self.doc, "InitialTemperature")
        c.initialTemperature = kelvin
        return self._add(c)

    def fixed_temperature(self, name, refs, kelvin):
        c = ObjectsFem.makeConstraintTemperature(self.doc, name)
        c.ConstraintType = "Temperature"
        c.Temperature = kelvin
        c.References = list(refs)
        return self._add(c)

    def cflux(self, name, refs, watts):
        c = ObjectsFem.makeConstraintTemperature(self.doc, name)
        c.ConstraintType = "CFlux"
        c.CFlux = f"{watts} W"
        c.References = list(refs)
        return self._add(c)

    def convection(self, name, refs, film, ambient_k):
        c = ObjectsFem.makeConstraintHeatflux(self.doc, name)
        c.ConstraintType = "Convection"
        c.FilmCoef = film
        c.AmbientTemp = ambient_k
        c.References = list(refs)
        return self._add(c)

    def radiation(self, name, refs, emissivity, ambient_k):
        c = ObjectsFem.makeConstraintHeatflux(self.doc, name)
        c.ConstraintType = "Radiation"
        c.Emissivity = emissivity
        c.AmbientTemp = ambient_k
        c.References = list(refs)
        return self._add(c)

    def dflux(self, name, refs, w_per_m2):
        c = ObjectsFem.makeConstraintHeatflux(self.doc, name)
        c.ConstraintType = "DFlux"
        c.DFlux = w_per_m2
        c.References = list(refs)
        return self._add(c)

    # --------------------------------------------------------------- solver
    def solver(self, time_end, max_step, initial_step=None, output_frequency=1):
        s = ObjectsFem.makeSolverCalculiXCcxTools(self.doc, "CalculiXccxTools")
        s.AnalysisType = "thermomech"
        s.ThermoMechType = "pure heat transfer"
        s.ThermoMechSteadyState = False
        s.TimeEnd = time_end
        s.TimeMaximumStep = max_step
        s.TimeInitialStep = initial_step or min(max_step, time_end / 100)
        s.OutputFrequency = output_frequency
        return self._add(s)

    # ----------------------------------------------------------------- mesh
    def mesh(self, max_size, solids=None, fuse=True, name="FEMMeshGmsh"):
        """Mesh the given solids (default: all).

        fuse=True joins touching solids with BooleanFragments so they share
        nodes (conformal mesh). fuse=False uses a plain compound, which is
        what a user gets by just selecting several parts.
        """
        objs = [self.boxes[s] for s in (solids or self.boxes)]
        if getattr(self, "fragments", None) is not None:
            shape_obj = self.fragments
        elif len(objs) == 1:
            shape_obj = objs[0]
        elif fuse:
            import BOPTools.SplitFeatures as SF

            shape_obj = SF.makeBooleanFragments(name="Fragments")
            shape_obj.Objects = objs
            shape_obj.Mode = "CompSolid"
        else:
            shape_obj = self.doc.addObject("Part::Compound", "Compound")
            shape_obj.Links = objs
        self.doc.recompute()
        m = ObjectsFem.makeMeshGmsh(self.doc, name)
        m.Shape = shape_obj
        m.CharacteristicLengthMax = f"{max_size} mm"
        m.ElementOrder = "2nd"
        self._add(m)
        self.doc.recompute()
        err = GmshTools(m).create_mesh()
        if err:
            raise RuntimeError(f"gmsh failed: {err}")
        self.mesh_obj = m
        return m

    def node_count(self):
        return self.mesh_obj.FemMesh.NodeCount

    def save(self, path):
        path = Path(path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.doc.recompute()
        self.doc.saveAs(path.as_posix())
        return path
