## Update: fixes applied (2026-10-07)

All confirmed silent failures are now fixed or turned into clear errors. `python validation/silent/run_silent_audit.py --strict` reproduces none of them, and CI runs it on every push (`.github/workflows/tests.yml`). The accuracy benchmarks give the same numbers as before the fixes.

| What an engineer could get wrong before | What happens now |
|---|---|
| Touching parts meshed separately (S21) | `tpre parse-fcstd` stops: "parts 1 and 2 touch but share no nodes… use BooleanFragments" |
| Convection on a face hidden under a component (S24, −27%) | stops: "FILM 'Plate:Face6': 56 of 1490 faces are inside the model… reference the split faces" |
| FreeCAD pre-check fails but a stale `.inp` gets solved (S1) | exit 1; the old `.inp` is deleted first |
| `find_coef.sh` "converges" on stale data, loops forever, loses the answer (S2, S3, S4) | stops at the first failing step with a log per step; iteration cap; result saved to `config.json`; any mesh name |
| Bisection on a run still heating up (S12) | stops if the drift exceeds half the tolerance, warns above a tenth |
| Old `.vtk` files or output every 2nd increment break `tpost csv` (S5, S6) | `tpost convert` cleans `vtk/`; `tpre` forces OutputFrequency 1; clear error on count mismatch |
| ParaView failures ignored (S7) | `tpost preview/animation/generate-gltf` check input, exit code and output files |
| Colour bar labels ≠ colours (S8) | the range comes from the results and is written to `gltf/range.json`, which the scale-bar script reads |
| Other side effects (S9–S11, S13–S19, S22, S23) | warnings instead of silent changes; only this design's backups deleted; report written to `simulation_report.md`; README commands fixed |

New helpers:
- `tpost convert` replaces the three manual `ccx2paraview` / `mkdir` / `mv` steps.
- `tpost csv --region NAME=box` gives per-part temperatures.
- `tpre parse-fcstd --cavity-radiation` adds surface-to-surface radiation (validated, B9).
- `tpre check --inp FILE` runs the model checks on any `.inp`.
- The README has a "Common mistakes" section.

The text below is the original validation summary, from before the fixes.

## Summary (run 2026-10-07, WSL Ubuntu 26.04, CalculiX 2.23, FreeCAD 1.0.0, Elmer 26.2)

**Verdict: the numbers are right, but the workflow isn't yet safe for a PCB engineer to use unaided.**

- **Accuracy: pass.** Every code-verification benchmark passes. The CalculiX results from the project's flow match analytical solutions or an independent Elmer model:
  - steady-state rise within 0.01%;
  - 1-D conduction within 0.005%;
  - surface-to-surface radiation within 0.02%;
  - a 3-D board within 0.3%.
- **Silent failures: fail.** 23 of 24 suspects are confirmed; only S20 was not reproduced (S19 was tested with a stand-in for PCBooth, no Blender needed). Several give a wrong answer with exit code 0 and no warning. The worst are model-setup traps a GUI user can fall into:
  - **S21:** parts not fused into one mesh pass no heat to each other (the board stayed at ambient while the package hit 2000 K).
  - **S24:** referencing the original board face instead of the split face gives a **27% low** temperature.
  - **S2:** the automatic film-coefficient search "converges" on stale data when the solver fails.
- **Mesh guidance matters.** On the test board, an 8 mm mesh read 11% low, 4 mm read 2.5% low, and 2 mm was converged (GCI 1.2%). The README's "use a sparse mesh" advice for the film-coefficient search biases results low.
- **Usability:** the cold-start install took about 1 h without sudo; it can't be done as the README describes on this machine. The README example then ran first time in about 35 s. For a two-body model (heater + block), `tpost` only reports the global max/min, so the answer the engineer actually needs (block temperature) took a custom script. The human usability sessions (plan §3) were dropped at the user's request.

### Go / no-go against the plan's criteria

| Criterion | Status |
|---|---|
| B1–B7 pass | **Yes.** B1's bias is documented; B2's time constant is +1.99% (2% limit) from the solver's time stepping. |
| No open S-Blocker | **No.** S1, S2, S21 and S24 are open. S5/S6 crash loudly but cryptically; S20 was not reproduced. |
| ≥ 80% correct answers in usability tasks | Dropped (user decision) |
| Median time to first result ≤ 4 h | Cold start ≈ 1 h for the agent with the no-sudo script; not measured with engineers |
| SUS ≥ 68 | Dropped (user decision) |

