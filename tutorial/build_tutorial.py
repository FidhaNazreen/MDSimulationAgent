"""Source-of-truth for tutorial/MD_simulation_with_agents.ipynb.

Run `python tutorial/build_tutorial.py` to regenerate the notebook
whenever the architecture or skills change. The notebook is intended to
be opened locally (`jupyter notebook tutorial/MD_simulation_with_agents.ipynb`)
or read on GitHub.

Each new pipeline feature should add (1) a markdown cell explaining it
and (2) a code cell with an executable usage example. Keep the notebook
linear — readers should be able to run cells top-to-bottom.
"""

from __future__ import annotations

from pathlib import Path

import nbformat as nbf

NOTEBOOK_PATH = Path(__file__).parent / "MD_simulation_with_agents.ipynb"

# ---- Cell builders -----------------------------------------------------


def md(text: str) -> nbf.notebooknode.NotebookNode:
    return nbf.v4.new_markdown_cell(text.rstrip() + "\n")


def code(text: str) -> nbf.notebooknode.NotebookNode:
    return nbf.v4.new_code_cell(text.strip("\n"))


# ---- Notebook content --------------------------------------------------

CELLS: list[nbf.notebooknode.NotebookNode] = [
    md("""
# MD Simulation with Claude skills + multi-agent pipeline

This tutorial shows how to run a molecular-dynamics (MD) preparation workflow
on a protein with **one natural-language instruction**, using the Claude skills
that ship with `mdagent`.

The user says something like:

> *"Set up lysozyme in water and minimize it."*

The right Claude skill (`md:run-workflow`) routes this through a small
pipeline of specialized sub-agents that handle structure ingest, classification,
topology generation (driving the interactive GROMACS `pdb2gmx` deterministically),
solvation, ion neutralization, and an energy-minimization validation gate.
A final REPORT.md tells you whether the system is **ready** to use — or what
exactly went wrong if not.

This notebook is generated from `tutorial/build_tutorial.py` — re-run that
script to refresh after the architecture changes.
"""),
    md("""
## Install — one command, then it's transferable

`mdagent` is shipped as an installable tool that lives outside any
particular project. After install you can use the skills from any
directory; no `cd` into a checkout required.

```bash
# 1. Install uv (skip if you already have it)
brew install uv     # macOS — or: curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Install mdagent (pinned to a git tag for reproducibility)
uv tool install --force git+https://github.com/<user>/MDSimulationAgent@v0.1.0

# 3. Make sure GROMACS is on PATH (for any step past prep)
brew install gromacs   # macOS

# 4. Install the Claude skills so Claude Code can discover them
mdagent install-skills --user                  # → ~/.claude/skills/
# OR  mdagent install-skills --project /path/to/myproject  # → ./.claude/skills/
```

Verify the install:

```bash
mdagent --version            # → mdagent 0.1.0
mdagent doctor --gmx-required
mdagent self-test resources  # confirms schemas + skills load
```

To upgrade to a newer release, reinstall with a fresh tag:

```bash
uv tool install --force git+https://github.com/<user>/MDSimulationAgent@v0.2.0
```
"""),
    md("""
## What's in the box

```
MDSimulationAgent/
├── skills/                       # Claude skill manifests (read by Claude Code)
│   ├── gpt-critique-loop/        # adversarial GPT critique helper
│   ├── md-run-workflow/          # the canonical 'do the whole pipeline' skill
│   ├── md-prep-structure/        # ingest+classify+prep only
│   └── md-visualize/             # VMD/PyMOL rendering at checkpoints
├── src/mdagent/                  # Python implementation
│   ├── steps/                    # one module per pipeline step
│   ├── dialogue/                 # PTY-driven driver for interactive gmx tools
│   ├── orchestrator.py           # runs the DAG, handles resume + fingerprints
│   └── cli.py                    # `python -m mdagent run-workflow ...`
├── schemas/v0.1.0/               # JSON Schemas for every artifact format
├── runs/                         # where you'll find your outputs
└── tutorial/                     # this notebook
```
"""),
    md("""
## The agentic pipeline

When you ask `md:run-workflow` to set up a protein, the orchestrator dispatches
through these phases in order:

| # | Step | What the agent does |
|---|------|---------------------|
| 1 | `StructureIngest` | Fetches the PDB / mmCIF; in general mode emits a `coordinate_id_map.json` that verifies the mmCIF↔PDB bridge is one-to-one. |
| 2 | `SystemClassifier` | Multi-label classification (`chemistry`, `assembly`, `environment`, `unsupported_features`). v0 supports `protein_only_soluble`; everything else fails fast with a structured reason. |
| 3 | `StructurePrep` | Analyzes chains, histidines, cysteines, residue counts; emits `observations.json` + `mutations.json`. In tutorial mode strips HETATMs. |
| 4 | `Topology` | Plans FF/water/termini, then drives `gmx pdb2gmx` deterministically via a PTY-based `DialogueRunner` with a `Pdb2GmxPromptRecognizer`. Records the full decision trace. |
| 5 | `Solvation` | `editconf` → `solvate` → grompp → `genion -neutral`. Four-stage charge accounting per R2-17: pre-ion / expected ions / actual ions / final charge. |
| 6 | `ShortEM` | `grompp` + 1000-step steepest-descent EM as a **validation gate**. Four-way verdict: `converged | needs_longer_em | diverged | stuck`. |
| 7 | `NVT` | Position-restrained NVT equilibration (default 100 ps at 300 K). Heats the system and lets the solvent relax around the restrained protein. |
| 8 | `NPT` | Position-restrained NPT equilibration (default 100 ps at 300 K / 1 bar). Equilibrates the box volume / density. Velocities continue from NVT. |
| 9 | `Production` | Free MD (no restraints). Default 1 ns; trajectory in `production.xtc`. Disable with `production.enabled: false` for prep-only runs. |
| 10 | `Analysis` | Drives `gmx rms`, `gmx gyrate`, `gmx rmsf` against the production trajectory. Emits `analysis.json` with time-series + summary stats plus the raw `.xvg` files for re-plotting. Skipped when production is disabled. |
| 11 | `Visualization` | (opt-in) renders VMD/PyMOL snapshots at requested checkpoints; writes Tcl/PML scripts unconditionally so the user can re-render later. |
| 12 | `Report` | Regenerates `REPORT.md` from on-disk truth; the first line is `readiness: ready | ready_with_warnings | blocked | not_validated`. |

Each step emits an immutable `step_report.json` + `step_fingerprint.json`. The
fingerprint is a SHA-256 over `(inputs_hash, parameters_hash, profile_hash,
mode_hash, tool_hash, schema_hash, code_hash)` — that's what makes
**resume-after-crash** and **config-drift invalidation** correct (slice 4c).
"""),
    md("""
## Quick start — runs anywhere `mdagent` is installed

After the one-time install above you don't need a repo checkout. Pick any
working directory; the runs go under `--runs-root` and the skills locate
the package via PATH.



Three flavors:

- **Prep-only** (ingest → topology → solvation → EM): pass `--production-disabled` or
  set `production.enabled: false` in the config. Useful for sanity-checking a
  system before committing to long MD.
- **Equilibration only** (prep + NVT + NPT): same plus `production.enabled: false`.
- **Full pipeline** (prep + NVT + NPT + production trajectory): the default.

The fastest test invocation (prep + EM + NVT + NPT, ~90 s on an M-series laptop):
"""),
    code("""
import subprocess, json
from pathlib import Path

runs_root = Path("./tutorial_runs").resolve()
runs_root.mkdir(parents=True, exist_ok=True)

# Build a config: tutorial mode, 2 ps NVT + 2 ps NPT, no production (~90 s).
cfg = {
    "schema_version": "0.1.0",
    "pipeline_mode": "tutorial_reproduction",
    "interaction_mode": "noninteractive_defaults",
    "input": {"pdb_id": "1AKI"},
    "force_field": "oplsaa", "water_model": "spc",
    "box": {"geometry": "dodecahedron", "padding_nm": 1.0, "cutoff_nm": 1.0},
    "ion_strategy": {"mode": "neutralize_only", "cation": "NA", "anion": "CL", "random_seed": 42},
    "em": {"step_cap": 1000, "fmax_tol_kjmolnm": 1000.0},
    "nvt": {"nsteps": 1000, "dt_ps": 0.002, "temperature_K": 300.0, "random_seed": 42},
    "npt": {"nsteps": 1000, "dt_ps": 0.002, "temperature_K": 300.0, "pressure_bar": 1.0},
    "production": {"enabled": False},   # prep+equilibration only
}
cfg_path = runs_root / "tutorial_quick.json"
cfg_path.write_text(json.dumps(cfg, indent=2, sort_keys=True))

# `mdagent` is on PATH after `uv tool install`. No `cd`, no `uv run`.
result = subprocess.run(
    ["mdagent", "run-workflow",
     "--runs-root", str(runs_root),
     "--config", str(cfg_path),
     "--run-id", "tutorial-1aki"],
    capture_output=True, text=True,
)
print(result.stdout)
"""),
    md("""
That command produced a directory full of artifacts under
`tutorial/runs/tutorial-1aki/`. The most important file is `REPORT.md`:
"""),
    code("""
report_path = Path("./tutorial_runs/tutorial-1aki/REPORT.md")
print(report_path.read_text() if report_path.is_file() else "(no report yet — run the cell above first)")
"""),
    md("""
For 1AKI tutorial-mode you should see:

- 1 chain, 1 histidine, 8 cysteines.
- ~7331 bulk-solvent molecules (± random ion placement noise).
- **8 Cl⁻** inserted, **0 Na⁺**, final total charge ≈ 0.
- EM **converges** in ~400–500 steps with Fmax < 1000 kJ/mol/nm.
- `readiness: **ready**`.
"""),
    md("""
## Driving the pipeline by natural-language prompt

In a Claude Code session, you don't run the CLI directly — you just say
what you want. The `md:run-workflow` skill (in `skills/md-run-workflow/SKILL.md`)
tells Claude how to map natural-language requests to the right invocation.

Examples of phrasings that route to `md:run-workflow`:

- *"Set up lysozyme in water and minimize it."*
- *"Prep PDB 1AKI for simulation using OPLS-AA."*
- *"Build a topology + solvated box for 6LU7, neutralize with NaCl at 150 mM."*
- *"I want a system ready to minimize from this PDB file: /tmp/protein.pdb"*

Claude reads the SKILL.md frontmatter (`description`) to decide whether to
invoke; the body tells it how (where the CLI lives, what flags to pass,
what to surface to the user, how to triage failures).

You can also invoke the skill from any Claude conversation that has the
mdagent repo's `skills/` directory on its skill-search path.
"""),
    md("""
## Anatomy of a run directory

```
runs/<run_id>/
├── run_config.json               # the resolved config (immutable)
├── index.json                    # step state machine + artifact hashes (only mutable file at root)
├── step_01_structure_ingest/
│   ├── original.pdb              # raw input
│   ├── working.pdb               # what downstream steps consume
│   ├── step_report.json
│   └── step_fingerprint.json
├── step_02_classifier/
│   ├── classification.json
│   ├── step_report.json
│   └── step_fingerprint.json
├── step_03_structure_prep/
│   ├── observations.json
│   ├── mutations.json
│   ├── working.pdb
│   └── step_report.json
├── step_04_topology/
│   ├── topology_plan.json
│   ├── pdb2gmx_transcript.json   # full decision trace from DialogueRunner
│   ├── system_apo.gro
│   ├── system_apo.top
│   ├── posre.itp
│   └── step_report.json
├── step_05_solvation/
│   ├── system_ions.gro
│   ├── system_ions.top
│   ├── system_ions.tpr
│   ├── charge_accounting.json    # 4-stage record
│   ├── ions.mdp
│   └── step_report.json
├── step_06_em/
│   ├── em.mdp
│   ├── em.gro                    # the minimized system
│   ├── em.log
│   ├── em_convergence.json       # verdict, fmax curve
│   └── step_report.json
├── step_07_nvt/                  # nvt.{mdp,gro,cpt,xtc,log,edr}
├── step_08_npt/                  # npt.{mdp,gro,cpt,xtc,log,edr}
├── step_09_production/
│   ├── production.mdp
│   ├── production.xtc            # the trajectory (xtc-compressed)
│   ├── production.gro            # last frame
│   ├── production.cpt            # checkpoint (for continuation runs)
│   ├── production.tpr
│   ├── production.log
│   └── production.edr            # energy file (gmx energy)
├── step_10_analysis/             # analysis.json + rmsd.xvg + gyrate.xvg + rmsf.xvg
├── step_11_visualization/        # (optional) Tcl/PML scripts + PNGs
└── REPORT.md
```

Every JSON artifact is validated against a schema in
`schemas/v0.1.0/`; every file referenced in `index.json` carries a SHA-256
content hash. Mutations to outputs after a step completed will trigger
invalidation on the next resume.
"""),
    md("""
## Configuration reference

The minimum valid `run_config.json`:

```json
{
  "schema_version": "0.1.0",
  "pipeline_mode": "tutorial_reproduction",
  "interaction_mode": "noninteractive_defaults",
  "input": {"pdb_id": "1AKI"}
}
```

Common knobs you'll override:

| Field | Default | Notes |
|---|---|---|
| `pipeline_mode` | `tutorial_reproduction` | also `general_md_prep` (different validation contract) |
| `interaction_mode` | `noninteractive_defaults` | also `interactive`, `strict_config_required` |
| `force_field` | `oplsaa` | also `amber99sb-ildn`, `charmm36-jul2022`, `gromos54a7` |
| `water_model` | `spc` | must match force-field allowlist |
| `box.geometry` | `dodecahedron` | also `cubic`, `octahedron` |
| `box.padding_nm` | `1.0` | nm |
| `ion_strategy.mode` | `neutralize_only` | also `physiological_salt` (set `salt_M: 0.15`) |
| `em.step_cap` | `1000` | bump if EM didn't converge |
| `em.fmax_tol_kjmolnm` | `1000.0` | convergence threshold |
| `nvt.nsteps` | `50000` | NVT equilibration steps (50000 × 2 fs = 100 ps) |
| `nvt.temperature_K` | `300.0` | target temperature in K |
| `npt.nsteps` | `50000` | NPT equilibration steps |
| `npt.pressure_bar` | `1.0` | target pressure in bar |
| `production.nsteps` | `500000` | production steps (500000 × 2 fs = 1 ns) |
| `production.enabled` | `true` | set `false` to stop after NPT (prep-only) |
| `visualization.mode` | `disabled` | use `default` or `requested` to enable rendering |
| `input.format_preference` | `auto` | `pdb`, `mmcif`, or `auto` (mode-driven) |

The full canonical schema is at `schemas/v0.1.0/run_config.schema.json`.
Every step's fingerprint declares which config fields it depends on
(`schemas/v0.1.0/step_definitions.json`), so e.g. changing
`visualization.mode` never invalidates topology.
"""),
    md("""
## Resume semantics — restart a crashed run

If anything goes wrong mid-run (system reboot, killed process, killed terminal),
re-invoking `run-workflow` with the **same `--run-id`** picks up where it left off:
"""),
    code("""
# Same run_id → orchestrator detects existing index.json, recovers
# stale-running steps via fingerprint walk, restarts at the first
# non-succeeded step. Upstream attempts stay at 1.

result = subprocess.run(
    ["mdagent", "run-workflow",
     "--runs-root", str(runs_root),
     "--pdb-id", "1AKI",
     "--run-id", "tutorial-1aki"],   # same run_id
    capture_output=True, text=True,
)
print(result.stdout)
"""),
    md("""
Resume is also config-aware. If you change `force_field` between runs and re-invoke,
the orchestrator computes new step fingerprints and **invalidates the topology
step plus all downstream steps**. Steps whose dependencies didn't change
(classifier, structure ingest) are kept. The full ledger of what was kept vs.
re-run is in `index.json` after a resume.
"""),
    md("""
## Inspecting a run

The `inspect` subcommand prints the step ledger + the REPORT:
"""),
    code("""
result = subprocess.run(
    ["mdagent", "inspect", "--run-root", str(runs_root / "tutorial-1aki")],
    capture_output=True, text=True,
)
print(result.stdout[:2000])  # truncate
"""),
    md("""
## Visualization

To get rendered snapshots of the system at each checkpoint, set
`visualization.mode = default` (or `requested`) in the run_config:

```json
{
  ...,
  "visualization": {
    "mode": "default",
    "viewer": "auto",
    "checkpoints": ["prep", "solvated", "em"],
    "render": "both"
  }
}
```

The visualization step probes for VMD → PyMOL → NGLview in that order.

- **VMD installed** (recommended): produces PNG snapshots via `vmd -dispdev text -e visualize.vmd`.
- **PyMOL installed**: produces PNG via `pymol -cq -r visualize.pml`.
- **Neither installed**: the skill **still writes Tcl/PML scripts** to
  `step_07_visualization/<checkpoint>/visualize.{vmd,pml}`. You can render
  them yourself after installing VMD.

The skill **does not prompt** in unattended mode (`noninteractive_defaults`,
`strict_config_required`). In `interactive` mode it asks once up-front
about viewer + checkpoints + render format. The `md:visualize` skill manifest
(`skills/md-visualize/SKILL.md`) is what tells Claude when and how to ask.
"""),
    md("""
## Reading the analysis output

When `production.enabled: true` and `analysis.enabled: true` (default),
the analysis step writes `step_10_analysis/analysis.json` plus the raw
`rmsd.xvg`, `gyrate.xvg`, `rmsf.xvg` files. The JSON is the easy thing
to consume from Python:
"""),
    code("""
# Load the analysis JSON from a completed run.
import json
from pathlib import Path

run_root = Path("tutorial/runs/tutorial-1aki")
analysis_path = run_root / "step_10_analysis" / "analysis.json"
if analysis_path.is_file():
    analysis = json.loads(analysis_path.read_text())
    print("RMSD summary:", analysis["rmsd"]["summary"])
    print("Rg summary  :", analysis["radius_of_gyration"]["summary"])
    print("RMSF summary:", analysis["rmsf"]["summary"])
    # Time series are right there — e.g.:
    print("\\nFirst few RMSD frames:")
    for entry in analysis["rmsd"]["time_series"][:5]:
        print(f"  t={entry['t']:.4f} ns  rmsd={entry['rmsd']:.4f} nm")
else:
    print("No analysis output — production was probably disabled in this run.")
"""),
    md("""
For lysozyme at 300 K you'd expect:

- **RMSD** vs. starting backbone: roughly 0.1–0.2 nm after the system equilibrates (longer runs trend higher).
- **Rg** (radius of gyration): ~1.4 nm for native-state lysozyme; values much above ~1.6 nm hint at partial unfolding.
- **RMSF**: per-residue fluctuation. Loop regions show 0.1–0.3 nm; structured core stays below 0.1 nm.

For plotting, point matplotlib at the JSON's `time_series` or the `.xvg`
files directly:

```python
import matplotlib.pyplot as plt
ts = analysis["rmsd"]["time_series"]
plt.plot([p["t"] for p in ts], [p["rmsd"] for p in ts])
plt.xlabel("time (ns)"); plt.ylabel("RMSD (nm)")
plt.show()
```
"""),
    md("""
## How to consume the results

After a successful run, the artifacts you'll typically feed downstream are:

| Use case | Artifact path |
|---|---|
| Built-in analysis (RMSD/Rg/RMSF) | `step_10_analysis/analysis.json` + `*.xvg` |
| Production trajectory (further analysis in MDAnalysis / VMD) | `step_09_production/production.xtc` + `.tpr` |
| Equilibrated starting frame | `step_08_npt/npt.gro` + `system_ions.top` |
| Re-run dynamics with different settings (resume) | use the same `--run-id` with an edited config |
| Hand to PyMOL / NGLview for static view | `step_06_em/em.gro` |
| Audit the FF/water/termini choices | `step_04_topology/topology_plan.json` |
| Audit the `pdb2gmx` interactive choices | `step_04_topology/pdb2gmx_transcript.json` |
| Check ion balance | `step_05_solvation/charge_accounting.json` |
| Check EM convergence curve | `step_06_em/em_convergence.json` + `em.log` |
| Check NVT temperature stability | `step_07_nvt/nvt.edr` (parse with `gmx energy`) |
| Check NPT density / pressure stability | `step_08_npt/npt.edr` |
| Reproducibility ledger | `index.json` + per-step `step_fingerprint.json` |

The `REPORT.md` is the human-facing summary; the per-step JSONs are the
machine-actionable record.
"""),
    md("""
## Failure triage

The `failure_reason.code` field in `step_report.json` uses a structured
taxonomy. The most common codes and what they mean:

| Code | What happened | Where to look |
|---|---|---|
| `UnsupportedResidueError` | Classifier said no (ligand, nucleic acid, membrane). | `step_02_classifier/classification.json` |
| `UnexpectedPromptError` | `pdb2gmx` asked something the recognizer didn't classify. | `step_04_topology/pdb2gmx_transcript.json` + the failure context (`raw_buffer_tail`) |
| `ConsistencyGateFailure` | `grompp` rejected the system. | `step_05_solvation/system_ions.tpr` step's stderr in the step report |
| `ChargeAccountingMismatch` | `genion` didn't insert the expected counter-ions. | `step_05_solvation/charge_accounting.json` |
| `EMDiverged` | EM blew up; system likely has bad geometry. | `step_06_em/em.log` |
| `EMStuck` / verdict=`needs_longer_em` | EM hit step cap without converging. | bump `em.step_cap` and resume same `run_id` |
| `CoordinateIdMapNotInjective` | mmCIF→PDB bridge would map ambiguously. | `step_01_structure_ingest/coordinate_id_map.json` (lossy_diff field) |

When you see a failure, the run's REPORT.md will say
`readiness: blocked` and the offending step's report will have the
structured failure reason. Surfaced clearly in the inspect output.
"""),
    md("""
## Two pipeline modes

Two `pipeline_mode` values change the contract:

- **`tutorial_reproduction`** (default). Matches the canonical GROMACS lysozyme
  tutorial. `pdb2gmx` runs without `-inter`; every per-residue protonation
  state is auto-resolved by gmx (HIS tautomer from H-bond geometry;
  LYS+/ARG+/ASP-/GLU- fixed defaults).
- **`general_md_prep`**. Every titratable residue (LYS/ARG/ASP/GLU/GLN/HIS/CYS)
  becomes a per-residue prompt that the `Pdb2GmxPromptRecognizer` answers
  from a structured plan (defaults: pH-7 reasonable for OPLS-AA).
  Disulfides are auto-accepted from structural distance (`(y/n) ?` SS prompt
  answered `y`). Each answer is recorded per-residue in
  `step_04_topology/protonation_decisions.json` with both `planned` and
  `actual` (from the DialogueRunner exchange log) for full auditability.

To exercise general mode, set `"pipeline_mode": "general_md_prep"` in the
config. The pipeline reads `step_03_structure_prep/observations.json` for
the list of titratable residues, applies pH-7 defaults, and drives
`pdb2gmx -inter`.

## What's available right now (slices 1–9)

- Soluble protein-only systems.
- OPLS-AA / AMBER99SB-ILDN / CHARMM36 force fields.
- Dodecahedron / cubic / octahedron boxes.
- Neutralize-only or physiological-salt ion strategy.
- Short steepest-descent EM as validation gate.
- NVT + NPT equilibration with position restraints on the protein.
- Free production MD.
- Built-in analysis: RMSD / Rg / RMSF time series + summary stats.
- mmCIF canonical ingest with coordinate_id_map (general mode).
- Resume + fingerprint dependency invalidation across the full pipeline.
- VMD / PyMOL / NGLview visualization with viewer-detect + scripts-always.
- `general_md_prep` mode with `-inter` per-residue protonation + auto-disulfide acceptance.
- H-bond count + NVT/NPT thermodynamics (Temperature/Pressure/Density) in the analysis output.
- **Transferable installation** via `uv tool install` (slice 9): skills + schemas live inside the package; works from any directory after one install command.

## Coming next

- Remote executor (HPC / cloud GPU).
- More analyses (H-bonds, secondary-structure, residue-residue contacts).
- Energy file parsing (`gmx energy`) for NVT/NPT thermodynamic plots.
- PROPKA-driven protonation in general mode (currently fixed pH-7 defaults).

This notebook will be regenerated as each lands.
"""),
]


def build_notebook() -> nbf.notebooknode.NotebookNode:
    nb = nbf.v4.new_notebook()
    nb["cells"] = CELLS
    nb["metadata"] = {
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python", "version": "3.11"},
        "tutorial": {"slice": "slices 1-9 (transferable install)"},
    }
    return nb


def main() -> None:
    nb = build_notebook()
    NOTEBOOK_PATH.write_text(nbf.writes(nb))
    print(f"wrote {NOTEBOOK_PATH} — {len(nb['cells'])} cells")


if __name__ == "__main__":
    main()
