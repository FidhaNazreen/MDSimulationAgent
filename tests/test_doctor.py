"""Doctor / transferability tests."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from mdagent import RunConfig
from mdagent.doctor import GMX_REQUIRING_STEPS, check_for_run, standalone


def _prep_only_config() -> RunConfig:
    return RunConfig.from_dict({
        "schema_version": "0.1.0",
        "pipeline_mode": "tutorial_reproduction",
        "interaction_mode": "noninteractive_defaults",
        "input": {"pdb_id": "1AKI"},
    })


def _full_config() -> RunConfig:
    return RunConfig.from_dict({
        "schema_version": "0.1.0",
        "pipeline_mode": "tutorial_reproduction",
        "interaction_mode": "noninteractive_defaults",
        "input": {"pdb_id": "1AKI"},
    })


def test_prep_only_does_not_require_gmx(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the planned steps don't include any GMX_REQUIRING_STEPS, doctor
    must not fail even with `gmx` stripped from PATH."""
    # Strip gmx (and uv) from PATH for this test.
    monkeypatch.setenv("PATH", "/tmp")
    cfg = _prep_only_config()
    planned = {"step_01_structure_ingest", "step_02_classifier", "step_03_structure_prep"}
    result = check_for_run(cfg, planned_step_ids=planned)
    assert result.ok, result.to_dict()
    gmx_entry = result.checks.get("gmx_available")
    assert gmx_entry is not None
    assert gmx_entry.status == "skipped"


def test_full_pipeline_requires_gmx_when_present(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _full_config()
    planned = GMX_REQUIRING_STEPS | {"step_01_structure_ingest"}
    # Don't strip PATH — let the real gmx (if installed) drive the check.
    result = check_for_run(cfg, planned_step_ids=planned, skip_network=True)
    gmx_entry = result.checks["gmx_available"]
    # We can't assert "ok" here unconditionally because gmx may not be
    # on the test runner's PATH. But we CAN assert it was checked
    # (status != "skipped" since gmx_required is True).
    assert gmx_entry.status in {"ok", "fail"}


def test_full_pipeline_fails_when_gmx_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", "/tmp")
    cfg = _full_config()
    planned = GMX_REQUIRING_STEPS | {"step_01_structure_ingest"}
    result = check_for_run(cfg, planned_step_ids=planned, skip_network=True)
    assert not result.ok
    assert result.checks["gmx_available"].status == "fail"
    assert "GROMACS" in (result.checks["gmx_available"].suggestion or "")


def test_visualizer_check_skipped_for_disabled_mode() -> None:
    cfg = RunConfig.from_dict({
        "schema_version": "0.1.0",
        "pipeline_mode": "tutorial_reproduction",
        "interaction_mode": "noninteractive_defaults",
        "input": {"pdb_id": "1AKI"},
        "visualization": {"mode": "disabled"},
    })
    result = check_for_run(cfg, planned_step_ids={"step_01_structure_ingest"}, skip_network=True)
    assert result.checks["viewer_renderable"].status == "skipped"


def test_visualizer_check_skipped_for_state_only_render() -> None:
    """Even with viz enabled, render=state_only doesn't need a viewer binary."""
    cfg = RunConfig.from_dict({
        "schema_version": "0.1.0",
        "pipeline_mode": "tutorial_reproduction",
        "interaction_mode": "noninteractive_defaults",
        "input": {"pdb_id": "1AKI"},
        "visualization": {"mode": "default", "render": "state_only"},
    })
    result = check_for_run(cfg, planned_step_ids={"step_01_structure_ingest"}, skip_network=True)
    assert result.checks["viewer_renderable"].status == "skipped"


def test_standalone_min_version_check_ok() -> None:
    result = standalone(min_version="0.1.0")
    assert result.ok
    assert result.checks["min_version"].status == "ok"


def test_standalone_min_version_check_fails_for_higher() -> None:
    result = standalone(min_version="99.0.0")
    assert not result.ok
    assert result.checks["min_version"].status == "fail"
    assert "upgrade" in (result.checks["min_version"].suggestion or "").lower() or \
           "newer" in (result.checks["min_version"].suggestion or "").lower()


def test_install_skills_dry_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """`mdagent install-skills --project DIR --dry-run` lists what would be written."""
    from mdagent.cli import main
    rc = main(["install-skills", "--project", str(tmp_path), "--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["dry_run"] is True
    assert payload["destination"] == str((tmp_path / ".claude" / "skills").resolve())
    # The 3 packaged skills should be listed.
    assert len(payload["written"]) == 3
    assert all("SKILL.md" in p for p in payload["written"])
    # No file actually written in dry-run.
    assert not (tmp_path / ".claude").exists() or not list((tmp_path / ".claude" / "skills").rglob("SKILL.md"))


def test_install_skills_writes_to_project_dir(tmp_path: Path) -> None:
    from mdagent.cli import main
    rc = main(["install-skills", "--project", str(tmp_path)])
    assert rc == 0
    dest = tmp_path / ".claude" / "skills"
    assert dest.is_dir()
    skills = sorted(p.name for p in dest.iterdir() if (p / "SKILL.md").is_file())
    assert skills == ["md-prep-structure", "md-run-workflow", "md-visualize"]


def test_self_test_resources_passes() -> None:
    from mdagent.cli import main
    rc = main(["self-test", "resources", "--json"])
    assert rc == 0


def test_cli_version() -> None:
    """`mdagent --version` returns the installed version."""
    from mdagent.cli import main
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
