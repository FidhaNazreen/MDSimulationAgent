"""End-to-end 1AKI golden-path test.

Drives `mdagent.run_workflow` through ingest → topology → solvation →
short EM → report on PDB 1AKI in `tutorial_reproduction` mode.

Expensive: fetches 1AKI from RCSB (~110 KB), runs gmx solvate (~38k atoms)
and EM (~1000 steps single-threaded). Wall-time on an M-series laptop:
~30-60 seconds end-to-end. Marked `slow`; opt-in via `--run-slow`.

Skipped automatically when `gmx` is not on PATH.
"""

from __future__ import annotations

import json
import shutil
import socket
import urllib.error
import urllib.request
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.skipif(shutil.which("gmx") is None, reason="GROMACS not installed"),
    pytest.mark.slow,
]


def _have_internet() -> bool:
    try:
        urllib.request.urlopen("https://files.rcsb.org/", timeout=5)
        return True
    except (OSError, urllib.error.URLError, socket.timeout):
        return False


def _write_config(tmp_path: Path) -> Path:
    cfg = {
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
        "ion_strategy": {
            "mode": "neutralize_only",
            "cation": "NA",
            "anion": "CL",
            "random_seed": 42,
        },
        "em": {"step_cap": 1000, "fmax_tol_kjmolnm": 1000.0},
        # Disable dynamics for the v0 golden-path test — it asserts up to EM only.
        "production": {"enabled": False},
        # Even with production disabled, NVT+NPT still run. Use tiny step counts.
        "nvt": {"nsteps": 1000, "dt_ps": 0.002, "temperature_K": 300.0, "random_seed": 42},
        "npt": {"nsteps": 1000, "dt_ps": 0.002, "temperature_K": 300.0, "pressure_bar": 1.0},
        "tool_versions": {"gromacs": "2026.2"},
    }
    p = tmp_path / "run_config.json"
    p.write_text(json.dumps(cfg, indent=2, sort_keys=True))
    return p


def test_1aki_golden_path_runs_to_ready(tmp_path: Path) -> None:
    """End-to-end run on 1AKI must finish with REPORT.md saying readiness=ready."""
    if not _have_internet():
        pytest.skip("no internet — cannot fetch 1AKI")

    cfg_path = _write_config(tmp_path)
    runs_root = tmp_path / "runs"

    from mdagent import run_workflow

    run_root, index = run_workflow(run_config_path=cfg_path, runs_root=runs_root, run_id="golden")

    # Per-step statuses on the happy path:
    statuses = {s.step_id: s.status for s in index.steps}
    assert statuses["step_00_preflight_early"] == "skipped"
    assert statuses["step_01_structure_ingest"] == "succeeded", statuses
    assert statuses["step_02_classifier"] == "succeeded", statuses
    assert statuses["step_03_structure_prep"] == "succeeded", statuses
    assert statuses["step_04_topology"] == "succeeded", statuses
    assert statuses["step_05_solvation"] == "succeeded", statuses
    assert statuses["step_06_em"] == "succeeded", statuses
    assert statuses["step_07_nvt"] == "succeeded", statuses
    assert statuses["step_08_npt"] == "succeeded", statuses
    assert statuses["step_09_production"] == "skipped", statuses  # production.enabled=false
    assert statuses["step_10_visualization"] == "skipped"
    assert statuses["step_11_report"] == "succeeded", statuses

    # Charge accounting passed.
    ca = json.loads((run_root / "step_05_solvation" / "charge_accounting.json").read_text())
    assert ca["passes"] is True
    # 1AKI has +8 net charge → 8 Cl-, 0 Na+
    assert ca["actual_anions"] == 8, ca
    assert ca["actual_cations"] == 0, ca
    assert abs(ca["final_total_charge"]) < 1e-3, ca

    # EM converged.
    em = json.loads((run_root / "step_06_em" / "em_convergence.json").read_text())
    assert em["verdict"] == "converged", em
    assert em["fmax_final"] < 1000.0, em

    # REPORT.md exists and proclaims ready.
    report = (run_root / "REPORT.md").read_text()
    assert "readiness: **ready**" in report, report[:500]
    assert "**converged**" in report

    # Each succeeded step has a fingerprint with depends_on_config_fields.
    for sid in ("step_04_topology", "step_05_solvation", "step_06_em"):
        fp = json.loads((run_root / sid / "step_fingerprint.json").read_text())
        assert fp["composite"], f"{sid} missing composite"
        assert isinstance(fp["depends_on_config_fields"], list) and fp["depends_on_config_fields"], sid
