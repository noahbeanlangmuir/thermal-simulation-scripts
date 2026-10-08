"""Sanity checks on a CalculiX .inp written by FreeCAD.

Plain-text parsing only (no FreeCAD), so it runs anywhere:

* disconnected parts: solids that touch but share no mesh nodes pass no heat
  to each other (fuse them with BooleanFragments before meshing)
* hidden faces: *FILM / *RADIATE / *DFLUX applied to faces inside the model
  (e.g. a board face partly covered by a package) remove heat that cannot
  leave there
* heat input: total *CFLUX power, to catch unit or selection mistakes
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path

# Corner nodes (0-based) of each tetrahedron face, CalculiX C3D4/C3D10 numbering
TET_FACES = {1: (0, 1, 2), 2: (0, 3, 1), 3: (1, 3, 2), 4: (2, 3, 0)}
TOUCH_TOL = 1e-3  # mm


@dataclass
class CheckResult:
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    info: dict = field(default_factory=dict)

    def log(self):
        for w in self.warnings:
            logging.warning(w)
        for e in self.errors:
            logging.error(e)


def _keyword(line):
    return line.split(",")[0].strip().upper()


def parse_inp(path):
    """Return nodes {id: (x, y, z)}, tets {id: corner node ids}, nsets
    {name: [ids]}, boundary blocks [(keyword, label, [(elem, face)])] and
    cflux [(nset, mW per node)]."""
    nodes, tets, nsets, blocks, cflux = {}, {}, {}, [], []
    section, label, current = None, "", None
    continued = False  # previous element line ended with "," (continues on next line)
    for raw in Path(path).read_text().splitlines():
        line = raw.strip()
        if not line:
            continue
        if continued:
            continued = line.endswith(",")
            continue
        if line.startswith("**"):
            if section in ("*FILM", "*RADIATE", "*DFLUX") and "face" in line.lower():
                label = line.lstrip("* ").strip()
                current = (section, label, [])
                blocks.append(current)
            continue
        if line.startswith("*"):
            section = _keyword(line)
            current, label = None, ""
            if section == "*ELEMENT":
                etype = line.upper().replace(" ", "")
                section = "*ELEMENT_TET" if "TYPE=C3D10" in etype or "TYPE=C3D4" in etype else "*ELEMENT_OTHER"
            elif section == "*NSET":
                name = [p.split("=")[1] for p in line.split(",") if "NSET=" in p.upper().replace(" ", "")]
                label = name[0].strip() if name else ""
                nsets[label] = []
            elif section in ("*FILM", "*RADIATE", "*DFLUX"):
                current = (section, section, [])
                blocks.append(current)
            continue
        parts = [p.strip() for p in line.split(",") if p.strip()]
        if section == "*NODE":
            nodes[int(parts[0])] = tuple(float(v) for v in parts[1:4])
        elif section in ("*ELEMENT_TET", "*ELEMENT_OTHER"):
            continued = line.endswith(",")
            if section == "*ELEMENT_TET":
                tets[int(parts[0])] = tuple(int(v) for v in parts[1:5])
        elif section == "*NSET":
            nsets[label].extend(int(v) for v in parts if v.lstrip("-").isdigit())
        elif section in ("*FILM", "*RADIATE", "*DFLUX") and current is not None:
            face = parts[1].upper()
            if face[:1] in "FRS" and face[1:2].isdigit():
                current[2].append((int(parts[0]), int(face[1])))
        elif section == "*CFLUX":
            cflux.append((parts[0], float(parts[2])))
    blocks = [b for b in blocks if b[2]]
    return nodes, tets, nsets, blocks, cflux


def _components(tets):
    parent = {}

    def find(a):
        while parent.setdefault(a, a) != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for corners in tets.values():
        r0 = find(corners[0])
        for n in corners[1:]:
            rn = find(n)
            if rn != r0:
                parent[rn] = r0
    groups = {}
    for corners in tets.values():
        groups.setdefault(find(corners[0]), set()).update(corners)
    return list(groups.values())


def _bbox(node_ids, nodes):
    lo, hi = [float("inf")] * 3, [float("-inf")] * 3
    for n in node_ids:
        p = nodes.get(n)
        if p is None:
            continue
        for i in range(3):
            lo[i] = min(lo[i], p[i])
            hi[i] = max(hi[i], p[i])
    return tuple(lo), tuple(hi)


def _boxes_touch(a, b):
    return all(a[0][i] <= b[1][i] + TOUCH_TOL and b[0][i] <= a[1][i] + TOUCH_TOL for i in range(3))


def _fmt_box(box):
    lo, hi = box
    return "x {:.1f}..{:.1f}, y {:.1f}..{:.1f}, z {:.1f}..{:.1f} mm".format(
        lo[0], hi[0], lo[1], hi[1], lo[2], hi[2])


def check(path) -> CheckResult:
    nodes, tets, nsets, blocks, cflux = parse_inp(path)
    res = CheckResult()
    if not tets:
        res.warnings.append(f"{Path(path).name}: no tetrahedral elements found, checks skipped")
        return res

    # --- disconnected parts
    parts = _components(tets)
    boxes = [_bbox(p, nodes) for p in parts]
    res.info["parts"] = len(parts)
    if len(parts) > 1:
        listing = "; ".join(f"part {i + 1}: {_fmt_box(b)}" for i, b in enumerate(boxes))
        touching = [(i, j) for i in range(len(boxes)) for j in range(i + 1, len(boxes))
                    if _boxes_touch(boxes[i], boxes[j])]
        if touching:
            pairs = ", ".join(f"{i + 1} and {j + 1}" for i, j in touching)
            res.errors.append(
                f"Mesh parts {pairs} touch but share no nodes, so no heat flows between them. "
                "Join touching solids with Part > BooleanFragments (Mode: CompSolid) and mesh "
                f"that object. ({listing})")
        else:
            res.warnings.append(
                f"Mesh has {len(parts)} separate parts that exchange heat only by radiation "
                f"(cavity radiation needs --cavity-radiation). ({listing})")

    # --- boundary conditions on internal faces
    face_count = {}
    for corners in tets.values():
        for idx in TET_FACES.values():
            key = frozenset(corners[i] for i in idx)
            face_count[key] = face_count.get(key, 0) + 1
    hidden_total = 0
    for keyword, label, faces in blocks:
        hidden = 0
        for elem, f in faces:
            corners = tets.get(elem)
            if corners and f in TET_FACES:
                key = frozenset(corners[i] for i in TET_FACES[f])
                if face_count.get(key, 0) > 1:
                    hidden += 1
        if hidden:
            hidden_total += hidden
            res.errors.append(
                f"{keyword.lstrip('*')} '{label}': {hidden} of {len(faces)} faces "
                f"({100 * hidden / len(faces):.0f}%) are inside the model, where another part "
                "covers them, so heat is removed where it cannot leave. Reference the split faces "
                "of the BooleanFragments object instead of the original part's face.")
    res.info["hidden_bc_faces"] = hidden_total

    # --- heat input
    total_w = sum(len(nsets.get(name, [])) * mw for name, mw in cflux) / 1000.0
    res.info["cflux_total_W"] = total_w
    if cflux:
        logging.info(f"Total concentrated heat input (CFLUX) = {total_w:.4g} W")
    return res
