"""Surface-to-surface ("cavity") radiation for FreeCAD-written .inp files.

FreeCAD only writes radiation to a fixed ambient temperature:
    *RADIATE
    elem,R<face>,T_ambient,emissivity
CalculiX's R<face>CR makes every such face exchange radiation with all the
others using view factors it computes; the part of a face's view that sees no
other cavity face still radiates to T_ambient.
"""

from pathlib import Path


def patch_cavity_radiation(inp) -> int:
    """Convert every *RADIATE face in `inp` to cavity radiation, in place.
    Returns the number of faces converted; raises if there were none."""
    inp = Path(inp)
    out, in_radiate, n = [], False, 0
    for line in inp.read_text().splitlines():
        s = line.strip()
        if s.startswith("**"):  # comment, FreeCAD writes these inside blocks
            pass
        elif s.startswith("*"):
            in_radiate = s.upper().startswith("*RADIATE")
        elif in_radiate and s:
            parts = s.split(",")
            face = parts[1].strip().upper() if len(parts) >= 2 else ""
            if face.startswith("R") and not face.endswith("CR"):
                parts[1] = parts[1].strip() + "CR"
                line = ",".join(parts)
                n += 1
        out.append(line)
    if n == 0:
        raise ValueError(
            f"--cavity-radiation: no radiation faces found in {inp.name}. Add a FreeCAD "
            "heat flux constraint of type Radiation on the faces that should see each other.")
    inp.write_text("\n".join(out) + "\n")
    return n
