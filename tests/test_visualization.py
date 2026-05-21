"""Visualization step tests — no real viewer required."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mdagent import RunConfig
from mdagent.steps import StepContext, visualization
from mdagent.steps.visualization import probe_viewers


def _minimal_pdb() -> str:
    """The smallest valid PDB the Tcl/PML scripts can reference."""
    return """\
ATOM      1  N   ALA A   1       0.000   0.000   0.000  1.00  0.00           N
ATOM      2  CA  ALA A   1       1.500   0.000   0.000  1.00  0.00           C
ATOM      3  C   ALA A   1       2.000   1.300   0.000  1.00  0.00           C
ATOM      4  O   ALA A   1       1.300   2.300   0.000  1.00  0.00           O
TER       5      ALA A   1
END
"""


def _make_cfg(**viz_overrides) -> RunConfig:
    cfg = {
        "schema_version": "0.1.0",
        "pipeline_mode": "tutorial_reproduction",
        "interaction_mode": "interactive",
        "input": {"pdb_id": "1AKI"},
        "visualization": {"mode": "default", **viz_overrides},
    }
    return RunConfig.from_dict(cfg)


def _make_ctx(tmp_path: Path, role: str, content: str, cfg: RunConfig) -> StepContext:
    art = tmp_path / "structure.pdb"
    art.write_text(content)
    step_dir = tmp_path / "step_11_visualization"
    step_dir.mkdir()
    inputs = [{
        "artifact_uri": f"local://{art}",
        "content_hash": "0" * 64,  # arbitrary; visualization doesn't verify hashes
        "role": role,
    }]
    return StepContext(
        step_id="step_11_visualization",
        run_root=tmp_path,
        step_dir=step_dir,
        run_config=cfg,
        inputs=inputs,
    )


def test_probe_viewers_returns_known_keys():
    p = probe_viewers()
    assert set(p.keys()) == {"vmd", "pymol", "nglview"}
    # Each ViewerProbe has a `.available` bool — the only invariant we test
    # since we don't know what's installed.
    for v in p.values():
        assert isinstance(v.available, bool)


def test_disabled_mode_passes_through(tmp_path: Path):
    cfg = _make_cfg(mode="disabled")
    ctx = _make_ctx(tmp_path, "working_pdb", _minimal_pdb(), cfg)
    out = visualization.run(ctx)
    assert out.ok
    assert out.extra["skipped"] is True
    assert out.outputs == []


def test_writes_tcl_script_when_no_viewer(tmp_path: Path):
    """With no viewer available the step still writes Tcl scripts."""
    cfg = _make_cfg(mode="default", viewer="vmd", checkpoints=["prep"])
    ctx = _make_ctx(tmp_path, "working_pdb", _minimal_pdb(), cfg)
    out = visualization.run(ctx)
    assert out.ok
    tcl = tmp_path / "step_11_visualization" / "prep" / "visualize.vmd"
    assert tcl.is_file()
    assert "mol new" in tcl.read_text()


def test_skipped_renderer_recorded_in_probe_json(tmp_path: Path):
    cfg = _make_cfg(mode="default", viewer="vmd", checkpoints=["prep"])
    ctx = _make_ctx(tmp_path, "working_pdb", _minimal_pdb(), cfg)
    out = visualization.run(ctx)
    probe_path = tmp_path / "step_11_visualization" / "render_probe.json"
    assert probe_path.is_file()
    probe = json.loads(probe_path.read_text())
    # Rendered list always populated for every requested checkpoint.
    rendered = probe["rendered"]
    assert len(rendered) == 1
    if probe["viewer_status"]["selected_viewer"] is None:
        # No VMD installed → no_viewer_available
        assert rendered[0]["rendered"] is False
        assert rendered[0]["reason"] == "no_viewer_available"


def test_checkpoint_missing_artifact_records_a_warning(tmp_path: Path):
    """Asking for the `em` checkpoint when no em_gro is present produces a clear note."""
    cfg = _make_cfg(mode="default", viewer="auto", checkpoints=["em"])
    ctx = _make_ctx(tmp_path, "working_pdb", _minimal_pdb(), cfg)  # only working_pdb supplied
    out = visualization.run(ctx)
    assert out.ok
    # Step succeeds, but `rendered` shows the missing-artifact note.
    probe = json.loads((tmp_path / "step_11_visualization" / "render_probe.json").read_text())
    em_entry = next(r for r in probe["rendered"] if r["checkpoint"] == "em")
    assert em_entry["status"] == "checkpoint_artifact_missing"


def test_all_checkpoints_keyword_expands(tmp_path: Path):
    """`checkpoints=['all']` expands to every known checkpoint."""
    cfg = _make_cfg(mode="default", viewer="auto", checkpoints=["all"])
    ctx = _make_ctx(tmp_path, "working_pdb", _minimal_pdb(), cfg)
    out = visualization.run(ctx)
    assert out.ok
    probe = json.loads((tmp_path / "step_11_visualization" / "render_probe.json").read_text())
    checkpoints_seen = {r["checkpoint"] for r in probe["rendered"]}
    assert checkpoints_seen == {"prep", "topology", "solvated", "em"}


def test_unknown_viewer_gracefully_falls_through(tmp_path: Path):
    """An explicitly-requested viewer that isn't on PATH is reported, not crashed."""
    cfg = _make_cfg(mode="default", viewer="vmd", checkpoints=["prep"])  # vmd not on PATH in CI
    ctx = _make_ctx(tmp_path, "working_pdb", _minimal_pdb(), cfg)
    out = visualization.run(ctx)
    assert out.ok
    # Either VMD is somehow installed (rendered=True) or it isn't (rendered=False)
    # — either way the step does not fail.
