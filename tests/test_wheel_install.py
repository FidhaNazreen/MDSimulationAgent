"""Wheel-install smoke test.

Builds the wheel via `uv build`, installs it into a clean virtualenv,
runs `mdagent --version` and `mdagent self-test resources --json` to
prove the package's resources (schemas + skills) ship correctly and
load from `importlib.resources`.

Marked `wheel` so it's opt-in (`--run-wheel`); the build step takes
~10 s. Skipped if `uv` is not on PATH.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.skipif(shutil.which("uv") is None, reason="uv not installed"),
    pytest.mark.wheel,
]


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def test_wheel_installs_and_self_tests(tmp_path: Path) -> None:
    repo = _project_root()
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()

    # 1) Build the wheel via uv.
    r = subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(dist_dir)],
        cwd=str(repo), capture_output=True, text=True,
    )
    assert r.returncode == 0, f"uv build failed:\n{r.stderr}"
    wheels = list(dist_dir.glob("mdagent-*.whl"))
    assert len(wheels) == 1, f"expected 1 wheel, got {wheels}"
    wheel = wheels[0]

    # 2) Create a clean venv (no site-packages from this checkout).
    venv = tmp_path / "venv"
    subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True, capture_output=True)
    pip = venv / "bin" / "pip"
    binexe = venv / "bin" / "mdagent"
    subprocess.run([str(pip), "install", str(wheel)], check=True, capture_output=True)

    # 3) Smoke: --version
    r = subprocess.run([str(binexe), "--version"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "mdagent" in r.stdout

    # 4) self-test resources --json must report ok=true with non-zero counts.
    r = subprocess.run(
        [str(binexe), "self-test", "resources", "--json"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    payload = json.loads(r.stdout)
    assert payload["ok"] is True, payload
    assert payload["schemas"]["count"] >= 5, payload
    assert payload["schemas"]["loaded_ok"] == payload["schemas"]["count"]
    assert payload["skills"]["count"] >= 3, payload
    assert set(payload["skills"]["names"]) == {"md-prep-structure", "md-run-workflow", "md-visualize"}

    # 5) doctor --json works at minimum mode.
    r = subprocess.run(
        [str(binexe), "doctor", "--json", "--min-version", "0.1.0"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    doc_payload = json.loads(r.stdout)
    assert doc_payload["ok"] is True
    assert doc_payload["checks"]["min_version"]["status"] == "ok"

    # 6) install-skills dry-run targets a fresh dir without writing.
    out_dir = tmp_path / "target_project"
    out_dir.mkdir()
    r = subprocess.run(
        [str(binexe), "install-skills", "--project", str(out_dir), "--dry-run"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    install_payload = json.loads(r.stdout)
    assert install_payload["dry_run"] is True
    assert install_payload["destination"] == str((out_dir / ".claude" / "skills").resolve())
    assert len(install_payload["written"]) == 3
