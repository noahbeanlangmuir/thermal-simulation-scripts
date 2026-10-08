import paraview.simple as pvs
import glob
import json
from pathlib import Path
import os

output_path = Path.cwd()


def ensure_output_directory(directory: str) -> None:
    """Ensure that the specified directory exists."""
    os.makedirs(directory, exist_ok=True)


def get_vtk_files() -> list[str]:
    """Get list of .vtk files."""
    files = sorted([file for file in glob.glob("vtk/*.vtk")])
    return files


def temperature_displayer(input_data, input_viewer, tmin, tmax):
    # Create LUT
    temperatureLUT = pvs.GetColorTransferFunction("NT")
    temperatureLUT.ScalarRangeInitialized = 1.0
    temperatureLUT.ApplyPreset("X Ray", True)
    temperatureLUT.AutomaticRescaleRangeMode = "Never"
    temperatureLUT.RescaleTransferFunction(tmin, tmax)
    # Create display
    temperature_display = pvs.Show(
        input_data, input_viewer, "UnstructuredGridRepresentation"
    )
    temperature_display.ColorArrayName = ["POINTS", "NT"]
    temperature_display.LookupTable = temperatureLUT
    temperature_display.SetScalarBarVisibility(input_viewer, True)
    temperature_display.RescaleTransferFunctionToDataRange = 0
    return temperature_display


def temperature_range(default=(273.15, 433.15)) -> tuple[float, float]:
    """Colour range [K]: the simulated min/max from temperature.csv if present."""
    try:
        import csv

        with open("temperature.csv") as f:
            rows = list(csv.DictReader(f))
        return min(float(r["min [K]"]) for r in rows), max(float(r["max [K]"]) for r in rows)
    except (OSError, KeyError, ValueError):
        print(f"temperature.csv not found or unreadable, colour range {default} K")
        return default


def generate(output_dir: str = "gltf") -> None:
    ensure_output_directory(output_dir)
    files = get_vtk_files()
    t_min, t_max = temperature_range()
    # the scale bar (generate_svg_palette.py) reads this so its labels match
    with open(f"{output_dir}/range.json", "w") as f:
        json.dump({"tmin_C": t_min - 273.15, "tmax_C": t_max - 273.15}, f)
    print(f"Generating GLTF files, colour range {t_min - 273.15:.1f}..{t_max - 273.15:.1f} C")
    for idx, file in enumerate(files):
        vtk_reader = pvs.OpenDataFile(file)
        render_view = pvs.GetActiveViewOrCreate("RenderView")
        display = temperature_displayer(vtk_reader, render_view, t_min, t_max)
        pvs.UpdatePipeline()
        pvs.Render()
        filename = f"{output_dir}/{idx:04d}.gltf"
        pvs.ExportView(filename, view=render_view)
        pvs.Delete(vtk_reader)
        pvs.Delete(display)
    print("Finished")


if __name__ == "__main__":
    generate()
