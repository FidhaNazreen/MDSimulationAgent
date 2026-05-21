"""mmCIF ingest + coordinate_id_map tests.

Fixtures are built programmatically via gemmi so the CIFs are guaranteed
valid (gemmi-written round-trips correctly).
"""

from __future__ import annotations

import json
from pathlib import Path

import gemmi
import pytest

from mdagent import RunConfig
from mdagent.steps import StepContext, ingest
from mdagent.steps.ingest import _resolve_format


def _write_cif(path: Path, residues: list[tuple[str, str, int, str]]) -> None:
    """`residues` is a list of (chain, resname, seqid_num, icode)."""
    st = gemmi.Structure()
    st.name = "TEST"
    model = gemmi.Model("1")
    chains: dict[str, gemmi.Chain] = {}
    for ch, resname, seqid_num, icode in residues:
        if ch not in chains:
            chains[ch] = gemmi.Chain(ch)
        res = gemmi.Residue()
        res.name = resname
        res.seqid = gemmi.SeqId(seqid_num, icode if icode else " ")
        res.entity_type = gemmi.EntityType.Polymer
        a = gemmi.Atom()
        a.name = "N"
        a.pos = gemmi.Position(0.0, 0.0, 0.0)
        a.element = gemmi.Element("N")
        res.add_atom(a)
        chains[ch].add_residue(res)
    for ch in chains.values():
        model.add_chain(ch)
    st.add_model(model)
    st.make_mmcif_document().write_file(str(path))


def _make_ctx(tmp_path: Path, fmt: str, structure_path: Path) -> StepContext:
    cfg = RunConfig.from_dict({
        "schema_version": "0.1.0",
        "pipeline_mode": "general_md_prep",
        "interaction_mode": "noninteractive_defaults",
        "input": {
            "structure_path": str(structure_path),
            "format_preference": fmt,
        },
    })
    step_dir = tmp_path / "step_01_structure_ingest"
    step_dir.mkdir()
    return StepContext(
        step_id="step_01_structure_ingest",
        run_root=tmp_path,
        step_dir=step_dir,
        run_config=cfg,
    )


def test_format_resolution_defaults_per_mode():
    cfg = RunConfig.from_dict({
        "schema_version": "0.1.0",
        "pipeline_mode": "tutorial_reproduction",
        "interaction_mode": "noninteractive_defaults",
        "input": {"pdb_id": "1AKI"},
    })
    assert _resolve_format(cfg) == "pdb"

    cfg2 = RunConfig.from_dict({
        "schema_version": "0.1.0",
        "pipeline_mode": "general_md_prep",
        "interaction_mode": "noninteractive_defaults",
        "input": {"pdb_id": "1AKI"},
    })
    assert _resolve_format(cfg2) == "mmcif"

    cfg3 = RunConfig.from_dict({
        "schema_version": "0.1.0",
        "pipeline_mode": "general_md_prep",
        "interaction_mode": "noninteractive_defaults",
        "input": {"pdb_id": "1AKI", "format_preference": "pdb"},
    })
    assert _resolve_format(cfg3) == "pdb"


def test_mmcif_ingest_emits_verified_coordinate_id_map(tmp_path: Path):
    cif_path = tmp_path / "input.cif"
    _write_cif(cif_path, [("A", "ALA", 1, ""), ("A", "GLY", 2, "")])
    ctx = _make_ctx(tmp_path, fmt="mmcif", structure_path=cif_path)
    out = ingest.run(ctx)
    assert out.ok, out.failure

    coord_map = json.loads((tmp_path / "step_01_structure_ingest" / "coordinate_id_map.json").read_text())
    assert coord_map["injectivity"] == "verified"
    assert len(coord_map["residues"]) == 2

    first = coord_map["residues"][0]
    assert first["canonical"]["residue_name"] == "ALA"
    assert first["canonical"]["auth_seq_id"] == 1
    assert first["derived_pdb"]["chain"] == "A"
    assert first["derived_pdb"]["resid"] == 1

    roles = {o["role"] for o in out.outputs}
    assert {"original_structure", "derived_pdb", "working_pdb", "coordinate_id_map"} <= roles


def test_mmcif_ingest_hard_fails_on_collision(tmp_path: Path):
    """Two residues both at (chain='A', resid=5, icode='') triggers
    CoordinateIdMapNotInjective."""
    cif_path = tmp_path / "bad.cif"
    # Use the same chain & seqid for both residues — under PDB encoding,
    # they collide on (chain, resid, icode).
    # gemmi will allow this in the structure; the ingest must catch it.
    st = gemmi.Structure()
    st.name = "BAD"
    model = gemmi.Model("1")
    chain = gemmi.Chain("A")
    for resname in ("ALA", "GLY"):
        res = gemmi.Residue()
        res.name = resname
        res.seqid = gemmi.SeqId(5, " ")  # same seqid for both
        res.entity_type = gemmi.EntityType.Polymer
        a = gemmi.Atom()
        a.name = "N"
        a.pos = gemmi.Position(0.0, 0.0, 0.0)
        a.element = gemmi.Element("N")
        res.add_atom(a)
        chain.add_residue(res)
    model.add_chain(chain)
    st.add_model(model)
    st.make_mmcif_document().write_file(str(cif_path))

    ctx = _make_ctx(tmp_path, fmt="mmcif", structure_path=cif_path)
    out = ingest.run(ctx)
    assert not out.ok, "expected failure on collision"
    assert out.failure["code"] == "CoordinateIdMapNotInjective", out.failure

    coord_map_path = tmp_path / "step_01_structure_ingest" / "coordinate_id_map.json"
    assert coord_map_path.is_file()  # diff must be written for user inspection
    coord_map = json.loads(coord_map_path.read_text())
    assert coord_map["injectivity"] == "lossy_with_diff"
    assert len(coord_map["lossy_diff"]) >= 1


def test_pdb_ingest_skips_coordinate_id_map(tmp_path: Path):
    pdb_path = tmp_path / "input.pdb"
    pdb_path.write_text(
        "ATOM      1  N   ALA A   1       0.000   0.000   0.000  1.00  0.00           N\n"
        "ATOM      2  CA  ALA A   1       1.500   0.000   0.000  1.00  0.00           C\n"
        "END\n"
    )
    ctx = _make_ctx(tmp_path, fmt="pdb", structure_path=pdb_path)
    out = ingest.run(ctx)
    assert out.ok
    roles = {o["role"] for o in out.outputs}
    assert "coordinate_id_map" not in roles
    assert "working_pdb" in roles


def test_insertion_codes_preserved_when_distinct(tmp_path: Path):
    """Two residues at same auth_seq_id with DIFFERENT insertion codes
    must remain injective."""
    cif_path = tmp_path / "icode.cif"
    _write_cif(cif_path, [("A", "ALA", 5, "A"), ("A", "GLY", 5, "B")])
    ctx = _make_ctx(tmp_path, fmt="mmcif", structure_path=cif_path)
    out = ingest.run(ctx)
    assert out.ok, out.failure
    coord_map = json.loads((tmp_path / "step_01_structure_ingest" / "coordinate_id_map.json").read_text())
    assert coord_map["injectivity"] == "verified", coord_map
    icodes = [r["canonical"]["insertion_code"] for r in coord_map["residues"]]
    assert set(icodes) == {"A", "B"}
