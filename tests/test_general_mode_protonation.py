"""general_md_prep mode: drive `pdb2gmx -inter` and confirm every
titratable residue gets a recorded answer."""

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


def test_general_mode_inter_drives_per_residue_protonation(tmp_path: Path) -> None:
    """Run prep+topology on 1AKI in general_md_prep mode. Every titratable
    residue must end up with an entry in protonation_decisions.json."""
    if not _have_internet():
        pytest.skip("no internet")

    from mdagent import run_workflow

    cfg = {
        "schema_version": "0.1.0",
        "pipeline_mode": "general_md_prep",
        "interaction_mode": "noninteractive_defaults",
        # general_md_prep mode picks mmcif fetch by default — override to pdb to
        # keep the test fast (mmCIF derivation is exercised in test_mmcif_ingest.py).
        "input": {"pdb_id": "1AKI", "format_preference": "pdb"},
        "force_field": "oplsaa",
        "water_model": "spc",
        "box": {"geometry": "dodecahedron", "padding_nm": 1.0, "cutoff_nm": 1.0},
        "ion_strategy": {"mode": "neutralize_only", "cation": "NA", "anion": "CL", "random_seed": 42},
        "em": {"step_cap": 1000, "fmax_tol_kjmolnm": 1000.0},
        "nvt": {"nsteps": 500, "dt_ps": 0.002, "temperature_K": 300.0, "random_seed": 42},
        "npt": {"nsteps": 500, "dt_ps": 0.002, "temperature_K": 300.0, "pressure_bar": 1.0},
        "production": {"enabled": False},
        "tool_versions": {"gromacs": "2026.2"},
    }
    cfg_path = tmp_path / "run_config.json"
    cfg_path.write_text(json.dumps(cfg, indent=2, sort_keys=True))

    run_root, index = run_workflow(run_config_path=cfg_path, runs_root=tmp_path / "runs", run_id="inter")

    # Pipeline succeeded through topology.
    statuses = {s.step_id: s.status for s in index.steps}
    assert statuses["step_04_topology"] == "succeeded", statuses

    # observations.json lists every titratable residue.
    obs = json.loads((run_root / "step_03_structure_prep" / "observations.json").read_text())
    titratable = obs.get("titratable_residues", [])
    # Lysozyme 1AKI has roughly: 6 LYS + 11 ARG + 3 GLN + 7 ASP + 2 GLU + 1 HIS + 8 CYS ≈ 38
    assert 30 <= len(titratable) <= 50, f"unexpected titratable count {len(titratable)}"

    # topology_plan records the planned decision per residue.
    plan = json.loads((run_root / "step_04_topology" / "topology_plan.json").read_text())
    assert plan["pipeline_mode"] == "general_md_prep"
    assert len(plan["protonation_decisions"]) == len(titratable)
    # Sanity: every entry has the expected fields and an answer_index that
    # is one of the allowed defaults.
    for d in plan["protonation_decisions"]:
        assert "chain" in d and "resid" in d and "residue_name" in d
        assert d["answer_index"] in {"0", "1", "2"}
        assert d["source"] == "policy_default_pH7"

    # protonation_decisions.json records BOTH the plan AND what actually fired.
    decisions = json.loads((run_root / "step_04_topology" / "protonation_decisions.json").read_text())
    assert "planned" in decisions and "actual" in decisions
    # `actual` covers most of the planned residues but excludes CYS that
    # pdb2gmx auto-converted to CYS2 (disulfide-bonded). For 1AKI: all 8
    # cysteines form 4 SS pairs, so 8 CYS prompts go silent.
    n_planned_cys = sum(1 for d in decisions["planned"] if d["prompt_name"] == "CYSTEINE")
    assert len(decisions["actual"]) == len(decisions["planned"]) - n_planned_cys
    # Every actual answer came from the plan.
    for a in decisions["actual"]:
        assert a["answer_source"] == "plan", a

    # Spot-check 1AKI residues at pH 7 under OPLS-AA:
    by_key = {(d["residue_type"], d["resid"]): d for d in decisions["actual"]}
    assert by_key[("HISTIDINE", 15)]["answer_index"] == "1"     # HIE
    assert by_key[("LYSINE", 1)]["answer_index"] == "1"          # LYSH (protonated)
    assert by_key[("ASPARTIC ACID", 18)]["answer_index"] == "0"  # ASP (deprotonated)

    # And we still produced the topology artifacts.
    assert (run_root / "step_04_topology" / "system_apo.gro").is_file()
    assert (run_root / "step_04_topology" / "system_apo.top").is_file()
