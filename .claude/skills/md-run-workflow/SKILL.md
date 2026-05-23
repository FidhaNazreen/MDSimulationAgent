---
name: md-run-workflow
description: Run the full GROMACS molecular-dynamics pipeline on a protein from PDB. Goes ingest → classify → prep → topology (via DialogueRunner) → solvation (four-stage charge accounting) → short EM (validation gate) → NVT → NPT → production MD → analysis (RMSD/Rg/RMSF/H-bonds/thermodynamics) → report. Produces a directory of immutable per-step artifacts (gro/top/itp/tpr/log/xtc/edr/json) plus a top-level REPORT.md whose first line is `readiness: ready | ready_with_warnings | blocked | not_validated`. Trigger when the user wants to run an MD simulation on a protein, set up lysozyme in water, prepare a system for minimization, equilibrate + simulate a protein, or any phrasing like "do the lysozyme tutorial", "build a topology for PDB X", "solvate and neutralize", "run EM as a sanity check", "equilibrate this protein at 300 K", "run a 10 ns production MD of <PDB>". The user can give a PDB id ("1AKI"), a local PDB/CIF path, or hand you a pre-built run_config.json. Only supports soluble protein-only systems; ligands/nucleic acids/membranes fail fast at the classifier with a structured reason. Default profile reproduces the canonical GROMACS lysozyme tutorial: OPLS-AA + SPC water + dodecahedron box (1.0 nm padding) + neutralize-only ion strategy + 1000-step steepest-descent EM + 100 ps NVT + 100 ps NPT + 1 ns production at 300 K / 1 bar. Set `production.enabled: false` for a prep-only run, or use the `md-prep-structure` skill.
metadata:
  minimum_mdagent_version: "0.1.0"
  skill_version: "1.0.0"
---

# md:run-workflow

End-to-end driver for the GROMACS MD pipeline.

## Setup (one-time per machine)

```bash
# 1. Install uv if not already installed:
brew install uv     # macOS
# OR  curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Install mdagent as a uv tool (pinned to a tag for reproducibility):
uv tool install --force git+https://github.com/<user>/MDSimulationAgent@v0.1.0

# 3. Make sure GROMACS is on PATH:
brew install gromacs   # macOS

# 4. (Optional) install the skills under the project or user .claude dir:
mdagent install-skills --user                 # makes them available everywhere
# OR  mdagent install-skills --project /path/to/myproject
```

Verify with:

```bash
mdagent --version
mdagent doctor --gmx-required
```

## Skill preflight (verbatim — paste into Bash before invoking)

```bash
command -v mdagent >/dev/null 2>&1 || {
  echo "mdagent not found on PATH."
  echo "Install: uv tool install --force git+https://github.com/<user>/MDSimulationAgent@v0.1.0"
  echo "PATH: ensure '$(uv tool dir --bin 2>/dev/null || echo "<uv tool bin dir>")' is on PATH."
  exit 1
}
mdagent doctor --json \
  --min-version 0.1.0 \
  --skill-name md-run-workflow \
  --skill-version 1.0.0 \
  --gmx-required \
  || { echo "Doctor failed. See output above."; exit 1; }
```

## Invocation

Tutorial-mode run on 1AKI (OPLS-AA + SPC + 100 ps NVT + 100 ps NPT + 1 ns production by default):

```bash
mdagent run-workflow \
  --runs-root ./runs \
  --pdb-id 1AKI \
  --run-id <something_meaningful>
```

With a config file:

```bash
mdagent run-workflow \
  --runs-root ./runs \
  --config /path/to/run_config.json \
  --run-id <something_meaningful>
```

Inspect a finished run:

```bash
mdagent inspect --run-root ./runs/<run_id>
```

## When to use `--stop-after`

For partial pipeline runs (e.g. prep + topology + solvation without dynamics):

```bash
mdagent run-workflow --runs-root ./runs --pdb-id 1AKI --stop-after solvation
```

