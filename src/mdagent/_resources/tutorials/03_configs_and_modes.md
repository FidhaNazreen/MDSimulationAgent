<!-- mdagent:requires mdagent,gromacs -->
<!-- mdagent:title Configs and modes -->

# 03 — Configs and modes

**Requirements:** mdagent + GROMACS.

The run is fully described by a single `run_config.json`. Everything
else (force field, water, box, ions, dynamics, analysis) is set there.

## Pipeline modes

`pipeline_mode` changes the contract the pipeline is fulfilling:

| Mode | Contract | Use when |
|---|---|---|
| `tutorial_reproduction` | Reproduce the canonical GROMACS lysozyme tutorial outputs exactly. `pdb2gmx` runs without `-inter`; HIS tautomer is auto-resolved from H-bond geometry. | You're following the standard tutorial / want a fast canonical reference run. |
| `general_md_prep` | Drive `pdb2gmx -inter` for per-residue protonation prompts (LYS/ARG/ASP/GLU/HIS/CYS). Each answer is recorded in `protonation_decisions.json` for audit. | You're prepping an arbitrary structure and want explicit pH-aware decisions. |

Switching is a single line:

```python
import json
cfg = json.loads(open("./run_configs/lysozyme_short.json").read())
cfg["pipeline_mode"] = "general_md_prep"
open("./run_configs/my_run.json", "w").write(json.dumps(cfg, indent=2))
```

## Interaction modes

`interaction_mode` controls whether the pipeline asks the user mid-run:

| Mode | Behavior |
|---|---|
| `interactive` | Prompt the user when a config field is missing AND has no reasonable default. |
| `noninteractive_defaults` (recommended for scripts) | Never prompt; apply defaults silently; record `auto_choice` in the manifest. |
| `strict_config_required` | Refuse to run if any required field is unset. Best for CI / reproducible studies. |

## The full knob table

| Knob | Default | Notes |
|---|---|---|
| `force_field` | `oplsaa` | also `amber99sb-ildn`, `charmm36-jul2022`, `gromos54a7` |
| `water_model` | `spc` | must match FF allowlist |
| `box.geometry` | `dodecahedron` | also `cubic`, `octahedron` |
| `box.padding_nm` | `1.0` | nm around the solute |
| `box.cutoff_nm` | `1.0` | nm |
| `ion_strategy.mode` | `neutralize_only` | also `physiological_salt` (set `salt_M: 0.15`) |
| `ion_strategy.cation` | `NA` | also `K` |
| `ion_strategy.anion` | `CL` | also `BR` |
| `ion_strategy.random_seed` | `42` | for `genion`'s placement |
| `em.step_cap` | `1000` | bump if EM didn't converge |
| `em.fmax_tol_kjmolnm` | `1000.0` | convergence threshold |
| `nvt.nsteps` | `50000` (= 100 ps at 2 fs) | shorter for tests |
| `nvt.temperature_K` | `300.0` | target T for NVT |
| `npt.nsteps` | `50000` | NPT equilibration steps |
| `npt.pressure_bar` | `1.0` | target P for NPT |
| `production.nsteps` | `500000` (= 1 ns) | the big one |
| `production.enabled` | `true` | set `false` to stop after NPT |
| `analysis.enabled` | `true` | RMSD/Rg/RMSF/H-bonds/thermo |
| `pipeline_mode` | `tutorial_reproduction` | also `general_md_prep` |
| `protonation_policy` | `propka` | also `ff_default` (fixed pH-7) |
| `ph` | `7.0` | only meaningful when `protonation_policy: propka` |
| `visualization.mode` | `disabled` | use `default` or `requested` |
| `input.format_preference` | `auto` | `pdb`, `mmcif`, or `auto` (mode-driven) |

## Write your own config

```python
import json
from pathlib import Path

cfg = {
  "schema_version": "0.1.0",
  "pipeline_mode": "tutorial_reproduction",
  "interaction_mode": "noninteractive_defaults",
  "input": {"pdb_id": "1AKI"},
  "force_field": "amber99sb-ildn",
  "water_model": "tip3p",
  "box": {"geometry": "dodecahedron", "padding_nm": 1.2, "cutoff_nm": 1.0},
  "ion_strategy": {"mode": "physiological_salt", "salt_M": 0.15,
                   "cation": "NA", "anion": "CL", "random_seed": 42},
  "em": {"step_cap": 5000, "fmax_tol_kjmolnm": 500.0},
  "nvt": {"nsteps": 50000, "dt_ps": 0.002, "temperature_K": 310.0, "random_seed": 42},
  "npt": {"nsteps": 50000, "dt_ps": 0.002, "temperature_K": 310.0, "pressure_bar": 1.0},
  "production": {"enabled": True, "nsteps": 250000, "dt_ps": 0.002,
                 "temperature_K": 310.0, "pressure_bar": 1.0, "nstxout_compressed": 5000},
  "analysis": {"enabled": True},
}
Path("./my_run_config.json").write_text(json.dumps(cfg, indent=2))
print("Wrote ./my_run_config.json")
```

Then run:

```bash
mdagent run-workflow --runs-root ./runs --config ./my_run_config.json --run-id custom
```

## Validating a config

```python
from mdagent import RunConfig
RunConfig.from_file("./my_run_config.json")  # raises ValidationError if invalid
print("config is valid")
```

## Where the schema lives

Inside the installed package:

```python
from mdagent.schemas import schemas_dir
print(schemas_dir() / "run_config.schema.json")
```

Every field has a `description` you can read for the canonical
contract.

## Next

- **04 — Reading outputs** for the post-run analysis output.
- **05 — PROPKA** for `protonation_policy: propka` in detail.
