"""Model checks in src/preprocessing/check_inp.py and cavity_radiation.py,
on tiny hand-written .inp files (no FreeCAD needed)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from preprocessing import check_inp  # noqa: E402
from preprocessing.cavity_radiation import patch_cavity_radiation  # noqa: E402

# Two tetrahedra sharing face (1, 2, 3): one conformal part
SHARED = """*Node, NSET=Nall
1, 0, 0, 0
2, 1, 0, 0
3, 0, 1, 0
4, 0, 0, 1
5, 0, 0, -1
*Element, TYPE=C3D4, ELSET=Evolumes
1, 1, 2, 3, 4
2, 1, 3, 2, 5
"""

# Same two tets, but the second one has its own copies of the shared nodes:
# geometrically touching, no shared nodes (an unfused compound)
UNFUSED = """*Node, NSET=Nall
1, 0, 0, 0
2, 1, 0, 0
3, 0, 1, 0
4, 0, 0, 1
11, 0, 0, 0
12, 1, 0, 0
13, 0, 1, 0
15, 0, 0, -1
*Element, TYPE=C3D4, ELSET=Evolumes
1, 1, 2, 3, 4
2, 11, 13, 12, 15
"""

# Two tets 10 units apart (e.g. heater and block across an air gap)
SEPARATED = UNFUSED.replace("11, 0, 0, 0", "11, 10, 0, 0").replace(
    "12, 1, 0, 0", "12, 11, 0, 0").replace("13, 0, 1, 0", "13, 10, 1, 0").replace(
    "15, 0, 0, -1", "15, 10, 0, -1")


def write(tmp_path, text, name="m.inp"):
    p = tmp_path / name
    p.write_text(text)
    return p


def test_conformal_mesh_is_one_part(tmp_path):
    res = check_inp.check(write(tmp_path, SHARED))
    assert res.info["parts"] == 1
    assert not res.errors and not res.warnings


def test_touching_unfused_parts_are_an_error(tmp_path):
    res = check_inp.check(write(tmp_path, UNFUSED))
    assert res.info["parts"] == 2
    assert any("share no nodes" in e for e in res.errors)


def test_separated_parts_only_warn(tmp_path):
    res = check_inp.check(write(tmp_path, SEPARATED))
    assert res.info["parts"] == 2
    assert not res.errors
    assert any("radiation" in w for w in res.warnings)


def test_film_on_internal_face_is_an_error(tmp_path):
    # F1 of element 1 = nodes (1, 2, 3): the face shared with element 2
    text = SHARED + "*FILM\n** Heat flux on face Plate:Face6\n1,F1,298.15,0.01\n1,F2,298.15,0.01\n"
    res = check_inp.check(write(tmp_path, text))
    assert res.info["hidden_bc_faces"] == 1
    assert any("Plate:Face6" in e and "1 of 2" in e for e in res.errors)


def test_film_on_outer_faces_is_fine(tmp_path):
    text = SHARED + "*FILM\n** Heat flux on face Plate:Face5\n1,F2,298.15,0.01\n1,F3,298.15,0.01\n"
    res = check_inp.check(write(tmp_path, text))
    assert res.info["hidden_bc_faces"] == 0
    assert not res.errors


def test_cflux_total(tmp_path):
    text = SHARED + "*NSET,NSET=Power\n1,\n2,\n3,\n4,\n*CFLUX\nPower,11,500\n"
    res = check_inp.check(write(tmp_path, text))
    assert res.info["cflux_total_W"] == pytest.approx(2.0)  # 4 nodes x 500 mW


def test_cavity_radiation_patch(tmp_path):
    text = SHARED + "*RADIATE\n** Heat flux on face Hot:Face6\n1,R2,298.15,0.9\n1,R3CR,298.15,0.9\n"
    p = write(tmp_path, text)
    assert patch_cavity_radiation(p) == 1
    out = p.read_text()
    assert "1,R2CR,298.15,0.9" in out and "R3CRCR" not in out


def test_cavity_radiation_needs_radiation_faces(tmp_path):
    with pytest.raises(ValueError):
        patch_cavity_radiation(write(tmp_path, SHARED))
