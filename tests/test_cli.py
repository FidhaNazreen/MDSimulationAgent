"""CLI smoke tests — no GROMACS required for these."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from mdagent.cli import build_parser, main


def test_parser_smoke():
    p = build_parser()
    args = p.parse_args(["run-workflow", "--runs-root", "/tmp/x", "--pdb-id", "1AKI"])
    assert args.cmd == "run-workflow"
    assert args.pdb_id == "1AKI"
    assert args.pipeline_mode == "tutorial_reproduction"


def test_inspect_command_reads_index(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """`inspect` must read an existing index.json and print step rows."""
    from mdagent import RunIndex
    idx = RunIndex.initialize(run_id="demo", run_config_hash="a" * 64)
    # Mark two as succeeded so the format-printing covers fingerprint slots
    for s in idx.steps[:2]:
        s.status = "succeeded"
        s.fingerprint_composite = "f" * 64
    idx.write(tmp_path / "index.json")

    rc = main(["inspect", "--run-root", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "run_id: demo" in out
    assert "step_01_structure_ingest" in out
    assert "succeeded" in out
    assert "ffffffffffffffff" in out  # the 16-char composite slice
