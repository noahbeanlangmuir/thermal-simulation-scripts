# Validation workstation setup (Windows 11 + WSL2 Ubuntu)

This installs everything the validation plan needs inside your existing WSL **Ubuntu 26.04**. It takes about 45 minutes and roughly 3 GB of downloads.

| Tool | Version | Used for |
|---|---|---|
| CalculiX (`ccx`) | distro package (README validated 2.20) | the solver |
| Python 3.11 + project (`tpre`, `tpost`, `ccx2paraview`) | 3.11 (pinned by pyproject) | pre/post-processing |
| FreeCAD | 1.0.0 (py311 AppImage) | models, constraints, mesh, `.inp` export |
| ParaView (`pvpython`) | 6.0.0 | previews, animations, glTF |
| Elmer | latest | cross-code check (benchmark B6) |
| jq, yq, ffmpeg, rsvg-convert, ImageMagick, gmsh | distro | scripts and media |

> **Fastest route (no sudo, verified 2026-10-07):** this is what the validation run used on this machine. It installs everything under `~/tss-tools` without root, using a FreeCAD that bundles its own `ccx` and `gmsh`. In Ubuntu, run:
>
> ```bash
> git clone /mnt/c/Users/NoahBean/Documents/GitHub/thermal-simulation-scripts ~/thermal-simulation-scripts
> ```
>
> ```bash
> WITH_ELMER=1 bash ~/thermal-simulation-scripts/validation/install_user.sh
> ```
>
> ```bash
> source ~/tss-env.sh
> ```
>
> Then skip to [§8 Verify everything](#8-verify-everything). The `sudo`-based steps below are the README route, kept for the usability study.

> **Log the friction.** You are also doing the "cold-start run" from §0 of the plan. Whenever a step differs from the project README, or something fails, add a row to [friction_log.md](friction_log.md).

---

## 0. Open Ubuntu and (optionally) give it more RAM

Open the **Ubuntu** app from the Start menu. Run every command below in that terminal unless a step says otherwise.

WSL currently gets 7 GB of RAM, which is fine for the benchmarks. Fine meshes in ccx may need more. To raise it, create `C:\Users\NoahBean\.wslconfig` on the Windows side with:

```ini
[wsl2]
memory=12GB
```

Then run `wsl --shutdown` in PowerShell and reopen Ubuntu.

## 1. System packages

```bash
sudo apt update
```

```bash
sudo apt install -y calculix-ccx git curl wget tar xz-utils jq yq ffmpeg librsvg2-bin imagemagick gmsh libxrender1 libgl1 libegl1 libglu1-mesa
```

```bash
sudo apt install -y libosmesa6 || echo "libosmesa6 not available - fine under WSLg"
```

```bash
ccx -v
```

Notes:
- The README's `libgl1-mesa-glx` doesn't exist on Ubuntu 24.04 or later; `libgl1` replaces it. Log this as friction.
- Write down the ccx version that `ccx -v` prints. The README was validated with 2.20, and Ubuntu 26.04 ships a newer one. That matters for finding S6, because `tpost csv` parses the `.sta` file by fixed column positions.

## 2. Get the repo inside WSL

The Windows checkout has CRLF line endings (`core.autocrlf=true`), and bash scripts like `find_coef.sh` break with `$'\r': command not found`. Clone a Linux copy instead, then bring over the uncommitted `validation/` folder:

```bash
git clone /mnt/c/Users/NoahBean/Documents/GitHub/thermal-simulation-scripts ~/thermal-simulation-scripts
```

```bash
cp -r /mnt/c/Users/NoahBean/Documents/GitHub/thermal-simulation-scripts/validation ~/thermal-simulation-scripts/
```

```bash
cd ~/thermal-simulation-scripts && file src/preprocessing/find_coef.sh
```

The output must **not** mention `CRLF`.

## 3. Python 3.11 and the project

Ubuntu 26.04 ships Python 3.14, but the project requires exactly 3.11 (and `bpy==4.4.0` only exists for 3.11). `uv` provides 3.11 without touching the system Python:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh && source ~/.local/bin/env
```

```bash
cd ~/thermal-simulation-scripts && uv python install 3.11 && uv venv --python 3.11 .venv
```

```bash
source .venv/bin/activate && uv pip install -e . pytest
```

The `bpy` wheel alone is about 350 MB, so this download takes a while. If the editable (`-e`) install fails, run `uv pip install . pytest` instead.

Make the venv activate automatically in every new terminal:

```bash
echo 'source ~/thermal-simulation-scripts/.venv/bin/activate' >> ~/.bashrc
```

Check:

```bash
tpre --help && tpost --help && which ccx2paraview
```

> This uses a venv, not the README's `pipx install`, so the validation tests can import the source and pick up fixes immediately. The usability participants should still follow the README as written.

## 4. FreeCAD 1.0.0

```bash
cd /tmp && wget -O freecad.AppImage "https://github.com/FreeCAD/FreeCAD/releases/download/1.0.0/FreeCAD_1.0.0-conda-Linux-x86_64-py311.AppImage"
```

```bash
chmod +x freecad.AppImage && ./freecad.AppImage --appimage-extract > /dev/null && rm freecad.AppImage
```

```bash
sudo rm -rf /usr/local/share/freecad && sudo mv squashfs-root /usr/local/share/freecad && sudo ln -sf /usr/local/share/freecad/AppRun /usr/local/bin/freecad
```

```bash
echo 'export FREECAD_PATH="/usr/local/share/freecad"' >> ~/.bashrc && source ~/.bashrc
```

Extracting the AppImage means no FUSE is needed.

**Check that the project can import FreeCAD.** This mirrors exactly what `src/preprocessing/parse_fcstd.py:14-19` does:

```bash
cd ~/thermal-simulation-scripts && python -c "import os,sys; fc=os.environ['FREECAD_PATH']; sys.path.insert(0, fc+'/usr/lib/python3.11/site-packages'); sys.path.append(fc+'/usr/lib'); import FreeCAD; from femtools import ccxtools; print('FreeCAD', '.'.join(FreeCAD.Version()[:3]), '+ femtools OK')"
```

If that fails with an `ImportError` about a `.so` file, or crashes, rebuild the venv on FreeCAD's own bundled Python 3.11 and repeat the check:

```bash
cd ~/thermal-simulation-scripts && rm -rf .venv && uv venv --python "$FREECAD_PATH/usr/bin/python" .venv && source .venv/bin/activate && uv pip install -e . pytest
```

Record which variant worked in the friction log; it isn't covered by the README.

**GUI check.** WSLg on Windows 11 shows Linux windows directly. You need the GUI to inspect benchmark models and for the usability sessions:

```bash
freecad &
```

## 5. ParaView 6.0.0

```bash
sudo mkdir -p /opt/paraview && sudo wget -O /opt/paraview/paraview.tar.gz "https://www.paraview.org/paraview-downloads/download.php?submit=Download&version=v6.0&type=binary&os=Linux&downloadFile=ParaView-6.0.0-MPI-Linux-Python3.12-x86_64.tar.gz"
```

```bash
sudo tar -xzf /opt/paraview/paraview.tar.gz --strip-components=1 -C /opt/paraview && sudo rm /opt/paraview/paraview.tar.gz
```

```bash
echo 'export PATH=/opt/paraview/bin:$PATH' >> ~/.bashrc && source ~/.bashrc
```

Check rendering works, since `tpost preview` needs it:

```bash
cd /tmp && pvpython -c "import paraview.simple as p; p.Sphere(); p.Show(); p.SaveScreenshot('/tmp/pv_test.png')" && ls -la /tmp/pv_test.png
```

If that fails with OpenGL/EGL errors, retry with `pvpython --force-offscreen-rendering -c "..."`. If only the flag works, log it: `tpost preview/animation/generate-gltf` call `pvpython` without it, and they hide the failure (finding S7).

## 6. Elmer (cross-code check, B6)

Try the official PPA first:

```bash
sudo add-apt-repository -y ppa:elmer-csc-ubuntu/elmer-csc-ppa && sudo apt update && sudo apt install -y elmerfem-csc
```

If the PPA has no build for 26.04 (apt says the repository "does not have a Release file"), remove it and build from source instead (about 15 minutes on 16 cores):

```bash
sudo add-apt-repository -y -r ppa:elmer-csc-ubuntu/elmer-csc-ppa && sudo apt install -y cmake gfortran g++ libblas-dev liblapack-dev
```

```bash
git clone --depth 1 https://github.com/ElmerCSC/elmerfem.git ~/elmerfem && cmake -S ~/elmerfem -B ~/elmerfem/build -DCMAKE_INSTALL_PREFIX=/opt/elmer -DWITH_MPI=OFF
```

```bash
cmake --build ~/elmerfem/build -j"$(nproc)" && sudo cmake --install ~/elmerfem/build && echo 'export PATH=/opt/elmer/bin:$PATH' >> ~/.bashrc && source ~/.bashrc
```

FreeCAD finds `ElmerSolver` and `ElmerGrid` on `PATH`. If it doesn't, set them under FreeCAD → Edit → Preferences → FEM → Elmer.

## 7. Optional: Blender/PCBooth

Only needed to validate the Blender render flow (finding S19). Install [PCBooth](https://github.com/antmicro/pcbooth) by following its README. Skip this otherwise; nothing else depends on it.

---

## 8. Verify everything

Open a **new** Ubuntu terminal so `.bashrc` is reloaded, then:

```bash
cd ~/thermal-simulation-scripts && for c in ccx pvpython freecad ccx2paraview tpre tpost jq yq ffmpeg rsvg-convert composite gmsh ElmerSolver; do printf '%-14s' "$c"; command -v "$c" || echo MISSING; done
```

Every line should show a path. `ElmerSolver` can be missing until you reach benchmark B6.

Run the validation checks that already exist:

```bash
python -m pytest validation -q
```

Expected: `32 passed, 2 xfailed`.

```bash
python validation/silent/run_silent_audit.py
```

Expected: the same CONFIRMED list as on Windows (see [silent/results.md](silent/results.md)).

## 9. Smoke test: README example, end to end

Work on a **copy**. `tpre parse-fcstd` rewrites the `.FCStd` in place and deletes backup files next to it (findings S9 and S14).

```bash
rm -rf /tmp/smoke && cp -r ~/thermal-simulation-scripts/designs /tmp/smoke && cd /tmp/smoke
```

```bash
tpre parse-fcstd --fcstd example.FCStd && tpre report
```

```bash
export OMP_NUM_THREADS=16 && time ccx FEMMeshGmsh
```

```bash
ccx2paraview FEMMeshGmsh.frd vtk && mkdir -p vtk && mv *.vtk vtk/
```

```bash
tpost csv && tpost plot && tpost preview
```

```bash
head -5 temperature.csv && ls graphs previews
```

You should see a `temperature.csv` with rising max temperatures, 18 `.jpg` files in `graphs/`, and 6 `.png` files in `previews/`. Note how long `ccx` took.

When this works, the environment is ready for benchmarks B2–B8 and the toolchain-dependent findings (S4, S5, S6, S19, S20, S21).

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `$'\r': command not found` | Scripts came from the Windows checkout | Use the WSL clone from step 2 |
| `FREECAD_PATH is not set`, then `NameError: FreeCAD` | `.bashrc` not reloaded | Open a new terminal or run `source ~/.bashrc` |
| `bpy` / `numpy==1.24.3` won't install | venv is not Python 3.11 | `python --version` inside the venv; redo step 3 |
| `tpost preview` exits instantly with no images | pvpython failed, and the error is swallowed (S7) | From the results folder, run `pvpython ~/thermal-simulation-scripts/src/postprocessing/create_previews.py` directly to see the error |
| `ccx` gets "Killed" | Out of memory | Raise memory in `.wslconfig` (step 0) or use a coarser mesh |
| FreeCAD window doesn't appear | WSLg not running | In PowerShell: `wsl --update`, then `wsl --shutdown` |
