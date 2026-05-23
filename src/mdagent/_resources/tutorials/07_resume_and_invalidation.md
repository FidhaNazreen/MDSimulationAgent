<!-- mdagent:requires mdagent,gromacs -->
<!-- mdagent:title Resume and fingerprint-driven invalidation -->

# 07 — Resume and fingerprint-driven invalidation

**Requirements:** mdagent + GROMACS.

Long MD runs crash. Configs change. Tool versions update. The
orchestrator's resume machinery handles all three by recomputing a
seven-component `StepFingerprint` for every previously-succeeded
step and invalidating anything that drifted.

## How resume works

Re-invoke `mdagent run-workflow` with the **same `--run-id`**. The
orchestrator:

1. Detects the existing `runs/<run_id>/index.json`.
2. Calls `recover_stale_running()` — any step left in `running` state
   by a dead process is marked `failed` with
   `code: CrashRecoveryStaleRunning`.
3. Walks the DAG. For each `succeeded` step, recomputes
   `StepFingerprint` (inputs / parameters / profile / mode / tool /
   schema / code hashes) and compares to the recorded composite.
4. Mismatches invalidate that step and all DAG descendants
   (status → `invalidated`).
5. Restarts at the first non-succeeded step. Attempt counter bumps
   by 1.

## Scenario 1 — crash mid-run

Say `gmx mdrun` got killed mid-NPT.

```bash
mdagent run-workflow --runs-root ./runs --config ./run_configs/lysozyme_short.json --run-id resumable
# ... NPT is interrupted by Ctrl-C or OOM kill ...

# Resume with the same run_id:
mdagent run-workflow --runs-root ./runs --config ./run_configs/lysozyme_short.json --run-id resumable
```

The orchestrator finds NPT in `running` state with a dead PID, marks
it `failed`, and re-runs from NPT onward. Steps 01–07 (ingest →
NVT) are untouched. The retried NPT step has `attempt: 2` in its
`step_report.json`.

## Scenario 2 — change a force-field, same run_id

Edit the config to switch `force_field: oplsaa` → `amber99sb-ildn`
and `water_model: spc` → `tip3p`. Re-run with the same `--run-id`:

```python
import json
from pathlib import Path

# Build "the same run_id" with a different FF
cfg = json.loads(Path("./run_configs/lysozyme_short.json").read_text())
cfg["force_field"] = "amber99sb-ildn"
cfg["water_model"] = "tip3p"
Path("./run_configs/amber_run.json").write_text(json.dumps(cfg, indent=2))
```

```bash
mdagent run-workflow --runs-root ./runs --config ./run_configs/amber_run.json --run-id resumable
```

The orchestrator computes new fingerprints. For
`step_04_topology`, `force_field` is in its
`depends_on_config_fields`, so `parameters_hash` changes →
composite hash mismatches → topology + solvation + EM + NVT + NPT +
production + analysis all become `invalidated`. They re-run with the
new FF. Steps 01 (ingest), 02 (classifier), 03 (prep) keep their
attempt counter at `1` — their inputs/parameters didn't change.

## Inspect the ledger

```python
import json
from pathlib import Path

idx = json.loads(Path("./runs/resumable/index.json").read_text())
for s in idx["steps"]:
    fp = (s.get("fingerprint_composite") or "")[:16]
    print(f"  {s['step_id']:32s} {s['status']:12s} attempt={s.get('current_attempt', '-'):>2}  fp={fp}")
```

## Per-step fingerprint details

```python
import json
from pathlib import Path

fp = json.loads(Path("./runs/resumable/step_04_topology/step_fingerprint.json").read_text())
for k in ("inputs_hash", "parameters_hash", "profile_hash", "mode_hash",
          "tool_hash", "schema_hash", "code_hash", "composite"):
    print(f"  {k:20s} = {fp[k][:16]}…")
print("\ndepends_on_config_fields:", fp["depends_on_config_fields"][:5], "...")
```

When any of these seven hashes changes, the composite changes, and
that step (plus everything downstream) re-runs.

## Force a re-run

Sometimes you want to re-run anyway. Easiest path: change `run-id`.

```bash
mdagent run-workflow --runs-root ./runs --config ./run_configs/lysozyme_short.json --run-id fresh
```

A new run_id means a fresh `index.json` with no prior state.

Or delete the step's dir from the existing run:

```bash
rm -rf ./runs/resumable/step_06_em
mdagent run-workflow --runs-root ./runs --config ./run_configs/lysozyme_short.json --run-id resumable
# step_06_em re-runs (and step_07 through end follow).
```

## Asking Claude

> *"Re-run from EM with `em.step_cap: 5000` for run `resumable`."*

Claude edits the config to bump `em.step_cap`, reruns with the same
`run_id`; the orchestrator invalidates step_06_em + downstream
because `em.step_cap` is in step_06's
`depends_on_config_fields`.

## Next

- **08 — Failure triage** for what to do when a step really did fail
  (not crash, not config-drift, but bad chemistry / geometry).
