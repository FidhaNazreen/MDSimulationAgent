"""PROPKA-driven protonation tests."""

from __future__ import annotations

import json
import shutil
import socket
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from mdagent import propka_helper
from mdagent.steps.topology import _pka_aware_answer

_LYSOZYME_PDB = Path("/Users/manu_jay/git_repos/MDSimulationAgent/src/mdagent/_resources/starter_kit/structures/1aki.pdb")


# ---- Pure unit tests (no external deps) -------------------------------


def test_pka_aware_answer_lys_protonated_above_ph():
    answer, source = _pka_aware_answer("LYSINE", pka_value=10.5, ph=7.0)
    assert answer == "1"  # LYSH
    assert source == "propka@pH7.0"


def test_pka_aware_answer_lys_neutral_below_ph():
    answer, source = _pka_aware_answer("LYSINE", pka_value=5.0, ph=7.0)
    assert answer == "0"  # LYS (neutral)


def test_pka_aware_answer_asp_protonated_above_ph():
    """ASP with elevated pKa (>pH) = protonated = option 1 (ASPH)."""
    answer, _ = _pka_aware_answer("ASPARTIC ACID", pka_value=8.0, ph=7.0)
    assert answer == "1"


def test_pka_aware_answer_asp_deprotonated_below_ph():
    answer, _ = _pka_aware_answer("ASPARTIC ACID", pka_value=3.5, ph=7.0)
    assert answer == "0"


def test_pka_aware_answer_his_HIE_at_neutral_ph():
    """HIS with pKa < pH → neutral form, default to HIE (option 1)."""
    answer, _ = _pka_aware_answer("HISTIDINE", pka_value=6.31, ph=7.0)
    assert answer == "1"


def test_pka_aware_answer_his_HIP_at_low_ph():
    """HIS with pKa > pH → protonated form (HIP, option 2)."""
    answer, _ = _pka_aware_answer("HISTIDINE", pka_value=6.31, ph=5.0)
    assert answer == "2"


def test_pka_aware_answer_falls_back_to_default_when_no_pka():
    answer, source = _pka_aware_answer("HISTIDINE", pka_value=None, ph=7.0)
    assert answer == "1"  # default
    assert source == "policy_default_pH7"


def test_pka_aware_answer_treats_9999_sentinel_as_no_pka():
    """PROPKA emits 99.99 for non-titratable groups (e.g. CYS in a disulfide)."""
    answer, source = _pka_aware_answer("CYSTEINE", pka_value=99.99, ph=7.0)
    assert source == "policy_default_pH7"
    assert answer == "0"


def test_propka_available_returns_bool():
    """propka_available() is a clean boolean check."""
    assert isinstance(propka_helper.propka_available(), bool)


# ---- PROPKA execution tests (require propka) --------------------------


@pytest.mark.skipif(not propka_helper.propka_available(), reason="propka not installed")
def test_propka_analyze_returns_expected_residues():
    """PROPKA on 1AKI should detect at least the canonical titratable residues."""
    if not _LYSOZYME_PDB.is_file():
        pytest.skip("bundled 1aki.pdb not found")
    result = propka_helper.analyze(_LYSOZYME_PDB, ph=7.0)
    assert result["method"] == "propka"
    assert result["ph_assumed"] == 7.0
    assert result["propka_version"]
    # 1AKI has 6 LYS + 11 ARG + 7 ASP + 2 GLU + 1 HIS + 8 CYS = ~35 titratable.
    assert 25 <= len(result["residues"]) <= 50, len(result["residues"])
    types_present = {r["residue_type"] for r in result["residues"]}
    assert {"HIS", "ASP", "GLU", "LYS", "ARG", "CYS"} <= types_present


