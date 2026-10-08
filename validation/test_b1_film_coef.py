"""B1: film coefficient calculator (src/preprocessing/calculate_coef.py).

The S13 tests at the end guard fixes for defects found by the validation.
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


def test_unknown_orientation_gives_clear_error():
    """S13 regression: a typo used to raise UnboundLocalError."""
    with pytest.raises(ValueError):
        calculate_film_coefficient(25.0, 65.0, "Vertical", 50.0)


def test_warns_outside_rayleigh_validity(caplog):
    """S13 regression: extrapolating the correlation used to be silent."""
    # 3 mm part, 5 K rise: Ra ~ 1e2, far below the 1e4 lower limit
    with caplog.at_level(logging.WARNING):
        calculate_film_coefficient(25.0, 30.0, "vertical", 3.0)
    assert any(r.levelno >= logging.WARNING for r in caplog.records)
