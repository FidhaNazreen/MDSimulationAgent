"""StepReport tests — schema validation, atomic write, round trip, error path."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from jsonschema import ValidationError

from mdagent import ArtifactRef, ExecutorCall, FailureReason, StepReport, Warning_


def _minimal_report() -> StepReport:
    return StepReport(
        step_id="step_04_topology",
        attempt=1,
        status="succeeded",
        inputs=[ArtifactRef(artifact_uri="local://prep/working.pdb", content_hash="a" * 64, role="cleaned_pdb")],
        outputs=[ArtifactRef(artifact_uri="local://topo/system.top", content_hash="b" * 64)],
        executor_calls=[ExecutorCall(argv=["gmx", "pdb2gmx", "-f", "in.pdb"], exit_status=0, wall_time_s=0.5)],
    )


def test_write_validates_and_round_trips(tmp_path: Path) -> None:
    rep = _minimal_report()
    rep.ended_at = "2026-05-20T21:00:00Z"
    path = tmp_path / "step_report.json"
    rep.write(path)
    loaded = StepReport.read(path)
    assert loaded["step_id"] == "step_04_topology"
    assert loaded["status"] == "succeeded"
    assert loaded["inputs"][0]["role"] == "cleaned_pdb"
    assert loaded["executor_calls"][0]["argv"] == ["gmx", "pdb2gmx", "-f", "in.pdb"]


def test_write_rejects_bad_status(tmp_path: Path) -> None:
    rep = _minimal_report()
    rep.status = "totally_invalid"
    with pytest.raises(ValidationError):
        rep.write(tmp_path / "x.json")


def test_write_rejects_bad_failure_code(tmp_path: Path) -> None:
    rep = _minimal_report()
    rep.status = "failed"
    rep.failure_reason = FailureReason(code="MadeUpError", message="x")
    with pytest.raises(ValidationError):
        rep.write(tmp_path / "x.json")


def test_warnings_serialize(tmp_path: Path) -> None:
    rep = _minimal_report()
    rep.warnings = [Warning_(cls="physics", severity="warning", message="EM needs longer")]
    path = tmp_path / "r.json"
    rep.write(path)
    data = StepReport.read(path)
    assert data["warnings"][0]["class"] == "physics"
    assert data["warnings"][0]["severity"] == "warning"


def test_atomic_write_no_tempfile_leftover(tmp_path: Path) -> None:
    rep = _minimal_report()
    path = tmp_path / "r.json"
    rep.write(path)
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.startswith(".step_report-")]
    assert leftovers == [], f"temp files leaked: {leftovers}"


def test_atomic_write_does_not_leave_partial_on_failure(tmp_path: Path, monkeypatch) -> None:
    """If validation fails inside .write() before rename, no .json appears at the target."""
    rep = _minimal_report()
    rep.status = "totally_invalid"  # will fail schema validation
    path = tmp_path / "r.json"
    with pytest.raises(ValidationError):
        rep.write(path)
    assert not path.exists()
    leftovers = list(tmp_path.iterdir())
    assert leftovers == [], f"unexpected files: {[p.name for p in leftovers]}"
