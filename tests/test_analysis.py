"""Analysis step integration test.

Runs the full pipeline (incl. a tiny production run) and asserts the
analysis.json + .xvg outputs are produced with sensible time-series
content.
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


def test_analysis_runs_against_short_production(tmp_path: Path) -> None:
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
        "nvt": {"nsteps": 1000, "dt_ps": 0.002, "temperature_K": 300.0, "random_seed": 42},
        "npt": {"nsteps": 1000, "dt_ps": 0.002, "temperature_K": 300.0, "pressure_bar": 1.0},
        "production": {"enabled": True, "nsteps": 2000, "dt_ps": 0.002,
                       "temperature_K": 300.0, "pressure_bar": 1.0, "nstxout_compressed": 200},
        "analysis": {"enabled": True},
        "tool_versions": {"gromacs": "2026.2"},
    }
    cfg_path = tmp_path / "run_config.json"
    cfg_path.write_text(json.dumps(cfg, indent=2, sort_keys=True))

    run_root, index = run_workflow(run_config_path=cfg_path, runs_root=tmp_path / "runs", run_id="ana")

    statuses = {s.step_id: s.status for s in index.steps}
    assert statuses["step_09_production"] == "succeeded", statuses
    assert statuses["step_10_analysis"] == "succeeded", statuses

    # analysis.json holds the time series + summary stats.
    analysis_path = run_root / "step_10_analysis" / "analysis.json"
    assert analysis_path.is_file()
    analysis = json.loads(analysis_path.read_text())

    # RMSD: 10 frames @ nstxout_compressed=200 across nsteps=2000 → about 10 entries.
    assert analysis["rmsd"]["ok"] is True
    assert analysis["rmsd"]["units"] == {"time": "ns", "value": "nm"}
    assert analysis["rmsd"]["summary"]["n"] > 0
    assert analysis["rmsd"]["summary"]["mean"] >= 0.0  # nm

    # Rg
    assert analysis["radius_of_gyration"]["ok"] is True
    rg_mean = analysis["radius_of_gyration"]["summary"]["mean"]
    assert 1.0 < rg_mean < 2.5, f"Rg of lysozyme should be ~1.4 nm; got {rg_mean}"

    # RMSF: one entry per protein residue (≈129 for 1AKI).
    assert analysis["rmsf"]["ok"] is True
    n_residues = analysis["rmsf"]["summary"]["n"]
    assert 120 < n_residues < 140, f"expected ~129 residues; got {n_residues}"

    # The .xvg files are also present so the user can re-plot.
    assert (run_root / "step_10_analysis" / "rmsd.xvg").is_file()
    assert (run_root / "step_10_analysis" / "gyrate.xvg").is_file()
    assert (run_root / "step_10_analysis" / "rmsf.xvg").is_file()

    # Thermodynamics: NVT temperature curve + NPT pressure/density should
    # all parse from the .edr files (gmx energy via stdin).
    thermo = analysis["thermodynamics"]
    assert thermo["temperature_K_nvt"]["ok"] is True, thermo
    t_mean = thermo["temperature_K_nvt"]["summary"]["mean"]
    # Temperature should be roughly near the target (300 K) — but with very
    # short runs there's substantial noise; allow generous bounds.
    assert 100 < t_mean < 500, f"NVT T mean {t_mean} K outside sane bounds"
    assert thermo["pressure_bar_npt"]["ok"] is True
    assert thermo["density_kgm3_npt"]["ok"] is True
    # Lysozyme + water density should be ~1000 kg/m^3 (broad bounds for noise).
    rho_mean = thermo["density_kgm3_npt"]["summary"]["mean"]
    assert 800 < rho_mean < 1200, f"NPT density mean {rho_mean} outside sane bounds"

    # H-bonds: best-effort. Don't hard-fail if hbond couldn't compute.
    if analysis["hbonds"]["ok"]:
        assert analysis["hbonds"]["summary"]["n"] > 0


def test_analysis_skipped_when_production_disabled(tmp_path: Path) -> None:
    """If production is disabled, analysis should be marked 'skipped' (not 'failed')."""
    if not _have_internet():
        pytest.skip("no internet")

    from mdagent import run_workflow

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
        "production": {"enabled": False},
        "tool_versions": {"gromacs": "2026.2"},
    }
    cfg_path = tmp_path / "run_config.json"
    cfg_path.write_text(json.dumps(cfg, indent=2, sort_keys=True))

    run_root, index = run_workflow(run_config_path=cfg_path, runs_root=tmp_path / "runs", run_id="ana_skipped")
    statuses = {s.step_id: s.status for s in index.steps}
    assert statuses["step_09_production"] == "skipped", statuses
    assert statuses["step_10_analysis"] == "skipped", statuses
