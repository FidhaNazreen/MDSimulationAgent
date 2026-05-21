---
name: md-run-workflow
description: Run the full GROMACS molecular-dynamics preparation pipeline on a protein from PDB. Goes ingest → classify → prep → topology (via DialogueRunner) → solvation (with four-stage charge accounting) → short EM (validation gate) → report. Produces a directory of immutable per-step artifacts (gro/top/itp/tpr/log/json) plus a top-level REPORT.md whose first line is `readiness: ready | ready_with_warnings | blocked | not_validated`. Trigger when the user wants to run an MD prep simulation on a protein, set up lysozyme in water, prepare a system for minimization, or any phrasing like "do the lysozyme tutorial", "build a topology for PDB X", "solvate and neutralize", "run EM as a sanity check". The user can give a PDB id ("1AKI"), a local PDB/CIF path, or hand you a pre-built run_config.json. v0 only supports soluble protein-only systems; ligands/nucleic acids/membranes fail fast at the classifier with a structured reason. Default profile reproduces the canonical GROMACS lysozyme tutorial: OPLS-AA + SPC water + dodecahedron box (1.0 nm padding) + neutralize-only ion strategy + 1000-step steepest-descent EM.
---

# md:run-workflow

End-to-end driver for the v0 GROMACS prep pipeline. Wraps `mdagent.orchestrator.run_workflow`.

## When to use this

Trigger phrases include: "set up <PDB> in water", "do the lysozyme tutorial", "prep <PDB> for simulation", "build a solvated/neutralized system from <PDB>", "ready <PDB> for minimization", "run the MD prep workflow on <PDB>". Use the **default-config path** for tutorial-style runs on the standard lysozyme target (1AKI). Use the **config-file path** when the user has specific force-field / box / ion / EM parameters in mind.

If the user is asking about a multi-step debug, an analysis-only request, or anything beyond ingest-through-EM, this is **not** the right skill — point them at the per-step skills (`md-prep-structure`, etc.) or the orchestrator's `inspect` command.

## What this skill does

1. Resolves the inputs (PDB id or local file).
2. Invokes the pipeline through `python -m mdagent run-workflow ...`.
3. Reports the per-step statuses + the final readiness verdict to the user.
4. Surfaces the REPORT.md and the run directory path.

## Setup (before running)

- This repo lives at `/Users/manu_jay/git_repos/MDSimulationAgent/`. The Python package is `mdagent`; deps are managed with `uv`.
- GROMACS must be on PATH (`gmx --version` should work). On macOS install via `brew install gromacs`. The current pin is **gmx 2026.2**; the architecture pin (R3-19) targets 2024.3 for tutorial parity but the recognizer was probed against 2026.2 — flag any version drift the user might care about.
- The workflow fetches PDB structures from RCSB over the network. Confirm internet is available (or accept a `--structure-path` instead).
- Wall-time on an M-series laptop is ~15 s for 1AKI tutorial mode. Larger systems scale roughly with atom count.

## Invocation

Default tutorial-reproduction run on 1AKI:

```bash
cd /Users/manu_jay/git_repos/MDSimulationAgent
uv run python -m mdagent run-workflow \
  --runs-root runs/ \
  --pdb-id 1AKI \
  --run-id <something_meaningful>
```

With a config file (preferred when the user has chosen non-default parameters):

```bash
uv run python -m mdagent run-workflow \
  --runs-root runs/ \
  --config /path/to/run_config.json \
  --run-id <something_meaningful>
```

Inspect a finished run:

```bash
uv run python -m mdagent inspect --run-root runs/<run_id>
```

## Build a run_config.json on the fly

When the user has specific parameters, write a `run_config.json` to disk before invoking. The full schema is at `schemas/v0.1.0/run_config.schema.json`; minimum required fields are `schema_version`, `pipeline_mode`, `interaction_mode`, `input.pdb_id` (or `input.structure_path`). Common knobs:

