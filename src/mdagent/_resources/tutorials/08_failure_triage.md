<!-- mdagent:requires mdagent -->
<!-- mdagent:title Failure triage -->

# 08 — Failure triage

**Requirements:** mdagent only (this tutorial reads existing run dirs).

Every step records failures with a structured taxonomy in
`step_report.json:failure_reason`. This tutorial maps each failure
code to its likely cause + the smallest remedy.

## The taxonomy

The full enum is in
`src/mdagent/_resources/schemas/v0.1.0/step_report.schema.json` under
`failure_reason.code`. Codes you'll actually hit:

| Code | Where it fires | Likely cause | Smallest remedy |
|---|---|---|---|
| `ConfigMissing` | any step | required field absent from `run_config.json` | Edit config; re-run same `--run-id`. |
| `UnsupportedResidueError` | `step_02_classifier` | ligand / nucleic acid / membrane / unknown HETATM | v0 only supports `chemistry={protein}` or `{protein, water}`. Strip the unsupported atoms or wait for v1. |
| `PromptMismatchError` / `UnexpectedPromptError` | `step_04_topology` | `pdb2gmx` emitted a prompt the recognizer didn't classify | Check `pdb2gmx_transcript.json` + raw_buffer_tail. Likely gmx version drift; the recognizer is pinned to 2026.x. |
| `MissingAtomError` | `step_04_topology` | residue missing backbone atoms | Use a complete structure or set `allow_terminal_truncation: true`. |
| `ChainInconsistencyError` | `step_04_topology` | multi-chain merge ambiguity | Set `chain_policy.merge_groups` explicitly. |
| `FFWaterUnavailableError` | `step_04_topology` | requested force-field or water-model not in gmx's `top/` | Use a supported `force_field` / `water_model` pair. |
| `TemplateMismatchError` | `step_04_topology` | residue rename produced a template `pdb2gmx` doesn't know | Likely v1-only chemistry; refuse the rename. |
| `DisulfideMismatchError` | `step_04_topology` | structural CYS-CYS distance check inconsistent with `disulfide_policy` | Set `disulfide_policy: auto_detect` (default) or `none`. |
| `ConsistencyGateFailure` | `step_05_solvation` or any later grompp | grompp rejected the topology+coordinates | Read the failure's `context.stderr`. Usually `Number of coordinates does not match` (topology+gro out of sync). |
| `ChargeAccountingMismatch` | `step_05_solvation` | `genion` didn't insert the expected counter-ions | Read `charge_accounting.json` — `expected_anions` vs `actual_anions`. |
| `EMDiverged` | `step_06_em` | EM blew up; bad geometry / clashes | Check `em.log` for the offending atoms. Often a structure-prep problem; re-run from prep. |
| `EMStuck` | `step_06_em` | step cap hit, fmax stalled above tol | Bump `em.step_cap` or relax `em.fmax_tol_kjmolnm`. |
| `CoordinateIdMapNotInjective` | `step_01_structure_ingest` | mmCIF→PDB bridge would map two residues to the same `(chain, resid, icode)` | Inspect `coordinate_id_map.json:lossy_diff`. Likely a multi-model structure or unusual insertion codes. |
| `RetainedWaterDisplaced` | `step_05_solvation` | a crystallographic water got replaced by an ion | Set `water_retention_policy: strip_all` and ingest fresh. |
| `UnresolvedDecisions` | `step_04_topology` (strict mode) | required per-residue answer absent | Set `interaction_mode: noninteractive_defaults` OR supply the answers via config. |
| `CrashRecoveryStaleRunning` | any step | a previous attempt left this step in `running` state with a dead PID | Resume restarted the step; if it failed again it's a real failure, look at the new context. |
| `NonZeroExitError` | any step | catch-all (uncategorized gmx failure) | Read `context.stderr`. |

## How to read a failure

```python
import json
from pathlib import Path

report = json.loads(Path("./runs/<run_id>/<step_id>/step_report.json").read_text())
fr = report.get("failure_reason")
if fr is not None:
    print(f"Code: {fr['code']}")
    print(f"Message: {fr['message']}")
    ctx = fr.get('context', {})
    if "stderr" in ctx:
        print("\n--- stderr (tail) ---")
        print(ctx["stderr"])
    if "raw_buffer_tail" in ctx:
        print("\n--- raw_buffer_tail ---")
        print(ctx["raw_buffer_tail"])
```

## Common cases by step

### Solvation: `ChargeAccountingMismatch`

```python
import json
from pathlib import Path

ca = json.loads(Path("./runs/<run_id>/step_05_solvation/charge_accounting.json").read_text())
print("pre-ion charge:", ca["pre_ion_total_charge"])
print("expected ions: ", ca["expected_anions"], "anions,", ca["expected_cations"], "cations")
print("actual ions:   ", ca["actual_anions"], "anions,", ca["actual_cations"], "cations")
print("final charge:  ", ca["final_total_charge"])
print("passes:        ", ca["passes"])
```

If `actual` ≠ `expected`, the `genion` invocation didn't replace the
right number of solvent molecules. Most common cause: a custom water
residue name (e.g. retained crystallographic waters) confused the
`SOL` index. The solvation step uses a positional `bulk_solvent`
index to avoid this; if you bypassed that path with a custom config,
re-enable it.

### EM: `EMStuck` or verdict `needs_longer_em`

```python
import json
from pathlib import Path

em = json.loads(Path("./runs/<run_id>/step_06_em/em_convergence.json").read_text())
print("verdict:", em["verdict"])
print("fmax_final:", em["fmax_final"])
print("nsteps   :", em["nsteps"])
```

If `fmax_final` is dropping but didn't reach `emtol` in the step cap,
bump `em.step_cap` (e.g. 1000 → 5000) and re-run with the same
`--run-id`.

If `fmax_final` is very large (> 1e6 kJ/mol/nm) → real divergence;
investigate the input geometry, force-field/water mismatch, or ion
clashes.

### Topology: `UnexpectedPromptError`

The DialogueRunner saw output from `pdb2gmx` that didn't match any
recognizer pattern. Most common cause: a `gmx` version with slightly
different prompt text. The pinned recognizer is `gmx 2026.x`.

```python
import json
from pathlib import Path

t = json.loads(Path("./runs/<run_id>/step_04_topology/pdb2gmx_transcript.json").read_text())
print("argv:", t["argv"])
print("exit:", t["exit_status"])
print("\n--- raw transcript tail ---")
print(t["raw_transcript"][-2000:])
```

The exchange log shows every prompt the recognizer DID match — the
unknown one is the next thing after the last entry.

## Asking Claude for triage

> *"My run `mystudy` failed. Tell me what's wrong."*

Claude reads `runs/mystudy/index.json`, finds the first `failed`
step, opens its `step_report.json`, and surfaces the structured
`failure_reason` plus the relevant sidecar JSON
(`charge_accounting.json` / `em_convergence.json` / etc.) and a
one-line remedy.

## End

This is the last tutorial. The full schema, all the agent code, and
every per-step report is on disk under `runs/<run_id>/`. The system
is designed to be auditable end-to-end — when something is wrong,
the answer is in a JSON file.
