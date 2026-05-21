"""Resume-after-crash tests.

Two scenarios:

1. **Crash mid-run** — run the pipeline through a successful topology step,
   simulate a crash before solvation completes by manually editing the
   index to leave step_04 succeeded and step_05 in 'running' status with
   a dead PID. Re-invoke `run_workflow` on the same run_id and assert
   the pipeline finishes correctly.

2. **Config drift** — let the run succeed end-to-end, then mutate the
   run_config to change a parameter that step_04_topology depends on
   (`force_field`). Re-invoke `run_workflow` on the same run_id with
   the mutated config and assert: topology + downstream become
   `invalidated`, then are re-run with the new force field, and the
   final EM still converges.

Both scenarios are `slow` because they exercise the full pipeline.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.skipif(shutil.which("gmx") is None, reason="GROMACS not installed"),
    pytest.mark.slow,
]

_DEFAULT_CFG = {
    "schema_version": "0.1.0",
    "pipeline_mode": "tutorial_reproduction",
    "interaction_mode": "noninteractive_defaults",
    "input": {"pdb_id": "1AKI", "biological_assembly": "asymmetric_unit"},
    "force_field": "oplsaa",
    "water_model": "spc",
    "ph": 7.0,
    "protonation_policy": "propka",
    "altloc_policy": "highest_occupancy",
    "water_retention_policy": "strip_all",
    "box": {"geometry": "dodecahedron", "padding_nm": 1.0, "cutoff_nm": 1.0},
    "ion_strategy": {"mode": "neutralize_only", "cation": "NA", "anion": "CL", "random_seed": 42},
    "em": {"step_cap": 1000, "fmax_tol_kjmolnm": 1000.0},
    "tool_versions": {"gromacs": "2026.2"},
}


def _have_internet() -> bool:
    import socket
    import urllib.error
    import urllib.request
    try:
        urllib.request.urlopen("https://files.rcsb.org/", timeout=5)
        return True
    except (OSError, urllib.error.URLError, socket.timeout):
        return False


def _write_cfg(path: Path, **overrides) -> Path:
    cfg = json.loads(json.dumps(_DEFAULT_CFG))
    cfg.update(overrides)
    path.write_text(json.dumps(cfg, indent=2, sort_keys=True))
    return path


def test_resume_after_simulated_crash(tmp_path: Path) -> None:
    """First-run partial, then resume — final state must match a clean run."""
    if not _have_internet():
        pytest.skip("no internet")

    from mdagent import run_workflow
    from mdagent.run_index import RunIndex

    cfg_path = _write_cfg(tmp_path / "run_config.json")
    runs_root = tmp_path / "runs"

    # First run — let it complete fully.
    run_root, index = run_workflow(run_config_path=cfg_path, runs_root=runs_root, run_id="resume_test")
    assert all(s.status in ("succeeded", "skipped") for s in index.steps), {s.step_id: s.status for s in index.steps}

    # Simulate a crash: mark step_05_solvation as 'running' with a dead PID,
    # delete the EM artifacts so step_06 also needs to re-run.
    idx = RunIndex.read(run_root / "index.json")
    sol_step = idx.step("step_05_solvation")
    sol_step.status = "running"
    em_step = idx.step("step_06_em")
    em_step.status = "planned"
    # Use a PID that's definitely not alive — 2**20 + 7
    idx.lock_holder_pid = 2 ** 20 + 7
    idx.write(run_root / "index.json")
    # Wipe step_06 outputs so it must really re-run.
    em_dir = run_root / "step_06_em"
    if em_dir.is_dir():
        for p in em_dir.iterdir():
            p.unlink()

    # Resume — should detect stale 'running', mark it 'failed', then re-run
    # solvation + em.
    run_root2, index2 = run_workflow(run_config_path=cfg_path, runs_root=runs_root, run_id="resume_test")
    assert run_root2 == run_root
    statuses = {s.step_id: s.status for s in index2.steps}
    # The resumed solvation was 'running' → after stale-recovery it should
    # be 'failed', then re-run to succeeded. Likewise for em.
    assert statuses["step_05_solvation"] == "succeeded", statuses
    assert statuses["step_06_em"] == "succeeded", statuses

    # Earlier steps shouldn't have been re-run — their attempt count stays at 1.
    rep = json.loads((run_root / "step_04_topology" / "step_report.json").read_text())
    assert rep["attempt"] == 1, "topology re-ran on resume — should have been kept"

    # Final report still says ready.
    report = (run_root / "REPORT.md").read_text()
    assert "readiness: **ready**" in report


def test_resume_after_config_change_invalidates_topology_and_below(tmp_path: Path) -> None:
    """Change a topology-dependent param; expect invalidation walker to re-run from topology."""
    if not _have_internet():
        pytest.skip("no internet")

    from mdagent import run_workflow

    cfg_path = _write_cfg(tmp_path / "run_config.json")
    runs_root = tmp_path / "runs"

    # First run on oplsaa.
    run_root, index = run_workflow(run_config_path=cfg_path, runs_root=runs_root, run_id="config_drift")
    assert all(s.status in ("succeeded", "skipped") for s in index.steps)
    topology_attempt_1 = json.loads((run_root / "step_04_topology" / "step_report.json").read_text())
    assert topology_attempt_1["attempt"] == 1

    # Mutate the config: switch force_field to amber99sb-ildn (downstream-invalidating)
    cfg = json.loads(cfg_path.read_text())
    cfg["force_field"] = "amber99sb-ildn"
    # amber needs a compatible water — use tip3p.
    cfg["water_model"] = "tip3p"
    cfg_path.write_text(json.dumps(cfg, indent=2, sort_keys=True))

    # Second run, same run_id — orchestrator must detect the drift and re-run
    # topology + solvation + em.
    run_root2, index2 = run_workflow(run_config_path=cfg_path, runs_root=runs_root, run_id="config_drift")
    statuses = {s.step_id: s.status for s in index2.steps}
    assert statuses["step_04_topology"] == "succeeded"
    assert statuses["step_05_solvation"] == "succeeded"
    assert statuses["step_06_em"] == "succeeded"

    # Topology attempt counter must have bumped.
    topology_attempt_2 = json.loads((run_root / "step_04_topology" / "step_report.json").read_text())
    assert topology_attempt_2["attempt"] == 2, topology_attempt_2

    # The new topology actually used the new FF.
    plan = json.loads((run_root / "step_04_topology" / "topology_plan.json").read_text())
    assert plan["force_field"] == "amber99sb-ildn"
    assert plan["water_model"] == "tip3p"

    # Earlier steps were NOT re-run (their params don't depend on FF/water).
    classifier_rep = json.loads((run_root / "step_02_classifier" / "step_report.json").read_text())
    assert classifier_rep["attempt"] == 1, "classifier re-ran but shouldn't have"

    # Final report still says ready.
    report = (run_root / "REPORT.md").read_text()
    assert "readiness: **ready**" in report
