<!-- mdagent:requires mdagent -->
<!-- mdagent:title Reading outputs -->

# 04 — Reading the run directory

**Requirements:** mdagent only (this tutorial reads an existing run).

`mdagent run-workflow` produces an immutable per-step record. This
tutorial walks you through every file, what it contains, and how to
consume it downstream.

## Run-directory anatomy

```
<runs_root>/<run_id>/
├── run_config.json               # the resolved config
├── index.json                    # step state machine + artifact hashes
├── step_01_structure_ingest/
│   ├── original.pdb              # raw input
│   ├── working.pdb               # what downstream steps consume
│   └── step_report.json
├── step_02_classifier/classification.json
├── step_03_structure_prep/
│   ├── observations.json         # chains, HIS, CYS, titratable residues
│   ├── mutations.json
│   ├── protonation_analysis.json # iff protonation_policy=propka
│   └── working.pdb
├── step_04_topology/
│   ├── topology_plan.json        # FF/water/termini/protonation plan
│   ├── pdb2gmx_transcript.json   # full DialogueRunner exchange log
│   ├── protonation_decisions.json # planned + actual per-residue answers
│   ├── system_apo.gro
│   ├── system_apo.top
│   └── posre.itp
├── step_05_solvation/
│   ├── system_ions.gro/.top/.tpr
│   ├── charge_accounting.json    # 4-stage record
│   └── ions.mdp
├── step_06_em/
│   ├── em.gro                    # the minimized system
│   ├── em.log
│   └── em_convergence.json       # verdict, fmax curve
├── step_07_nvt/                  # nvt.{gro,cpt,xtc,log,edr,tpr}
├── step_08_npt/                  # npt.{gro,cpt,xtc,log,edr,tpr}
├── step_09_production/           # production.{gro,cpt,xtc,log,edr,tpr}
├── step_10_analysis/             # analysis.json + rmsd.xvg + gyrate.xvg + rmsf.xvg + ...
├── step_11_visualization/        # (optional) Tcl/PML scripts + PNGs
└── REPORT.md                     # readiness verdict + summary
```

## `analysis.json` — the headline file

```python
import json
from pathlib import Path

analysis = json.loads(Path("./runs/smoke/step_10_analysis/analysis.json").read_text())
print("RMSD summary:", analysis["rmsd"]["summary"])
print("Rg summary  :", analysis["radius_of_gyration"]["summary"])
print("RMSF summary:", analysis["rmsf"]["summary"])
print("H-bonds     :", analysis["hbonds"]["summary"])
print("NPT density :", analysis["thermodynamics"]["density_kgm3_npt"]["summary"])
```

Each metric has the same shape:

```json
{
  "ok": true,
  "units": {"time": "ns", "value": "nm"},
  "summary": {"n": 11, "mean": 1.42, "stdev": 0.006, "min": 1.41, "max": 1.43},
  "time_series": [{"t": 0.0, "rmsd": 0.012}, ...]
}
```

`time_series` is the per-frame data; `summary` is the canonical
short-form for the report.

## Plotting RMSD

```python
import json
import matplotlib.pyplot as plt
from pathlib import Path

data = json.loads(Path("./runs/smoke/step_10_analysis/analysis.json").read_text())
ts = data["rmsd"]["time_series"]
plt.plot([p["t"] for p in ts], [p["rmsd"] for p in ts])
plt.xlabel("time (ns)"); plt.ylabel("RMSD (nm)")
plt.title("Backbone RMSD vs. starting frame")
plt.show()
```

## Auditing the `pdb2gmx` decisions

Every per-residue answer in general mode is recorded:

```python
import json
from pathlib import Path

decisions = json.loads(Path("./runs/smoke/step_04_topology/protonation_decisions.json").read_text())
for d in decisions["planned"]:
    if d["residue_name"] == "HIS":
        print(d)
```

Each entry has `residue_name`, `resid`, `chain`, `prompt_name`,
`answer_index`, `source` (`propka@pH7.0` or `policy_default_pH7`),
`pka_value` (if propka ran), and `ph_assumed`.

## Verifying charge neutrality

```python
import json
ca = json.loads(open("./runs/smoke/step_05_solvation/charge_accounting.json").read())
print(ca)
# Expected for lysozyme (+8 net charge before ions):
#   pre_ion_total_charge ≈ 8.0
#   expected_anions      = 8
#   actual_anions        = 8
#   final_total_charge   ≈ 0.0
#   passes               = True
```

## Reproducibility ledger

```python
import json
idx = json.loads(open("./runs/smoke/index.json").read())
for s in idx["steps"]:
    fp = (s.get("fingerprint_composite") or "")[:16]
    print(f"{s['step_id']:32s} {s['status']:12s} fp={fp}")
```

Each step's `step_fingerprint.json` carries the seven components
(inputs / parameters / profile / mode / tool / schema / code). On
resume, the orchestrator recomputes the composite for each
'succeeded' step; any mismatch invalidates that step and all
descendants (see tutorial 7).

## Downstream: MDAnalysis

The production trajectory is GROMACS-format XTC. Open with
MDAnalysis:

```python
import MDAnalysis as mda

u = mda.Universe("./runs/smoke/step_09_production/production.tpr",
                 "./runs/smoke/step_09_production/production.xtc")
print(u.atoms.n_atoms, "atoms over", u.trajectory.n_frames, "frames")
```

## Next

- **05 — PROPKA** for `protonation_analysis.json` and how it's
  consumed.
- **07 — Resume** for how `step_fingerprint.json` drives invalidation.