Valid stopping points: `prep | topology | solvation | em | nvt | npt`.

## Build a run_config.json on the fly

When the user has specific parameters, write a `run_config.json` to disk
before invoking. Most-asked knobs:

| Knob | Default | Notes |
|---|---|---|
| `force_field` | `oplsaa` | also `amber99sb-ildn`, `charmm36-jul2022`, `gromos54a7` |
| `water_model` | `spc` | must match FF allowlist |
| `box.geometry` | `dodecahedron` | also `cubic`, `octahedron` |
| `box.padding_nm` | `1.0` | nm |
| `ion_strategy.mode` | `neutralize_only` | also `physiological_salt` (set `salt_M: 0.15`) |
| `em.step_cap` | `1000` | bump if EM didn't converge |
| `nvt.nsteps` / `npt.nsteps` | `50000` (= 100 ps at 2 fs) | shorter for tests |
| `production.nsteps` | `500000` (= 1 ns) | longer for science |
| `production.enabled` | `true` | set `false` to stop after NPT |
| `pipeline_mode` | `tutorial_reproduction` | also `general_md_prep` (drives `pdb2gmx -inter` for per-residue protonation) |
| `protonation_policy` | `propka` | in general mode: use PROPKA-predicted pKa vs. configured `ph` (requires `propka` extra). Also `ff_default` (fixed pH-7). |
| `ph` | `7.0` | only meaningful when `protonation_policy: propka` |
| `visualization.mode` | `disabled` | use `md-visualize` skill to enable |

## Reading the output

```
<runs_root>/<run_id>/
├── run_config.json
├── index.json                    # step state machine + artifact hashes
├── step_01_structure_ingest/     # original.pdb + working.pdb
├── step_02_classifier/           # classification.json
├── step_03_structure_prep/       # observations.json + mutations.json
├── step_04_topology/             # system_apo.gro/.top + posre.itp + topology_plan.json + pdb2gmx_transcript.json + protonation_decisions.json
├── step_05_solvation/            # system_ions.gro/.top/.tpr + charge_accounting.json
├── step_06_em/                   # em.gro + em.log + em_convergence.json
├── step_07_nvt/                  # nvt.{gro,cpt,xtc,log,edr}
├── step_08_npt/                  # npt.{gro,cpt,xtc,log,edr}
├── step_09_production/           # production.{gro,cpt,xtc,log,edr,tpr}
├── step_10_analysis/             # analysis.json + rmsd.xvg + gyrate.xvg + rmsf.xvg + hbnum.xvg + temperature/pressure/density.xvg
├── step_11_visualization/        # (optional) Tcl/PML scripts + PNGs
└── REPORT.md                     # readiness verdict + summary
```

Headline values from `REPORT.md`:
- **`readiness: ready`** — every gate passed; production trajectory at `step_09_production/production.xtc`.
- **`readiness: ready_with_warnings`** — chemistry/physics caveats worth reading.
- **`readiness: blocked`** — a hard validator failed; the offending step's `step_report.json` has the failure reason.
- **`readiness: not_validated`** — EM didn't converge within the step cap; bump `em.step_cap` and re-run with the same `--run-id`.

## Failure-mode triage

| Code | Where to look |
|---|---|
| `UnsupportedResidueError` | `step_02_classifier/classification.json` |
| `UnexpectedPromptError` | `step_04_topology/pdb2gmx_transcript.json` + step report's `raw_buffer_tail` |
| `ConsistencyGateFailure` | `step_05_solvation/` grompp stderr |
| `ChargeAccountingMismatch` | `step_05_solvation/charge_accounting.json` |
| `EMDiverged` / `EMStuck` | `step_06_em/em.log` |
| `CoordinateIdMapNotInjective` | `step_01_structure_ingest/coordinate_id_map.json` |

## What this skill does NOT do

- Cloud / HPC execution (RemoteExecutor not yet wired).
- PROPKA-driven protonation (general mode uses fixed pH-7 defaults).
- Free-energy / enhanced sampling.
