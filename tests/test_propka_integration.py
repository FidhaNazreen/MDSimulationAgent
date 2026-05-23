"""End-to-end test: PROPKA actually changes per-residue topology answers
between pH 7 and pH 5.

Slow + gmx-gated.
"""

from __future__ import annotations

import json
import shutil
import socket
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from mdagent import propka_helper

pytestmark = [
    pytest.mark.skipif(shutil.which("gmx") is None, reason="gmx not installed"),
    pytest.mark.skipif(not propka_helper.propka_available(), reason="propka not installed"),
    pytest.mark.slow,
]


def _have_internet() -> bool:
    try:
        urllib.request.urlopen("https://files.rcsb.org/", timeout=5)
        return True
    except (OSError, urllib.error.URLError, socket.timeout):
        return False


_LYSOZYME_PDB = Path("/Users/manu_jay/git_repos/MDSimulationAgent/src/mdagent/_resources/starter_kit/structures/1aki.pdb")


def _make_config(tmp_path: Path, ph: float) -> Path:
    cfg = {
        "schema_version": "0.1.0",
        "pipeline_mode": "general_md_prep",
        "interaction_mode": "noninteractive_defaults",
        "input": {"structure_path": str(_LYSOZYME_PDB), "format_preference": "pdb"},
        "force_field": "oplsaa",
        "water_model": "spc",
        "ph": ph,
        "protonation_policy": "propka",
        "box": {"geometry": "dodecahedron", "padding_nm": 1.0, "cutoff_nm": 1.0},
        "ion_strategy": {"mode": "neutralize_only", "cation": "NA", "anion": "CL", "random_seed": 42},
        "em": {"step_cap": 1000, "fmax_tol_kjmolnm": 1000.0},
        "nvt": {"nsteps": 500, "dt_ps": 0.002, "temperature_K": 300.0, "random_seed": 42},
        "npt": {"nsteps": 500, "dt_ps": 0.002, "temperature_K": 300.0, "pressure_bar": 1.0},
        "production": {"enabled": False},
        "tool_versions": {"gromacs": "2026.2"},
    }
    p = tmp_path / f"cfg_pH{int(ph)}.json"
    p.write_text(json.dumps(cfg, indent=2, sort_keys=True))
    return p


def _topology_answer_for_his15(run_root: Path) -> str:
    """Extract the HIS-15 answer from this run's protonation_decisions.json."""
    decisions = json.loads((run_root / "step_04_topology" / "protonation_decisions.json").read_text())
    plan = {(d["residue_name"], d["resid"]): d for d in decisions["planned"]}
    return plan[("HIS", 15)]["answer_index"]


def test_propka_changes_HIS15_answer_between_pH7_and_pH5(tmp_path: Path) -> None:
    """1AKI HIS 15 has a PROPKA-predicted pKa around ~6 (varies by structure).
    At pH 7 (above pKa) → neutral form (HIE, option 1).
    At pH 5 (below pKa) → protonated form (HIP, option 2).
    The test asserts the answers DIFFER between the two runs."""
    from mdagent import run_workflow

    # --- Run at pH 7 ---
    cfg_ph7 = _make_config(tmp_path, ph=7.0)
    run7_root, _ = run_workflow(
        run_config_path=cfg_ph7,
        runs_root=tmp_path / "runs",
        run_id="ph7",
        stop_after_step_id="step_04_topology",  # we only need topology to make the comparison
    )

    # --- Run at pH 5 ---
    cfg_ph5 = _make_config(tmp_path, ph=5.0)
    run5_root, _ = run_workflow(
        run_config_path=cfg_ph5,
        runs_root=tmp_path / "runs",
        run_id="ph5",
        stop_after_step_id="step_04_topology",
    )

    ans7 = _topology_answer_for_his15(run7_root)
    ans5 = _topology_answer_for_his15(run5_root)

    # The HIS 15 answer MUST be different between pH 7 and pH 5 — that's
    # the whole point of pKa-aware protonation.
    assert ans7 != ans5, f"HIS 15 answer the same at pH 7 ({ans7}) and pH 5 ({ans5})"

    # Sanity: at pH 7 the HIS should be neutral (option 1, HIE).
    # At pH 5 it should be protonated (option 2, HIP).
    assert ans7 == "1", f"expected HIE (1) at pH 7, got {ans7}"
    assert ans5 == "2", f"expected HIP (2) at pH 5, got {ans5}"

    # Source field should reflect propka-driven decisions.
    decisions7 = json.loads((run7_root / "step_04_topology" / "protonation_decisions.json").read_text())
    his_entry = next(d for d in decisions7["planned"] if d["residue_name"] == "HIS" and d["resid"] == 15)
    assert his_entry["source"].startswith("propka@pH"), his_entry