@pytest.mark.skipif(not propka_helper.propka_available(), reason="propka not installed")
def test_propka_his15_in_known_pka_range():
    """1AKI HIS 15 should have pKa in a reasonable range (literature ~5–7)."""
    if not _LYSOZYME_PDB.is_file():
        pytest.skip("bundled 1aki.pdb not found")
    result = propka_helper.analyze(_LYSOZYME_PDB, ph=7.0)
    his_entries = [r for r in result["residues"] if r["residue_type"] == "HIS" and r["resid"] == 15]
    assert his_entries, "HIS 15 not found in propka output"
    pka = his_entries[0]["pka_value"]
    assert 4.0 < pka < 8.5, f"HIS 15 pKa {pka} outside the expected range"


@pytest.mark.skipif(not propka_helper.propka_available(), reason="propka not installed")
def test_propka_cys_disulfide_marked_999():
    """CYS in disulfide bonds get pKa=99.99 from PROPKA."""
    if not _LYSOZYME_PDB.is_file():
        pytest.skip("bundled 1aki.pdb not found")
    result = propka_helper.analyze(_LYSOZYME_PDB, ph=7.0)
    cys_entries = [r for r in result["residues"] if r["residue_type"] == "CYS"]
    # Every CYS in lysozyme is in a disulfide (4 SS pairs covering all 8).
    # So every CYS pKa should be either 99.99 (PROPKA's sentinel) or
    # None / very high.
    for c in cys_entries:
        assert c["pka_value"] is None or c["pka_value"] >= 50, c


# ---- StructurePrep integration ----------------------------------------


def test_structure_prep_emits_protonation_analysis_when_propka_available(tmp_path: Path):
    """When protonation_policy=propka, StructurePrep emits the analysis JSON."""
    from mdagent import RunConfig
    from mdagent.steps import StepContext, prep
    if not propka_helper.propka_available():
        pytest.skip("propka not installed")
    if not _LYSOZYME_PDB.is_file():
        pytest.skip("bundled 1aki.pdb not found")

    cfg = RunConfig.from_dict({
        "schema_version": "0.1.0",
        "pipeline_mode": "general_md_prep",
        "interaction_mode": "noninteractive_defaults",
        "input": {"structure_path": str(_LYSOZYME_PDB)},
        "ph": 7.0,
        "protonation_policy": "propka",
    })
    inputs = [{"artifact_uri": f"local://{_LYSOZYME_PDB}", "content_hash": "0" * 64, "role": "working_pdb"}]
    step_dir = tmp_path / "step_03_structure_prep"
    step_dir.mkdir()
    ctx = StepContext(
        step_id="step_03_structure_prep",
        run_root=tmp_path,
        step_dir=step_dir,
        run_config=cfg,
        inputs=inputs,
    )
    outcome = prep.run(ctx)
    assert outcome.ok, outcome.failure
    analysis_path = step_dir / "protonation_analysis.json"
    assert analysis_path.is_file()
    analysis = json.loads(analysis_path.read_text())
    assert analysis["method"] == "propka"
    assert outcome.extra["protonation_method"] == "propka"


# ---- Doctor warning ---------------------------------------------------


def test_doctor_warns_when_propka_policy_and_missing(monkeypatch: pytest.MonkeyPatch):
    """If protonation_policy=propka but propka is not importable, doctor records a warning."""
    from mdagent import RunConfig
    from mdagent.doctor import check_for_run

    cfg = RunConfig.from_dict({
        "schema_version": "0.1.0",
        "pipeline_mode": "general_md_prep",
        "interaction_mode": "noninteractive_defaults",
        "input": {"pdb_id": "1AKI"},
        "protonation_policy": "propka",
    })
    # Pretend propka isn't importable.
    monkeypatch.setattr("mdagent.propka_helper.propka_available", lambda: False)
    monkeypatch.setattr("mdagent.propka_helper.propka_version", lambda: None)

    result = check_for_run(
        cfg,
        planned_step_ids={"step_03_structure_prep"},
        skip_network=True,
    )
    # propka entry exists, is a warning (not fail), suggestion is populated.
    assert "propka" in result.checks
    assert result.checks["propka"].status == "warning"
    assert result.checks["propka"].suggestion is not None
    # Doctor still ok overall (warnings don't fail).
    assert result.ok