| Knob | Default | Notes |
|---|---|---|
| `force_field` | `oplsaa` | also: `amber99sb-ildn`, `charmm36-jul2022`, `gromos54a7` |
| `water_model` | `spc` | must match FF allowlist |
| `box.geometry` | `dodecahedron` | also `cubic`, `octahedron` |
| `box.padding_nm` | `1.0` | nm |
| `ion_strategy.mode` | `neutralize_only` | also `physiological_salt` (set `salt_M: 0.15`) |
| `em.step_cap` | `1000` | steepest-descent step cap |
| `em.fmax_tol_kjmolnm` | `1000.0` | convergence threshold |
| `visualization.mode` | `disabled` | use the `md-visualize` skill to enable |

## Reading the output

After the run, the directory layout is:

```
<runs_root>/<run_id>/
├── run_config.json               # the resolved config (immutable)
├── index.json                    # step state machine + artifact hashes
├── step_01_structure_ingest/     # original.pdb + working.pdb
├── step_02_classifier/           # classification.json
├── step_03_structure_prep/       # observations.json + mutations.json
├── step_04_topology/             # system_apo.gro/.top + posre.itp + topology_plan.json + pdb2gmx_transcript.json
├── step_05_solvation/            # system_ions.gro/.top/.tpr + charge_accounting.json
├── step_06_em/                   # em.gro + em.log + em_convergence.json
├── step_08_report/               # report step bookkeeping (REPORT.md proper lives at the run root)
└── REPORT.md                     # the human-facing summary
```

Headlines from `REPORT.md`:
- **`readiness: ready`** — system passed every gate; user can hand `step_06_em/em.gro` and `step_05_solvation/system_ions.top` to a downstream NVT/NPT/production run.
- **`readiness: ready_with_warnings`** — there are chemistry/physics caveats worth reading before moving on.
- **`readiness: blocked`** — a hard validator failed; the run_root's step reports identify the failure.
- **`readiness: not_validated`** — EM didn't converge within the step cap. User can re-run with a higher `em.step_cap`.

## Handling failures

- **System classified unsupported** (`UnsupportedResidueError`): the structure has ligands / nucleic acids / membrane markers. v0 only supports `chemistry={protein}` or `{protein, water}`. Tell the user which features tripped the classifier and that general-mode support is past v0.
- **`pdb2gmx` unexpected prompt** (`UnexpectedPromptError`): the GROMACS version emitted a prompt the recognizer didn't classify. Capture the raw buffer tail from the step report and surface it — likely a catalog update is needed.
- **Charge accounting mismatch** (`ChargeAccountingMismatch`): genion didn't insert the expected counter-ions. Compare `expected_anions`/`actual_anions` in `step_05_solvation/charge_accounting.json`.
- **EM didn't converge** (`EMDiverged` / `EMStuck` / verdict=`needs_longer_em`): inspect `em.log`; the simplest remedy is to raise `em.step_cap` (1000 → 5000) and re-run. If the verdict is `diverged`, look at `em_convergence.json:fmax_final` — values > 1e9 indicate a real chemistry problem upstream.

## What this skill does NOT do

- Production MD (NVT/NPT/long runs) — past v0.
- Analysis (RMSD, Rg, RMSF, H-bonds) — past v0.
- Visualization — that's the `md-visualize` skill.
- mmCIF canonical ingest — past v0; tutorial mode on 1AKI uses PDB directly.
- Cloud / HPC execution — `Executor` interface ships but only `LocalExecutor` is wired in v0.

## Verification

Once a run completes, sanity-check by running:

```bash
uv run python -m mdagent inspect --run-root runs/<run_id>
```

For 1AKI tutorial mode the canonical expectations are:
- 1 chain, 1 HIS, 8 CYS detected.
- 7331 bulk-solvent molecules (give or take ~20 due to random ion placement seed).
- 8 Cl⁻ inserted, 0 Na⁺, final total charge ≈ 0 ± 1e-3.
- EM converges (Fmax < 1000 kJ/mol/nm) in roughly 400–500 steps.
