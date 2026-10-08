# Friction log

One row per obstacle. Fill in during the cold-start run (§0) and each usability session (§3).

- **Severity:** Blocker (cannot continue without help) · Major (more than 10 min lost, or a workaround needed) · Minor (annoyance)
- **Category:** install · docs · CLI · FreeCAD modelling · results interpretation · silent error

| Session | Participant | Task | Step / command | Symptom (what they saw) | Minutes lost | Severity | Category | Helped by observer? | Linked finding (S#/B#) |
|---|---|---|---|---|---|---|---|---|---|
| 0 cold start 2026-10-07 | Claude (agent) | T1 | README `sudo apt install …` | No passwordless sudo in WSL; README assumes root for apt, FreeCAD and ParaView. Installed everything user-level instead (micromamba for ccx/jq, AppImage/tarball under `~/tss-tools`) | 15 | Major | install | – | – |
| 0 | agent | T1 | `pipx install .` | WSL Ubuntu 26.04 ships Python 3.14; pyproject pins `>=3.11,<3.12` and `bpy==4.4.0` exists only for 3.11. Needed `uv python install 3.11` | 5 | Major | install | – | – |
| 0 | agent | T1 | git checkout on Windows | `core.autocrlf=true` gives CRLF in `find_coef.sh`/`blender_animation.sh` → `$'\r': command not found` in WSL. Must clone inside WSL | 5 | Major | install / docs | – | – |
| 0 | agent | T1 | FreeCAD AppImage | Bundles its own `ccx` 2.22 and `gmsh` 4.12, which the README doesn't mention; conda-forge `ccx` is 2.23, README says 2.20. Three solver versions on one machine | 5 | Minor | docs | – | S23 |
| 0 | agent | T1 | `import FreeCAD` | Prepends FreeCAD's bin dir to PATH, so `simulation.json` reports ccx 2.22 while the shell runs 2.23 | 10 | Minor | silent error | – | S23 |
| 0 | agent | T1 | Ubuntu 26.04 coreutils | `tail -3` rejected (Rust coreutils need `tail -n 3`) | 2 | Minor | install | – | – |
| 0 | agent | T1 | Elmer | Not on conda-forge or in Ubuntu repos; built from source with conda compilers (~10 min); needs an `LD_LIBRARY_PATH` wrapper for OpenBLAS | 20 | Major | install | – | B6 |
| 0 | agent | T2 | README walkthrough (`parse-fcstd` → `ccx` → `ccx2paraview` → `csv` → `plot` → `preview`) | Worked first time, ~35 s total; 84 increments, 19 graphs, 6 previews (WSLg rendering OK) | 0 | – | – | – | – |
| 0 | agent | B6 | FreeCAD → Elmer solver (headless) | Elmer task crashes on `ViewObject` (GUI-only) after writing the case. Generated `case.sif` merges package-top flux with plate-top convection (both named "Face6") and drops the FR4 material. Replaced by an independent gmsh→Elmer model | 25 | Major | FreeCAD modelling / silent error | – | B6 |
| 0 | agent | case | heater + block | `tpost csv`/`plot`/`preview` report only global max/min, so with a fixed-temperature heater in the model they show 150 °C and say nothing about the block. Block temperatures needed a custom script reading the `.vtk` per region | 20 | Major | results interpretation | – | – |
| 0 | agent | case | gap radiation | FreeCAD can only write radiation to ambient; surface-to-surface radiation needs a post-edit of the `.inp` (`R3` → `R3CR`). A naive edit silently patched 0 faces (comment lines inside `*RADIATE`) | 15 | Major | FreeCAD modelling / silent error | – | B9 |

## Per-session summary

| Session | Participant | T1 install | T2 example | T3 model | T4 answer (2 W / 3 W) | Correct ±10%? | Confidence 1–5 | T5 compare | T6 find_coef | Time to first result | Interventions | SUS |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| | | | | | | | | | | | | |
