<!-- mdagent:requires mdagent,gromacs,propka -->
<!-- mdagent:title PROPKA-driven protonation -->

# 05 — PROPKA-driven protonation

**Requirements:** mdagent + GROMACS + PROPKA (`mdagent[tutorials]` /
`mdagent[propka]` extra).

When you set `protonation_policy: propka` in the run config, the prep
step runs PROPKA on the working PDB and the topology step uses each
predicted pKa to set the per-residue `pdb2gmx -inter` answer based on
the configured `ph`. This tutorial walks through the chemistry and the
audit trail.

## When to use PROPKA

| Scenario | Recommendation |
|---|---|
| You're reproducing the canonical GROMACS lysozyme tutorial. | Use `tutorial_reproduction` mode. PROPKA isn't called. |
| You're prepping any other protein and care about the protonation states being correct at your target pH. | Use `general_md_prep` + `protonation_policy: propka` + an explicit `ph`. |
| Your structure has unusual residues (covalent ligands, modified amino acids). | PROPKA may not have parameters; topology will still fall back to fixed defaults for those. |

## The chemistry

PROPKA predicts a pKa for each titratable residue (LYS / ARG / ASP /
GLU / GLN / HIS / CYS / TYR). The topology step's decision rule:

| Residue | Answer if `pKa > ph` (protonated) | Answer if `pKa < ph` (deprotonated) |
|---|---|---|
| LYS | `1` (LYSH, +1) | `0` (LYS, neutral) |
| ASP | `1` (ASPH, neutral) | `0` (ASP, -1) |
| GLU | `1` (GLUH, neutral) | `0` (GLU, -1) |
| HIS | `2` (HIP, both N's, +1) | `1` (HIE, ε-protonated, neutral) |
| ARG / GLN | (fixed default) | (fixed default) |
| CYS | (handled by SS prompts) | (handled by SS prompts) |

CYS in a disulfide bond gets PROPKA's `99.99` sentinel (= non-titratable);
those flow through the `SS_YN` prompt instead.

## Run it

```python
import json
from pathlib import Path

cfg = {
    "schema_version": "0.1.0",
    "pipeline_mode": "general_md_prep",
    "interaction_mode": "noninteractive_defaults",
    "input": {"structure_path": "./structures/1aki.pdb", "format_preference": "pdb"},
    "force_field": "oplsaa", "water_model": "spc",
    "ph": 7.0,
    "protonation_policy": "propka",
    "box": {"geometry": "dodecahedron", "padding_nm": 1.0, "cutoff_nm": 1.0},
    "ion_strategy": {"mode": "neutralize_only", "cation": "NA", "anion": "CL", "random_seed": 42},
    "em": {"step_cap": 1000, "fmax_tol_kjmolnm": 1000.0},
    "nvt": {"nsteps": 500, "dt_ps": 0.002, "temperature_K": 300.0, "random_seed": 42},
    "npt": {"nsteps": 500, "dt_ps": 0.002, "temperature_K": 300.0, "pressure_bar": 1.0},
    "production": {"enabled": False},
}
Path("./run_configs/propka_pH7.json").write_text(json.dumps(cfg, indent=2))
```

```bash
mdagent run-workflow --runs-root ./runs --config ./run_configs/propka_pH7.json --run-id propka_pH7 --stop-after topology
```

## Read the analysis

```python
import json
from pathlib import Path

# 1) The raw PROPKA output:
analysis = json.loads(Path("./runs/propka_pH7/step_03_structure_prep/protonation_analysis.json").read_text())
print("method:", analysis["method"], "  pH:", analysis["ph_assumed"])
for r in analysis["residues"][:5]:
    print(f"  {r['residue_type']} {r['resid']} chain={r['chain']} pKa={r['pka_value']}")

# 2) The per-residue answer chosen by Topology:
decisions = json.loads(Path("./runs/propka_pH7/step_04_topology/protonation_decisions.json").read_text())
his15 = next(d for d in decisions["planned"] if d["residue_name"] == "HIS" and d["resid"] == 15)
print("\nHIS-15 decision:", his15)
```

For lysozyme HIS-15 at pH 7 with PROPKA pKa ≈ 6.3 (< pH), Topology
picks `answer_index: "1"` (HIE, neutral). The `source` field reads
`propka@pH7.0`.

## Same protein at pH 5

```python
cfg["ph"] = 5.0
Path("./run_configs/propka_pH5.json").write_text(json.dumps(cfg, indent=2))
```

```bash
mdagent run-workflow --runs-root ./runs --config ./run_configs/propka_pH5.json --run-id propka_pH5 --stop-after topology
```

```python
import json
from pathlib import Path

d5 = json.loads(Path("./runs/propka_pH5/step_04_topology/protonation_decisions.json").read_text())
his15 = next(d for d in d5["planned"] if d["residue_name"] == "HIS" and d["resid"] == 15)
print("HIS-15 at pH 5:", his15["answer_index"], his15["source"])  # → "2" (HIP, protonated)
```

The HIS-15 decision flips from `"1"` (HIE) at pH 7 to `"2"` (HIP) at
pH 5 — exactly what physics says.

## Asking Claude

> *"Set up 1AKI at pH 5.5 with PROPKA-driven protonation, then equilibrate at 300 K."*

Claude writes a config with `pipeline_mode: general_md_prep`,
`protonation_policy: propka`, `ph: 5.5`, runs the pipeline, and
surfaces the HIS-15 decision (which is the most interesting residue
in lysozyme for pH studies).

## When PROPKA isn't installed

If you set `protonation_policy: propka` but didn't install the extra,
the doctor preflight emits a **warning** (not a failure) and the
pipeline falls back to fixed pH-7 defaults. Re-install with the
extra to enable:

```bash
uv tool install --force "mdagent[tutorials] @ git+https://github.com/mjayadharan/MDSimulationAgent@v0.1.0"
```

(`mdagent[tutorials]` ships PROPKA + the notebook/PDF build deps;
there's also a narrower `mdagent[propka]` extra if you only want the
chemistry, not the docs build.)

## Next

- **06 — Visualization** for VMD/PyMOL/NGLview rendering.
- **08 — Failure triage** if PROPKA fails or the pipeline blows up
  somewhere.
