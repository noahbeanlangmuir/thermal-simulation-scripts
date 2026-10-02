"""B1: film coefficient calculator (src/preprocessing/calculate_coef.py).

Tests marked xfail(strict=True) document confirmed defects. When a defect is
fixed the test starts passing, strict xfail turns that into a failure, and the
marker should be removed so the test guards the fix.
"""

import logging
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from preprocessing.calculate_coef import calculate_film_coefficient  # noqa: E402
import reference  # noqa: E402

ORIENTATIONS = ["vertical", "horizontal_up", "horizontal_down"]


@pytest.mark.parametrize("orientation", ORIENTATIONS)
@pytest.mark.parametrize("length_mm", [5.0, 20.0, 100.0])
@pytest.mark.parametrize("delta_t", [10.0, 40.0, 80.0])
def test_matches_independent_implementation(orientation, length_mm, delta_t):
    """The code implements its stated correlation without arithmetic/unit errors."""
    h = calculate_film_coefficient(25.0, 25.0 + delta_t, orientation, length_mm)
    expected = reference.h_same_correlation(
        25.0, 25.0 + delta_t, orientation, length_mm
    )
    assert h == pytest.approx(expected, rel=1e-2)


def test_order_of_magnitude_for_typical_board():
    """A 100 mm vertical board 40 K above ambient should see h of ~3-8 W/m2K."""
    h = calculate_film_coefficient(25.0, 65.0, "vertical", 100.0)
    assert 3.0 < h < 8.0


def test_fluid_hotter_than_surface_is_rejected():
    with pytest.raises(Exception):
        calculate_film_coefficient(60.0, 40.0, "vertical", 50.0)


@pytest.mark.parametrize("orientation", ORIENTATIONS)
def test_bias_vs_textbook_is_bounded(orientation):
    """Correlation + fixed 20 C air properties stay within 25 % of textbook
    correlations with film-temperature properties, inside the validity range."""
    h = calculate_film_coefficient(25.0, 65.0, orientation, 50.0)
    h_ref = reference.h_textbook(25.0, 65.0, orientation, 50.0)
    assert math.isclose(h, h_ref, rel_tol=0.25)


@pytest.mark.xfail(
    strict=True, reason="S13: unknown orientation raises UnboundLocalError"
)
def test_unknown_orientation_gives_clear_error():
    with pytest.raises(ValueError):
        calculate_film_coefficient(25.0, 65.0, "Vertical", 50.0)


@pytest.mark.xfail(
    strict=True, reason="S13: no warning outside the correlation's Ra range"
)
def test_warns_outside_rayleigh_validity(caplog):
    # 3 mm part, 5 K rise: Ra ~ 1e2, far below the 1e4 lower limit
    with caplog.at_level(logging.WARNING):
        calculate_film_coefficient(25.0, 30.0, "vertical", 3.0)
    assert any(r.levelno >= logging.WARNING for r in caplog.records)