### Fixes, highest impact first

1. **Guard the model setup in `tpre`:**
   - refuse or warn when a mesh has several solids that share no nodes (S21);
   - refuse or warn when a boundary condition lands on an internal interface (S24);
   - print the total power, radiating area and convective area per constraint so mistakes are visible.
2. **Fail loudly:**
   - non-zero exit on FreeCAD prerequisite failure (S1);
   - `find_coef.sh`: add `set -euo pipefail`, an iteration cap and distinct exit codes, stop hiding solver output, and save the result (S2, S3, S4).
3. **Per-body results** in `tpost` (mean/max/min for each solid). Without them, any model with a fixed-temperature part reports nothing useful.
4. **Surface-to-surface radiation** as a `tpre` option. It's needed for gaps and enclosures. The `.inp` patch in `benchmarks/pipeline.py` is validated (B9, 0.02%).
5. **`tpost csv`:** support output frequency > 1, clear stale `.vtk` files, and give a clear error (S5, S6).
6. **Docs:**
   - use A/P as the characteristic length for horizontal plates (−27% h with the current advice);
   - radiation is as large as convection on boards;
   - mesh-size guidance;
   - a no-sudo / WSL install route.
7. **Stop surprising side effects:** deleting backups (S14), overwriting `README.md` (S15), silently forcing transient analysis (S9).

### The real question: 3×2×2 in bare block, 15 in from a 200 °F PID element, closed box, no fan (§4)

**The block never reaches 200 °F unless the box is almost perfectly insulated.** The PID holds the *element* at 200 °F, so the element can only put out as much heat as its small surplus over the box allows. Meanwhile the box loses heat to the room. Everything settles where heater output equals wall loss:

| Assumed box | Block levels off at | 95% of that reached after |
|---|---|---|
| 4×4 in element, 24×16×16 in box, 1 in insulation (baseline) | ~99 °F | ~6 h |
| same, bare sheet-metal box | ~85 °F | ~5 h |
| same, 4 in insulation | ~125 °F | ~14 h |
| 12×12 in element, 1 in insulation | ~155 °F | ~4 h |
| 12×12 in element, 4 in insulation | ~181 °F | ~5 h |
| perfectly insulated box (theoretical limit) | 200 °F | within 5 °F after ~25 h |

- **The bare block follows the box air.** At ε ≈ 0.07 it absorbs very little radiation; at 15 in the element fills under 1% of its view. So the block is essentially an air thermometer with about a 2 h lag. Anodising it barely changes the final temperature, just makes it lag less.
- **To get the block to 200 °F in a reasonable time:** control the PID on the *box air* (not the element), let the element run hotter, add a fan, or mount the block on a heated plate.
- **Trust:** the lumped model matches the validated 3-D FEM case within 2% on steady rise. Its view factors are exact. Box air is treated as one well-mixed temperature, which is the main approximation; real stratification makes the top of the box warmer.

### Earlier placeholder case: heater → still air → aluminium block (§3)

The heater is held at 150 °C, 20 mm from a 50×50×20 mm 6061 block, in 25 °C still air:
- **Anodised or painted block (ε 0.85):** it settles **+4.7 K above ambient (29.7 °C)**. It reaches 63% of the rise in 24 min and 95% in 74 min. It absorbs about 0.43 W.
- **Bare block (ε 0.09):** it settles only **+1.2 K (26.2 °C)**, with 63% in 59 min and 95% in 169 min. It absorbs about 0.05 W. Surface finish is the dominant design lever.
- **Temperature map:** the block is uniform to within 0.03 K, because aluminium spreads the heat. The warm spot sits opposite the heater.
- **Trust:**
  - The radiation coupling is validated (B9).
  - The mesh is converged: 3.0 mm and 2.5 mm meshes agree within 0.001%.
  - The film coefficients converged in two passes.
- **Not modelled: air movement between the parts.** The hand estimate of direct gas conduction across the gap is about 0.1 W, **twice the bare block's radiative input** and a quarter of the anodised one. Treat the bare-block result as a lower bound.
- **Layout matters:** if the block sits *above* the heater, its plume will dominate and this model will badly under-predict. Measurement or CFD is needed in that case.
- **Time-step caveat:** the time step was 300 s (about 1/10 to 1/5 of the time constant), so the warm-up times are good to roughly ±10%.
