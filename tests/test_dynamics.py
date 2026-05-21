"""Dynamics integration test: NVT + NPT + a tiny production run.

Slower than the golden-path EM-only test. Asserts the three dynamics
phases produce the expected artifacts and the production trajectory
exists on disk.
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


def test_full_dynamics_pipeline_on_1aki(tmp_path: Path) -> None:
    """ingest → … → EM → NVT → NPT → short Production produces a valid trajectory."""
    if not _have_internet():
        pytest.skip("no internet")

    from mdagent import run_workflow

    cfg = {
        "schema_version": "0.1.0",
        "pipeline_mode": "tutorial_reproduction",
        "interaction_mode": "noninteractive_defaults",
        "input": {"pdb_id": "1AKI"},
        "force_field": "oplsaa",
        "water_model": "spc",
        "box": {"geometry": "dodecahedron", "padding_nm": 1.0, "cutoff_nm": 1.0},
        "ion_strategy": {"mode": "neutralize_only", "cation": "NA", "anion": "CL", "random_seed": 42},
        "em": {"step_cap": 1000, "fmax_tol_kjmolnm": 1000.0},
        # Very short dynamics for testing — 2 ps NVT + 2 ps NPT + 4 ps production.
        "nvt": {"nsteps": 1000, "dt_ps": 0.002, "temperature_K": 300.0, "random_seed": 42},
        "npt": {"nsteps": 1000, "dt_ps": 0.002, "temperature_K": 300.0, "pressure_bar": 1.0},
        "production": {"enabled": True, "nsteps": 2000, "dt_ps": 0.002,
                       "temperature_K": 300.0, "pressure_bar": 1.0, "nstxout_compressed": 200},
        "tool_versions": {"gromacs": "2026.2"},
    }
    cfg_path = tmp_path / "run_config.json"
    cfg_path.write_text(json.dumps(cfg, indent=2, sort_keys=True))

    run_root, index = run_workflow(run_config_path=cfg_path, runs_root=tmp_path / "runs", run_id="dyn")

    statuses = {s.step_id: s.status for s in index.steps}
    assert statuses["step_07_nvt"] == "succeeded", statuses
    assert statuses["step_08_npt"] == "succeeded", statuses
    assert statuses["step_09_production"] == "succeeded", statuses

    # NVT artifacts
    nvt_gro = run_root / "step_07_nvt" / "nvt.gro"
    nvt_cpt = run_root / "step_07_nvt" / "nvt.cpt"
    nvt_xtc = run_root / "step_07_nvt" / "nvt.xtc"
    assert nvt_gro.is_file() and nvt_cpt.is_file() and nvt_xtc.is_file()

    # NPT artifacts
    npt_gro = run_root / "step_08_npt" / "npt.gro"
    npt_cpt = run_root / "step_08_npt" / "npt.cpt"
    assert npt_gro.is_file() and npt_cpt.is_file()

    # Production trajectory
    prod_xtc = run_root / "step_09_production" / "production.xtc"
    prod_gro = run_root / "step_09_production" / "production.gro"
    assert prod_xtc.is_file(), "production trajectory missing"
    assert prod_gro.is_file()
    # The .xtc should be > 0 bytes (real frames written).
    assert prod_xtc.stat().st_size > 0

    # The final report should still say ready.
    report = (run_root / "REPORT.md").read_text()
    assert "readiness: **ready**" in report
