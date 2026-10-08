from postprocessing import create_csv
from postprocessing import create_plot
from postprocessing import plot_comparison
from pathlib import Path
import typer
from typing import List, Optional
from enum import Enum
import shutil
import subprocess
import logging

app = typer.Typer(help="Postprocessing utilities")

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


@app.command()
def convert(
    frd: str = typer.Option("FEMMeshGmsh.frd", help="CalculiX result file (.frd)"),
    vtk: str = typer.Option("vtk", help="Directory for the .vtk files"),
):
    """Convert .frd results to .vtk files in a clean vtk directory"""
    frd_path = Path(frd).resolve()
    if not frd_path.exists():
        logging.error(f"{frd_path} not found. Run ccx first.")
        raise typer.Exit(1)
    vtk_dir = Path(vtk).resolve()
    vtk_dir.mkdir(parents=True, exist_ok=True)
    # old results would be mixed into the new time series
    for old in vtk_dir.glob("*.vtk"):
        old.unlink()
    for old in frd_path.parent.glob(f"{frd_path.stem}*.vtk"):
        old.unlink()
    p = subprocess.run(["ccx2paraview", str(frd_path), "vtk"])
    if p.returncode != 0:
        logging.error(f"ccx2paraview exited {p.returncode}")
        raise typer.Exit(1)
    new = sorted(frd_path.parent.glob(f"{frd_path.stem}*.vtk"))
    if not new:
        logging.error("ccx2paraview produced no .vtk files")
        raise typer.Exit(1)
    for f in new:
        shutil.move(str(f), vtk_dir / f.name)
    logging.info(f"{len(new)} .vtk files in {vtk_dir}")


@app.command()
def csv(
    vtk: str = typer.Option("vtk", help="Path to directory with .vtk files"),
    sta: str = typer.Option(
        "FEMMeshGmsh.sta", help="Path to CalculiX time stamp file (.sta)"
    ),
    output: str = typer.Option("temperature.csv", help="Path to output file"),
    region: List[str] = typer.Option(
        [],
        help="Extra columns for the nodes inside a box: NAME=xmin,ymin,zmin,xmax,ymax,zmax "
        "(mm). Repeat for several parts, e.g. --region block=25,0,0,45,50,50",
    ),
):
    """Generate csv file from simulation output"""
    try:
        regions = create_csv.parse_regions(region)
        create_csv.main(vtk, sta, output, regions)
    except ValueError as e:
        logging.error(str(e))
        raise typer.Exit(1)


@app.command()
def plot(
    csv: str = typer.Option(
        "temperature.csv", help="Path to simulation data file (.csv)"
    ),
    output: str = typer.Option("graphs", help="Path to graph directory"),
    sim: Optional[str] = typer.Option(None, help="Path to simulation settings file"),
):
    """Generate temperature characteristics"""
    create_plot.main(csv, output, sim)


class Position(str, Enum):
    upper_left = "upper left"
    upper_right = "upper right"
    center = "center"  # type: ignore[assignment]
    lower_left = "lower left"
    lower_right = "lower right"


@app.command()
def compare_csv(
    legend: Optional[Position] = typer.Option(None, help="Legend location"),
    time: Optional[float] = typer.Option(None, help="Max time [s]"),
    csv1: str = typer.Option("", help="Path to 1st csv"),
    csv2: str = typer.Option("", help="Path to 2nd csv"),
    label1: str = typer.Option("Simulation", help="Name of 1st plot"),
    label2: str = typer.Option("Measurements", help="Name of 2nd plot"),
    kelvin: Optional[bool] = typer.Option(False, help="Use Kelvin temperature scale"),
    fahrenheit: Optional[bool] = typer.Option(
        False, help="Use Fahrenheit temperature scale"
    ),
    name: Optional[str] = typer.Option(None, help="Graph name"),
    output: str = typer.Option("comparison.png", help="Path to the saved graph"),
    show: bool = typer.Option(False, help="Also open the graph in a window"),
):
    """Compare two temperature plots on a common graph"""
    plot_comparison.plot(
        legend, time, csv1, csv2, label1, label2, kelvin, fahrenheit, name, output, show
    )


@app.command()
def process_blend(
    input: str = typer.Option("raw.blend", help="Path to input blend (.blend)"),
    output: str = typer.Option("processed.blend", help="Path to output blend (.blend)"),
    material: str = typer.Option(
        Path(__file__).parent.resolve() / "material.blend",
        help="Path to file with thermal_threshold material (.blend)",
    ),
    config: str = typer.Option("config.json", help="Path to config (.json)"),
):
    """Prepare .blend for pcbooth"""
    from postprocessing import process_blend as pb

    pb.process_blend(blend_in=input, blend_out=output, material=material, config=config)


@app.command()
def gltf_to_blend(
    gltf: str = typer.Option("", help="Path to gltf file (.gltf)"),
    blend: str = typer.Option("raw.blend", help="Path to output blend (.blend)"),
):
    """Convert format from gltf to blend"""
    from postprocessing import process_blend

    process_blend.gltf_to_blend(gltf_path=gltf, blend_path=blend)


@app.command()
def preview_camera(
    gltf: str = typer.Option("", help="Input path (.gltf)"),
    blend: str = typer.Option("camera_preview.blend", help="Path to preview (.blend)"),
):
    """Create camera preview .blend"""
    from postprocessing import process_blend

    process_blend.preview_camera(gltf_path=gltf, blend_path=blend)


@app.command()
def save_camera(
    blend: str = typer.Option("camera_preview.blend", help="Path to preview (.blend)"),
    config: str = typer.Option("config.json", help="Path to config (.json)"),
):
    """Save custom camera properties from .blend to config"""
    from postprocessing import process_blend

    process_blend.save_camera_properties(blend, config)


def _run_pvpython(script: str, out_dir: str) -> None:
    """Run a ParaView script on ./vtk; stop with an error if it fails or
    writes nothing to out_dir (ParaView can log errors and still exit 0)."""
    import time

    if not list(Path("vtk").glob("*.vtk")):
        logging.error(f"No .vtk files in {Path('vtk').resolve()}. Run `tpost convert` first.")
        raise typer.Exit(1)
    if shutil.which("pvpython") is None:
        logging.error("pvpython not found on PATH. Install ParaView and add its bin directory.")
        raise typer.Exit(1)
    start = time.time()
    p = subprocess.run(["pvpython", str(Path(__file__).parent / script)])
    if p.returncode != 0:
        logging.error(f"pvpython {script} exited {p.returncode}")
        raise typer.Exit(1)
    new = [f for f in Path(out_dir).glob("*") if f.stat().st_mtime >= start - 1]
    if not new:
        logging.error(f"pvpython {script} finished but wrote nothing to {out_dir}/; see errors above")
        raise typer.Exit(1)
    logging.info(f"{len(new)} files written to {Path(out_dir).resolve()}")


@app.command()
def generate_gltf():
    """Generate gltf files for every time step."""
    _run_pvpython("generate_gltf.py", "gltf")


@app.command()
def preview():
    """Create paraview image previews."""
    _run_pvpython("create_previews.py", "previews")


@app.command()
def animation():
    """Create paraview animation."""
    _run_pvpython("create_animation.py", "animations")


def main():
    """Main script function."""
    app()


if __name__ == "__main__":
    main()
