# Thermal simulation scripts

Copyright (c) 2023-2025 [Antmicro](https://www.antmicro.com)

![](img/simulation-toolchain.png)

This project contains scripts used for thermal simulation and data visualization.
You can learn more about the project from the following [blog note](https://antmicro.com/blog/2025/03/open-source-thermal-simulation-analysis-and-visualization/).

## Table of Contents

1. [Installation](#installation)
   - [Dependencies](#dependencies)
   - [Installation instructions](#installation-instructions)
2. [Usage](#usage)
   - [Constraints and mesh generation](#constraints-and-mesh-generation)
   - [Pre-processing](#pre-processing)
   - [Running the simulation](#running-the-simulation)
   - [Post-processing](#post-processing)
   - [Generating graphs](#generating-graphs)
   - [Generating previews](#generating-previews)
3. [Example walkthrough](#example-simulation-walkthrough)
   - [Common mistakes](#common-mistakes)
4. [Licensing](#licensing)

---

## Installation

### Dependencies

The `thermal-simulation-scripts` pipeline has been tested and validated with the following dependencies::

- `Calculix` = 2.20
- `ParaView` = 6.0.0
- `python` = 3.11.2
- `pip`
- `FreeCAD` = 1.0.0
- `ccx2paraview`
- `ffmpeg`
- `jq` (automated film coefficient estimation)

> **Windows / no root access:** run everything inside WSL2. [validation/SETUP.md](validation/SETUP.md) has a step-by-step guide and a no-sudo install script (`validation/install_user.sh`). Clone the repository inside WSL, not on the Windows drive, so the shell scripts keep Unix line endings.

On Debian-based systems, these dependencies can be installed using:

#### Install apt requirements

```bash
sudo apt install -y calculix-ccx python3 python3-pip libxrender1 tar wget libgl1-mesa-glx libegl1 libosmesa6 ffmpeg 
```

#### Install FreeCAD

```bash
wget -O freecad.AppImage "https://github.com/FreeCAD/FreeCAD/releases/download/1.0.0/FreeCAD_1.0.0-conda-Linux-x86_64-py311.AppImage"
sudo chmod +x freecad.AppImage
./freecad.AppImage --appimage-extract
sudo mv squashfs-root /usr/local/share/freecad
sudo ln -s /usr/local/share/freecad/AppRun /usr/local/bin/freecad
echo 'export FREECAD_PATH="/usr/local/share/freecad"' >> ~/.bashrc && source ~/.bashrc
rm freecad.AppImage
```

#### Install ParaView

```bash
sudo mkdir /opt/paraview
sudo wget -O /opt/paraview/paraview.tar.gz "https://www.paraview.org/paraview-downloads/download.php?submit=Download&version=v6.0&type=binary&os=Linux&downloadFile=ParaView-6.0.0-MPI-Linux-Python3.12-x86_64.tar.gz"
sudo tar -xvzf /opt/paraview/paraview.tar.gz --strip-components=1 -C /opt/paraview
sudo rm /opt/paraview/paraview.tar.gz
echo 'export PATH=/opt/paraview/bin:$PATH' >> ~/.bashrc
source ~/.bashrc
```

### Installation instructions

Clone the repository:

```bash
git clone http://github.com/antmicro/thermal-simulation-scripts
cd thermal-simulation-scripts
```

Installation should be performed in an isolated python environment to avoid dependency conflicts:

```sh
sudo apt update
sudo apt install pipx
pipx ensurepath
pipx install . --include-deps
```

The script can be run using the following commands:

- `tpre` for pre-processing tasks.
- `tpost` for simulation post-processing.

---

## Usage

### Constraints and mesh generation

The first step in a thermal simulation is to define constraints for each surface of the 3D model and convert it into a mesh using FreeCAD. This process results in a `.FCStd` format file.

### Pre-processing

This step prepares the simulation. The `.FCStd` file should be sufficient, but additional settings can be configured.

#### Generating inp file

```bash
tpre parse-fcstd --fcstd <path_to_fcstd> --inp [inp_dir] --log [settings_dir]
```

- `<path_to_fcstd>`: Path to FreeCad design file (`.FCStd`)
- `[inp_dir]`: Optional output directory for the simulation input file (`.inp`)
- `[settings_dir]`: Optional output directory for the simulation settings file (`simulation.json`)
- `--cavity-radiation`: Radiation faces exchange heat with each other using view factors, not only with the ambient temperature. Use it when parts are separated by a gap or sit in an enclosure.
- `--force`: Keep the `.inp` even if the model checks below report errors.

The `.inp` is named after the FreeCAD mesh object (`FEMMeshGmsh.inp` by default). The name is printed at the end and stored in `simulation.json` as `"Input file"`.

`parse-fcstd` checks the generated model and stops with an error if:

- touching parts were meshed separately, so no heat can flow between them (fuse them first, see [Common mistakes](#common-mistakes));
- a convection/radiation/heat flux constraint covers a face that is hidden inside the model.

It also prints the total heat input. The same checks can be run on any `.inp` with `tpre check --inp <file>`.

#### Generating simulation settings report

To generate report in markdown format use the following command.
The report includes data from `simulation.json`, and optionally, user comments provided under the `user_comments` key in config.json.

```bash
tpre report --sim [path_to_settings_file] --config [path_to_config_file] --report-dir [report_dir] --output [file_name]
```

- `[path_to_settings_file]`: Optional path to simulation settings file (`simulation.json`)
- `[path_to_config_file]`: Optional path to config file (`config.json`)
- `[report_dir]`: Optional directory for the report (default: current directory)
- `[file_name]`: Optional report file name (default: `simulation_report.md`)

### Running the simulation

To run the simulation using CalculiX:

```bash
ccx <inp_name_without_extension>
```

Use the name printed by `tpre parse-fcstd` (e.g. `ccx FEMMeshGmsh`).

Refer to the [CalculiX manual](http://www.dhondt.de/) for further details.

### Post-processing

#### Converting simulation results

```bash
tpost convert --frd <frd_file> --vtk [vtk_directory]
```

- `<frd_file>`: Path to the CalculiX output `.frd` file (default `FEMMeshGmsh.frd`).
- `[vtk_directory]`: Directory for the `.vtk` files (default `vtk`). Old `.vtk` files in it are removed first so results of different runs are never mixed.

#### Generating CSV files

```bash
tpost csv --vtk [vtk_directory] --sta [sta_file] --output [output_file] --region [NAME=xmin,ymin,zmin,xmax,ymax,zmax]
```

- `[vtk_directory]`: Optional path to directory with `.vtk` files.
- `[sta_file]`: Optional path to `.sta` file (output from CalculiX).
- `[output_file]`: Optional path for the output CSV file.
- `--region`: Optional, repeatable. Adds max/mean/min columns for the mesh nodes inside a box (mm), e.g. one per component: `--region block=25,0,0,45,50,50`.

The output CSV contains:

- Time [s]
- Maximum/Minimum temperature of the whole model in Kelvin, Celsius and Fahrenheit
- Max/mean/min temperature [C] of each `--region`

The whole-model maximum is often a heat source held at a fixed temperature; use `--region` to get the temperature of the part you care about.

### Generating graphs

```bash
tpost plot --csv [data_file] --output [output_dir] --sim [simulation_json]
```

- `[data_file]`: Optional path to simulation `.csv` file.
- `[output_dir]`: Optional directory where graphs will be saved.
- `[simulation_json]`: Optional simulation JSON file.

Graphs generated:

- Temperature vs. time (Kelvin & Celsius)
- Highest/Lowest temperatures
- Temperature differences
- Simulation iterations over time

All of them will be saved in `/graphs/`.

To compare characteristics on a common graph use:

```bash
tpost compare-csv --csv1 <1st_csv_file> --csv2 <2nd_csv_file> --output comparison.png
```

Both CSV files need the `time [s]` and `max [C]` (or `max [K]` / `max [F]`) columns written by `tpost csv`. The graph is saved to `--output`; add `--show` to also open it in a window. Run `tpost compare-csv --help` for advanced options.

### Visualizing simulation in ParaView

#### Preview

```bash
tpost preview
```

Images colored with temperature gradients will be generated in `/previews/`.

#### Animations

```bash
tpost animation
```

Animation frames will be saved in `/animations/`.

To create an animation in `.webm` format, use e.g. `ffmpeg`

```bash
ffmpeg -framerate <fps>  -i <input_frames> <animation_path>
```

`<fps>`: frames per second
`<input_frames>`: path to animation frames - can be used with wildcards
`<animation_path>`: file path to the animation

---

### Visualizing simulation in Blender

Blender animations utilize Antmicro's scene setup and rendering tool [PCBooth](https://github.com/antmicro/pcbooth).

Animation scripts require:

- `.vtk` files that are obtained in [converting simulation results](#converting-simulation-results)
- `config.json` [Optional] containing `camera_custom` parameters needed if PCBooth is set to use custom camera

#### Single frame

Use this command to generate `.gltf` files from `.vtk` files:

```bash
tpost generate-gltf
```

Then convert `.gltf` file to `.blend`:

```bash
tpost gltf-to-blend --gltf <path-to-gltf>
```

Prepare the .blend for [PCBooth](https://github.com/antmicro/pcbooth) with:

```bash
tpost process-blend
```

Render frame with PCBooth:
```bash
pcbooth -b <path-to-blend> -c <pcbooth-job-name>
```

Add color scale bar:

```bash
rsvg-convert -a -h <height> -o scale.png <colormap_scale.svg>
composite -gravity east scale.png <frame.png> <output.png>
```

where:

- `<height>` is the height of the frame in pixels.  
- `<scale.svg>` is the color bar `.svg` generated using [`generate_svg_palette`](/src/postprocessing/generate_svg_palette.py). Run it in the folder where `tpost generate-gltf` wrote `gltf/range.json` so the labels match the colours.  
- `<frame.png>` is the frame image rendered with PCBooth.  
- `<output.png>` is the output path where the frame and color bar are combined.

#### Animation

Generate gltf files with the following command:

```bash
tpost generate-gltf
```

then in the `/designs/` directory run

```bash
../src/postprocessing/blender_animation.sh <gltf_dir> 
```

where:

- `<gltf_dir>` is path to gltf directory created with `tpost generate-gltf`

### Example simulation walkthrough

#### Prepare simulation

```bash
cd designs
tpre parse-fcstd --fcstd example.FCStd
tpre report
```

#### Run simulation with multithreading

```bash
export OMP_NUM_THREADS=16
ccx FEMMeshGmsh
```

#### Convert results

```bash
tpost convert --frd FEMMeshGmsh.frd
```

#### Visualize with ParaView

Generate graphs, previews and animation frames:

```bash
tpost csv
tpost plot
tpost preview
tpost animation
```

To generate animations from ParaView output frames:

```bash
ffmpeg -framerate 5 -i animations/ISO_%6d.png animations/iso.webm
ffmpeg -framerate 5 -i animations/TOP_%6d.png animations/top.webm
ffmpeg -framerate 5 -i animations/BOTTOM_%6d.png animations/bottom.webm
```

#### Render Blender animation

```bash
tpost generate-gltf
../src/postprocessing/blender_animation.sh gltf
```

### Common mistakes

These give plausible-looking but wrong results. `tpre parse-fcstd` catches the first two.

- **Touching parts not fused.** If a component and a board are meshed as separate solids, they share no mesh nodes and no heat flows between them. Select the parts, use *Part > Split > Boolean Fragments* (Mode: CompSolid), and mesh that object.
- **Constraints on the original part's faces.** After fusing, pick the faces of the Boolean Fragments object. A face of the original board also covers the area under the component, and convection applied there removes heat that cannot leave (the validation board read 27% too cool).
- **Mesh too coarse.** Check that the result does not change when you halve the mesh size. On the validation board an 8 mm mesh read 11% low, 4 mm read 2.5% low and 2 mm was converged.
- **Ignoring radiation.** On boards near room temperature, radiation (about 6 W/m²K at emissivity 0.9) is about as large as natural convection. Add a Radiation heat flux constraint, and use `--cavity-radiation` when parts can see each other.
- **Horizontal plate length.** For horizontal surfaces, use area / perimeter as the characteristic length (see [Config](#config)).
- **Not at steady state.** The run is transient; if `temperature.csv` is still rising at the end, increase Time End.

---

## Automated film coefficient estimation

Simulating natural convection requires calculating the film coefficients for the surfaces.
These coefficients can be estimated using an initial guess for the surface temperature.
However, since predicting the surface temperature accurately is complex, this method alone may not provide precise results.

The Bisection Algorithm is used to improve accuracy.
It iterates over a given temperature range, comparing the simulated final temperature with the temperature assumed in the film coefficient calculator.
With each iteration, the temperature range is reduced until the difference between the simulated and assumed temperatures is within a specified tolerance.
Then the algorithm returns the final temperature and the corresponding film coefficients.

**Using sparse mesh is recommended for this algorithm**

### Defining constraints in FreeCad

Define the `Heat Flux Load` constraints in FreeCad.
Then assign each face that dissipates heat to one of them.
Rename each `Heat Flux Load` to a custom name.

In this example, 3 `Heat Flux Load` constraints were defined:

* vertical
* horizontal_up
* horizontal_down

### Defining the config

In `/designs/`, create `config.json` (or edit if it exists):

- In the `film` dictionary, specify entries for each `Heat Flux Load` constraint defined in FreeCad
- In the `temperature` dictionary, specify the `max`, `min` and `tolerance` values.

Visit [config section](#config) for in detail information.
Config for this example can be found in [config.json](/designs/config.json).

### Running the bisection algorithm

```bash
./src/preprocessing/find_coef.sh designs/example.FCStd designs/
```

The 1st argument is the path to the `.FCStd` file and the 2nd argument is the path to the `/designs/` directory.

The script stops at the first failing step and points to its log in `designs/find_coef_logs/`. On convergence the temperature is saved in `config.json` as `bisected_temp` and the film coefficients are printed. Exit codes: 0 converged, 2 temperature outside the `min`/`max` range, 3 the simulation is still heating up by more than half the tolerance (increase Time End), 4 no convergence within `MAX_ITER` iterations (default 20, set the environment variable to change it).

---

## Config

`config.json` is used to store information needed for automated film coefficient estimation and Blender visualization flow.
It also allows adding user comments to the simulation report. Allowed fields with their structure are listed below:

```yaml
{
   "film":{
      <constraint1_name>:[
         <characteristic_length>,
         <orientation>
      ],
      <constraint2_name>:[
         ...
      ]
   },
   "temperature":{
      "max":<max_temp>,
      "min":<min_temp>,
      "tolerance":<tol>
   },
   "camera_custom":{
      ...
   },
   "user_comments":{
      ...
   }
}
```

- `<constraint_name>` is the constraint name defined in FreeCad
- `<characteristic_length>` is the height (vertical surfaces) or area / perimeter (horizontal surfaces, e.g. 22.2 mm for a 100 x 80 mm board) [mm]
- `<orientation>` is `vertical`,`horizontal_up` or `horizontal_down`
- `<max_temp>` is the upper boundary of automatic film coefficient search area [Celsius]
- `<min_temp>` is the lower boundary of automatic film coefficient search area [Celsius]
- `<tol>` is the acceptable difference of calculated and simulated temperature in automatic film coefficient search [Celsius]
- `camera_custom` stores Blender camera data and is defined automatically with `tpost save-camera`
- `user_comments` the content of it will be added to the report written by `tpre report`

## Licensing

This project is published under the [Apache-2.0 License](https://www.apache.org/licenses/LICENSE-2.0).
