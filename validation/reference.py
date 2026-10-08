"""Closed-form reference solutions used by the validation benchmarks.

Everything here is independent of the code under test (src/), so it can be
used as ground truth. Units: SI unless the name says otherwise.

Run directly to print the B1 film-coefficient bias table:
    python validation/reference.py
"""

import math

GRAVITY = 9.80665  # m/s^2
P_ATM = 101325.0  # Pa
R_AIR = 287.05  # J/kg/K
CP_AIR = 1007.0  # J/kg/K (varies < 1 % over 0-150 C)

# Constants hardcoded in src/preprocessing/calculate_coef.py, repeated here so
# the "same correlation" check is an independent re-implementation.
CODE_AIR = {
    "k": 0.0259,
    "mu": 0.000018,
    "cp": 1005.0,
    "beta": 0.00365,
    "rho": 1.205,
}
CODE_C = {"vertical": 0.59, "horizontal_up": 0.54, "horizontal_down": 0.27}

# Validity range (Rayleigh number) of the correlations used by the code.
# Incropera, Fundamentals of Heat and Mass Transfer, ch. 9.
CODE_RA_RANGE = {
    "vertical": (1e4, 1e9),
    "horizontal_up": (1e4, 1e7),
    "horizontal_down": (1e5, 1e10),
}


def air_properties(t_kelvin: float) -> dict:
    """Dry air at 1 atm, evaluated at the given (film) temperature."""
    rho = P_ATM / (R_AIR * t_kelvin)
    # Sutherland's law
    mu = 1.716e-5 * (t_kelvin / 273.15) ** 1.5 * (273.15 + 110.4) / (t_kelvin + 110.4)
    # Power-law fit to tabulated data, within ~1 % over 250-450 K
    k = 0.0241 * (t_kelvin / 273.15) ** 0.9
    return {"k": k, "mu": mu, "cp": CP_AIR, "beta": 1.0 / t_kelvin, "rho": rho}


def rayleigh(props: dict, delta_t: float, length_m: float) -> float:
    nu = props["mu"] / props["rho"]
    alpha = props["k"] / (props["rho"] * props["cp"])
    return GRAVITY * props["beta"] * delta_t * length_m**3 / (nu * alpha)


def prandtl(props: dict) -> float:
    return props["mu"] * props["cp"] / props["k"]


def h_same_correlation(
    t_fluid_c: float, t_surface_c: float, orientation: str, length_mm: float
) -> float:
    """Independent re-implementation of the code's correlation and constants."""
    length = length_mm / 1000.0
    ra = rayleigh(CODE_AIR, t_surface_c - t_fluid_c, length)
    nu = CODE_C[orientation] * ra**0.25
    return nu * CODE_AIR["k"] / length


def h_textbook(
    t_fluid_c: float, t_surface_c: float, orientation: str, length_mm: float
) -> float:
    """Recommended correlations with properties at film temperature.

    vertical:        Churchill-Chu, all Ra
    horizontal_up:   0.54 Ra^1/4 (1e4-1e7), 0.15 Ra^1/3 (1e7-1e11)
    horizontal_down: 0.52 Ra^1/5 (Incropera 7th ed.)
    For horizontal plates the length must be A/P (area / perimeter).
    """
    length = length_mm / 1000.0
    props = air_properties((t_fluid_c + t_surface_c) / 2.0 + 273.15)
    ra = rayleigh(props, t_surface_c - t_fluid_c, length)
    pr = prandtl(props)
    if orientation == "vertical":
        nu = (
            0.825 + 0.387 * ra ** (1 / 6) / (1 + (0.492 / pr) ** (9 / 16)) ** (8 / 27)
        ) ** 2
    elif orientation == "horizontal_up":
        nu = 0.54 * ra**0.25 if ra <= 1e7 else 0.15 * ra ** (1 / 3)
    elif orientation == "horizontal_down":
        nu = 0.52 * ra**0.2
    else:
        raise ValueError(f"Unknown orientation {orientation!r}")
    return nu * props["k"] / length


def h_radiation(t_fluid_c: float, t_surface_c: float, emissivity: float) -> float:
    """Linearised radiation coefficient to surroundings at fluid temperature."""
    sigma = 5.670374419e-8
    ts, tf = t_surface_c + 273.15, t_fluid_c + 273.15
    return emissivity * sigma * (ts**2 + tf**2) * (ts + tf)


def characteristic_length_horizontal(a_mm: float, b_mm: float) -> float:
    """A/P for an a x b rectangle [mm]."""
    return a_mm * b_mm / (2 * (a_mm + b_mm))


def lumped_rise(power_w: float, h: float, area_m2: float) -> float:
    """Steady-state temperature rise of a lumped body [K]."""
    return power_w / (h * area_m2)


def lumped_tau(rho: float, cp: float, volume_m3: float, h: float, area_m2: float):
    """Time constant of a lumped body [s]."""
    return rho * cp * volume_m3 / (h * area_m2)


def lumped_transient(t: float, power_w: float, h: float, area_m2: float, tau: float):
    return lumped_rise(power_w, h, area_m2) * (1 - math.exp(-t / tau))


def _b1_table() -> str:
    import logging

    # the table has its own "in range" column; skip the per-call extrapolation warnings
    logging.disable(logging.WARNING)
    try:
        return _b1_rows()
    finally:
        logging.disable(logging.NOTSET)


def _b1_rows() -> str:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from preprocessing.calculate_coef import calculate_film_coefficient

    rows = [
        "| orientation | L [mm] | dT [K] | Ra (code props) | in range | h code | h textbook | bias | h_rad (e=0.9) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    t_inf = 25.0
    for orientation in ("vertical", "horizontal_up", "horizontal_down"):
        for length in (5.0, 20.0, 100.0):
            for dt in (10.0, 40.0, 80.0):
                h_code = calculate_film_coefficient(
                    t_inf, t_inf + dt, orientation, length
                )
                h_ref = h_textbook(t_inf, t_inf + dt, orientation, length)
                ra = rayleigh(CODE_AIR, dt, length / 1000)
                lo, hi = CODE_RA_RANGE[orientation]
                in_range = "yes" if lo <= ra <= hi else "**no**"
                h_rad = h_radiation(t_inf, t_inf + dt, 0.9)
                rows.append(
                    f"| {orientation} | {length:g} | {dt:g} | {ra:.2e} | {in_range} "
                    f"| {h_code:.2f} | {h_ref:.2f} | {100 * (h_code / h_ref - 1):+.1f} % "
                    f"| {h_rad:.2f} |"
                )
    # Characteristic-length guidance in README.md ("smaller dimension") vs A/P
    a, b = 100.0, 80.0
    lp = characteristic_length_horizontal(a, b)
    h_small = calculate_film_coefficient(t_inf, t_inf + 40, "horizontal_up", b)
    h_ap = calculate_film_coefficient(t_inf, t_inf + 40, "horizontal_up", lp)
    rows += [
        "",
        f"Characteristic length for a {a:g}x{b:g} mm board, horizontal_up, dT=40 K:",
        f"README 'smaller dimension' L={b:g} mm -> h={h_small:.2f} W/m2K; "
        f"textbook A/P L={lp:.1f} mm -> h={h_ap:.2f} W/m2K "
        f"({100 * (h_small / h_ap - 1):+.1f} %)",
    ]
    return "\n".join(rows)


if __name__ == "__main__":
    print(_b1_table())
