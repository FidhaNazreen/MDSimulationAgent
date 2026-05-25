# Getting started

This walkthrough takes a fresh `mdagent init-project` directory and
runs a short MD simulation on hen-egg-white lysozyme (1AKI) end-to-end.

Total time: ~2 minutes (on an M-series laptop). Everything is local —
no internet needed.

## 0. Prerequisites

You need `mdagent` (the agentic CLI) and `gmx` (GROMACS) on PATH. If
not yet installed:

```bash
brew install uv     # macOS — or: curl -LsSf https://astral.sh/uv/install.sh | sh
uv tool install --force git+https://github.com/mjayadharan/MDSimulationAgent@v0.1.0
brew install gromacs
```

Confirm both:

```bash
mdagent --version       # → mdagent 0.1.0
gmx --version | head -3 # → GROMACS version: 2026.2
```

## 1. Verify the kit is wired up

From this directory:

```bash
./verify.sh
```

Expected output: a list of "✓" lines, ending in
`✓ starter kit verified`. This checks every file the kit needs is
present and every shipped `run_configs/*.json` validates against the
schema. **No GROMACS needed yet.**

## 2. Run a short simulation

```bash
./verify.sh --run-smoke
```

This invokes `mdagent run-workflow` against
`run_configs/lysozyme_short.json`. The pipeline runs:

1. Ingest the bundled `structures/1aki.pdb`.
2. Classify (protein-only, soluble — supported).
3. Prep (analyze chains, HIS, CYS).
4. Topology via `gmx pdb2gmx`.
5. Solvation + ion neutralization (8 Cl⁻ for lysozyme's +8 charge).
6. Short EM (steepest-descent, ≤1000 steps).
7. NVT equilibration (2 ps).
8. NPT equilibration (2 ps).
9. Production MD (4 ps).
10. Analysis (RMSD, Rg, RMSF, H-bonds, Temperature/Pressure/Density).
11. Report.

When it finishes, look at the result:

```bash
mdagent inspect --run-root ./runs/smoke
```

`REPORT.md` should start with `# REPORT — readiness: **ready**`.

## 3. Read the analysis output

```bash
python3 -c "
import json
data = json.loads(open('./runs/smoke/step_10_analysis/analysis.json').read())
print('RMSD summary:', data['rmsd']['summary'])
print('Rg summary  :', data['radius_of_gyration']['summary'])  # expect ~1.4 nm for lysozyme
print('NPT density :', data['thermodynamics']['density_kgm3_npt']['summary'])
"
```

For lysozyme at 300 K you should see:

- Rg mean ≈ **1.4 nm** (literature value for native-state lysozyme).
- NPT density ≈ **1000 kg/m³** (water + protein).
- RMSD < ~0.3 nm (very short trajectory — noisy).

## 4. Customize a config

The shipped configs are the source of truth. To tweak, copy one:

```bash
cp ./run_configs/lysozyme_short.json ./run_configs/my_run.json
# Edit my_run.json — e.g. change force_field to amber99sb-ildn, water_model to tip3p.
mdagent run-workflow --runs-root ./runs --config ./run_configs/my_run.json --run-id mine
```

Common knobs (full list in the upstream README):

| Knob | Default | Notes |
|---|---|---|
| `force_field` | `oplsaa` | also `amber99sb-ildn`, `charmm36-jul2022` |
| `water_model` | `spc` | must match FF allowlist |
| `box.padding_nm` | `1.0` | nm around the solute |
| `ion_strategy.mode` | `neutralize_only` | also `physiological_salt` (`salt_M: 0.15`) |
| `nvt.nsteps` / `npt.nsteps` | `1000` (= 2 ps) | bigger for real science |
| `production.nsteps` | `2000` (= 4 ps) | bigger for real production |
| `pipeline_mode` | `tutorial_reproduction` | also `general_md_prep` (`-inter` per-residue protonation) |

## 5. Use Claude Code

Open a Claude Code session in this directory and ask, for example:

> *"Run the lysozyme tutorial."*
> *"Set up 1AKI for simulation at 350 K using AMBER99SB-ILDN."*
> *"Prep this PDB file at /tmp/my_protein.pdb but don't run dynamics yet."*

Claude reads the three packaged skills under `.claude/skills/`,
chooses `md-run-workflow` (or `md-prep-structure` if no dynamics), and
runs the CLI for you. Failures get surfaced verbatim from the step
reports.

## 6. Visualize

VMD (or PyMOL) is best-effort. The `md-visualize` skill writes Tcl/PML
scripts regardless of whether the viewer is installed:

```bash
mdagent visualize --run-root ./runs/smoke --viewer auto --checkpoints all --render both
```

After this, look in `runs/smoke/step_10_visualization_cli/<checkpoint>/`.
If VMD wasn't installed: scripts are still there; install VMD later
(`brew install --cask vmd` on macOS) and run them.

## 7. Resume a crashed / changed run

Re-invoke `mdagent run-workflow` with the **same `--run-id`**. The
orchestrator detects the existing run, recovers any `running` steps
left by a dead process, recomputes each `succeeded` step's
fingerprint against the current config + tool versions + agent code,
invalidates anything stale, and resumes from the first non-succeeded
step. Steps whose inputs and parameters didn't change are kept.

```bash
mdagent run-workflow --runs-root ./runs --config ./run_configs/lysozyme_short.json --run-id smoke
# … re-runs only the steps that need to.
```

## Next

- The `lysozyme_rcsb_tutorial.json` config does the full canonical
  GROMACS lysozyme tutorial (~1 ns production, ~hour on a laptop). It
  fetches 1AKI live from RCSB.
- The `general_md_prep_example.json` config exercises
  `pipeline_mode: "general_md_prep"` which drives `pdb2gmx -inter` for
  per-residue protonation prompts (LYS / ARG / ASP / GLU / HIS / CYS).
  By default it uses fixed pH-7 defaults. **Set
  `"protonation_policy": "propka"`** and install the optional `propka`
  extra to switch to PROPKA-driven per-residue pKa predictions:

  ```bash
  uv tool install --force --with propka git+https://github.com/mjayadharan/MDSimulationAgent@v0.1.0
  ```

  Then with `"protonation_policy": "propka"` and a chosen `"ph"` in
  the config, the topology step picks each LYS/ASP/GLU/HIS answer
  based on the residue's predicted pKa vs. that pH. For example
  lysozyme HIS-15 (pKa ≈ 6.3) ends up as HIE (neutral) at pH 7 and
  HIP (protonated) at pH 5.
- For your own structures, drop them in `structures/` and copy a config
  to point at them via `input.structure_path`.
