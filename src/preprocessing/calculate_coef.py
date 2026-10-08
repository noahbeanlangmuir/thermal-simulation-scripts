import logging

# Air properties in 20ºC due to
# https://calcdevice.com/natural-convection-of-vertical-surface-id128.html
fluid_thermal_conductivity = 0.0259  # W/m*ºC
dynamic_viscosity = 0.000018  # Pa*s
fluid_specific_heat = 1005  # J/kg*⁰C
volumetric_expansion = 0.00365  # 1/⁰C
density = 1.205  # kg/m³
gravity = 9.80665  # m/s^2

log = logging.getLogger(__name__)

# Nusselt number coefficient C and the Rayleigh range where Nu = C * Ra^0.25 holds
CORRELATIONS = {
    "vertical": (0.59, 1e4, 1e9),
    "horizontal_up": (0.54, 1e4, 1e7),
    "horizontal_down": (0.27, 1e5, 1e10),
}


def calculate_film_coefficient(
    temp_fluid: float, temp_surface: float, orientation: str, length: float
):
    # Characteristic length [mm]
    length = length / 1000
    # Nusselt number coefficients for natural convection due to
    # https://www.sfu.ca/~mbahrami/ENSC%20388/Notes/Natural%20Convection.pdf#page=4
    n = 0.25
    if orientation not in CORRELATIONS:
        raise ValueError(
            f"Unknown orientation {orientation!r}, use one of: {', '.join(CORRELATIONS)}"
        )
    c, ra_min, ra_max = CORRELATIONS[orientation]
    # fmt: off
    if temp_fluid > temp_surface:
        raise Exception("TEMP_FLUID higher than TEMP_SURFACE")
    grashof_number = (
        gravity * pow(length, 3) * volumetric_expansion * (temp_surface - temp_fluid)
        / pow((dynamic_viscosity / density), 2)
    )
    prandtl_number = dynamic_viscosity * fluid_specific_heat / fluid_thermal_conductivity
    rayleigh_number = grashof_number * prandtl_number
    nusselt_number = c * pow(rayleigh_number, n)
    film_coefficient = nusselt_number * fluid_thermal_conductivity / length
    # fmt: on
    if not ra_min <= rayleigh_number <= ra_max:
        logging.warning(
            f"Rayleigh number {rayleigh_number:.3g} is outside the {orientation} "
            f"correlation range [{ra_min:.0e}, {ra_max:.0e}]; the film coefficient "
            f"{film_coefficient:.2f} W/m^2/K is extrapolated (L = {length * 1000:g} mm, "
            f"dT = {temp_surface - temp_fluid:g} K)"
        )
    heat_flow = film_coefficient * (temp_surface - temp_fluid)
    logging.debug(f"Grashof_number = {grashof_number}")
    logging.debug(f"Prandtl_number = {prandtl_number}")
    logging.debug(f"Rayleigh_number = {rayleigh_number}")
    logging.debug(f"Nusselt_number = {nusselt_number}")
    logging.debug(f"Film coefficient = {film_coefficient}")
    logging.debug(f"Heat flow = {heat_flow}")
    return film_coefficient
