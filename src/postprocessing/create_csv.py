import vtkmodules.all as vtk
from vtkmodules.util import numpy_support
import glob
import numpy as np
import pandas as pd
import typer


def get_vtk_files(vtk_directory: str) -> list[str]:
    """Get list of .vtk files.

    Keyword arguments:
    vtk_directory -- path to directory with vtk files
    """
    files = sorted([file for file in glob.glob(f"{vtk_directory}/*.vtk")])
    return files


def get_timesteps(filename: str) -> list[str]:
    """Get timesteps from .sta file.

    Keyword arguments
    filename -- path to .sta file
    """
    timesteps = []
    with open(filename) as f:
        lines = f.readlines()
        del lines[0]
        del lines[0]
        for line in lines:
            splited_line = line.split(" ")
            convergence = "".join(splited_line[-12:-10]).isnumeric()
            step = splited_line[-5:-4][0]
            if convergence:  # in some case time step entry can be duplicated
                timesteps.append(step)
    return timesteps


def find_array_id_by_name(point_data: vtk.vtkPointData, name: str) -> int | None:
    """Find array id by array name.

    Keyword arguments:
    point_data -- vtk unstructured grid data
    name -- name of the array to find
    """
    for id in range(0, point_data.GetNumberOfArrays()):
        if point_data.GetArrayName(id) == name:
            return id
    return None


def parse_regions(specs: list[str]) -> dict[str, tuple[list[float], list[float]]]:
    """Parse NAME=xmin,ymin,zmin,xmax,ymax,zmax (mm) into {name: (lo, hi)}."""
    regions = {}
    for spec in specs:
        name, _, values = spec.partition("=")
        nums = values.split(",")
        if not name or len(nums) != 6:
            raise ValueError(
                f"--region {spec!r}: expected NAME=xmin,ymin,zmin,xmax,ymax,zmax (mm)"
            )
        v = [float(x) for x in nums]
        regions[name.strip()] = (v[:3], v[3:])
    return regions


def main(
    vtk_directory: str, sta_file: str, output_file: str, regions: dict | None = None
) -> None:
    """Main script function.

    Keyword arguments:
    vtk_directory -- path to vtk directory
    sta_file -- path to CalculiX sta file
    output_file -- path to output csv file
    regions -- {name: (lo, hi)} boxes in mm; adds max/mean/min columns per box
    """
    regions = regions or {}
    files = get_vtk_files(vtk_directory)
    if not files:
        raise ValueError(f"No .vtk files in {vtk_directory}. Run `tpost convert` first.")
    timesteps = get_timesteps(sta_file)
    if len(files) != len(timesteps):
        raise ValueError(
            f"{len(files)} .vtk files in {vtk_directory} but {len(timesteps)} time steps in "
            f"{sta_file}. Either old .vtk files from an earlier run are still there (run "
            "`tpost convert`, which clears them) or the solver wrote results less often "
            "than every increment (set OutputFrequency = 1)."
        )

    columns: dict[str, list] = {
        name: [] for name in ("max [K]", "max [C]", "max [F]", "min [K]", "min [C]", "min [F]")
    }
    for name in regions:
        for stat in ("max", "mean", "min"):
            columns[f"{name} {stat} [C]"] = []
    for filename in files:
        reader = vtk.vtkUnstructuredGridReader()
        reader.SetFileName(filename)
        reader.Update()
        point_data = reader.GetOutput().GetPointData()
        nt_id = find_array_id_by_name(point_data, "NT")
        if nt_id is None:
            raise ValueError(f"{filename} has no NT (nodal temperature) array")
        nt = reader.GetOutput().GetPointData().GetArray(nt_id)

        array = numpy_support.vtk_to_numpy(nt)
        columns["max [K]"].append(array.max())
        columns["max [C]"].append(array.max() - 273.15)
        columns["max [F]"].append((array.max() - 273.15) * 1.8 + 32)
        columns["min [K]"].append(array.min())
        columns["min [C]"].append(array.min() - 273.15)
        columns["min [F]"].append((array.min() - 273.15) * 1.8 + 32)
        if regions:
            points = numpy_support.vtk_to_numpy(reader.GetOutput().GetPoints().GetData())
        for name, (lo, hi) in regions.items():
            inside = ((points >= np.array(lo) - 1e-6) & (points <= np.array(hi) + 1e-6)).all(axis=1)
            if not inside.any():
                raise ValueError(f"--region {name}: no mesh nodes inside {lo}..{hi} mm")
            t = array[inside] - 273.15
            columns[f"{name} max [C]"].append(t.max())
            columns[f"{name} mean [C]"].append(t.mean())
            columns[f"{name} min [C]"].append(t.min())

    df = pd.DataFrame(data={"time [s]": timesteps, **columns})

    print(f"Collected {len(df)} rows from {len(files)} result files")
    last = df.iloc[-1]
    print(f"At t = {last['time [s]']} s: max {last['max [C]']:.2f} C, min {last['min [C]']:.2f} C")
    for name in regions:
        print(
            f"  {name}: max {last[f'{name} max [C]']:.2f} C, mean "
            f"{last[f'{name} mean [C]']:.2f} C, min {last[f'{name} min [C]']:.2f} C"
        )
    df.to_csv(output_file)


if __name__ == "__main__":
    typer.run(main)
