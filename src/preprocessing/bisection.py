import json
from pathlib import Path
import logging
import csv
import sys
import os
from preprocessing.common import get_config, save_config

log = logging.getLogger()

# Exit codes read by find_coef.sh. 1 is deliberately unused: it is what Python
# returns on any crash, which must stop the loop instead of looking like progress.
CONVERGED = 0
OUT_OF_RANGE = 2
NOT_STEADY = 3
CONTINUE = 10


def bisect_temperature(config_path: str, csv_path: str):
    """Checks simulation output temperature.

    Compares it with the middle value of the current temperature range.
    If there is no convergence, update the temperature range for the next simulation.
    Exit codes: 0 converged, 10 continue, 2 out of range, 3 not steady state.
    """

    # Get simulated temp
    p = Path(csv_path).resolve().as_posix()
    times, temps = [], []
    with open(p, "r") as file:
        csv_reader = csv.DictReader(file)
        for row in csv_reader:
            times.append(float(row["time [s]"]))
            temps.append(float(row["max [C]"]))
    if not temps:
        logging.error(f"{csv_path} has no data rows")
        sys.exit(1)
    temp_sim = max(temps)

    # Get config parameters
    config = get_config(config_path)
    tolerance = config["temperature"]["tolerance"]
    temp_mid = (config["temperature"]["min"] + config["temperature"]["max"]) / 2.0
    iteration = os.environ.get("ITERATION", "?")

    # Save results to log file
    logging.info(
        f"#{iteration} Simulated temp = {temp_sim} Calculated temp = {temp_mid}"
    )

    # The bisection compares steady-state temperatures; a run still heating up by
    # more than half the convergence tolerance is not usable
    t_end = times[-1]
    tail = [t for t, time in zip(temps, times) if time >= 0.9 * t_end]
    drift = temps[-1] - min(tail) if tail else 0.0
    if drift > tolerance / 2:
        logging.error(
            f"Max temperature still rose {drift:.2f} K over the last 10% of the simulation "
            f"(more than half the {tolerance} K tolerance): it has not reached steady state. "
            "Increase Time End in the solver."
        )
        sys.exit(NOT_STEADY)
    if drift > tolerance / 10:
        logging.warning(
            f"Max temperature still rose {drift:.2f} K over the last 10% of the simulation; "
            "the result is close to, but not fully at, steady state."
        )

    # Check if in range
    t_min = float(os.environ.get("TMIN", config["temperature"]["min"]))
    t_max = float(os.environ.get("TMAX", config["temperature"]["max"]))
    if temp_sim < t_min:
        logging.error(
            "Simulated temperature is below the lower bound of the range. Reduce the lower limit of the range."
        )
        sys.exit(OUT_OF_RANGE)
    if temp_sim > t_max:
        logging.error(
            "Simulated temperature is above the upper bound of the range. Increase the upper limit of the range."
        )
        sys.exit(OUT_OF_RANGE)

    # Break condition
    if abs(temp_sim - temp_mid) <= tolerance:
        config["bisected_temp"] = temp_mid
        with open(config_path, "w") as file:
            json.dump(config, file)
        logging.info(f"CONVERGENCE T = {temp_mid}")
        sys.exit(CONVERGED)

    # Continue conditions
    if temp_sim > temp_mid:
        config["temperature"]["min"] = temp_mid
    else:
        config["temperature"]["max"] = temp_mid
    logging.info(
        f'NO CONVERGENCE -> New range = [{config["temperature"]["min"]} , {config["temperature"]["max"]}]'
    )
    save_config(config, config_path)
    sys.exit(CONTINUE)
