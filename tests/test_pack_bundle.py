"""Tests for `mdagent pack-bundle`."""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from mdagent.cli import main as cli_main
from mdagent.pack import (
    _template_skill_for_bundle,
    detect_platform,
    materialize_bundle,
)


# ---- Fast unit tests --------------------------------------------------


def test_detect_platform_returns_human_and_pip_tags():
    human, pip_tag = detect_platform()
    assert "-" in human
    assert pip_tag  # non-empty string


def test_template_skill_rewrites_install_hint():
    src = (
        "Install: uv tool install --force git+https://github.com/FidhaNazreen/MDSimulationAgent@v0.1.0\n"
        "And:    uv tool install --force \"mdagent[propka] @ git+https://github.com/FidhaNazreen/MDSimulationAgent@v0.1.0\"\n"
        "Some other text.\n"
    )
    out = _template_skill_for_bundle(src)
    assert "(packed bundle)" in out
    assert "git+https" not in out
    assert "./setup.sh" in out
    assert "Some other text." in out


def test_template_skill_is_idempotent():
    src = "no install hint here\n"
    assert _template_skill_for_bundle(src) == src


# ---- pack-bundle: structural (no vendor) ------------------------------


def test_pack_bundle_creates_expected_tree(tmp_path: Path):
    dest = tmp_path / "bundle"
    rc = cli_main(["pack-bundle", str(dest)])
    assert rc == 0

    # Required files
    assert (dest / "README.md").is_file()
    assert (dest / "setup.sh").is_file()
    assert (dest / "run_simulation.sh").is_file()
    assert (dest / "MANIFEST.json").is_file()
    assert (dest / ".gitignore").is_file()
    assert (dest / "runs" / ".gitkeep").is_file()
    assert (dest / "structures" / "1aki.pdb").is_file()
    assert (dest / "structures" / "README.md").is_file()
    # Skills
    for name in ("md-prep-structure", "md-run-workflow", "md-visualize"):
        assert (dest / ".claude" / "skills" / name / "SKILL.md").is_file()
    # Configs
    assert (dest / "run_configs" / "lysozyme_offline.json").is_file()
    assert (dest / "run_configs" / "lysozyme_rcsb.json").is_file()
    assert (dest / "run_configs" / "propka_pH7.json").is_file()
    assert (dest / "run_configs" / "propka_pH5.json").is_file()

    # Scripts are executable
    assert os.access(dest / "setup.sh", os.X_OK)
    assert os.access(dest / "run_simulation.sh", os.X_OK)


def test_pack_bundle_manifest_records_metadata(tmp_path: Path):
    dest = tmp_path / "bundle"
    cli_main(["pack-bundle", str(dest)])
    manifest = json.loads((dest / "MANIFEST.json").read_text())
    assert manifest["bundle_kind"] == "packed-mdagent-bundle"
    assert manifest["python"] == "3.11"
    assert manifest["platform"]
    assert manifest["pip_platform_tag"]
    assert manifest["includes_vendor"] is False
    assert manifest["includes_propka"] is False
    # Every listed file actually exists and the recorded sha256 matches.
    import hashlib
    for entry in manifest["files"]:
        p = dest / entry["path"]
        assert p.is_file(), entry["path"]
        h = hashlib.sha256(p.read_bytes()).hexdigest()
        assert h == entry["sha256"], f"{entry['path']} hash mismatch"


def test_pack_bundle_refuses_non_empty_without_force(tmp_path: Path):
    dest = tmp_path / "bundle"
    dest.mkdir()
    (dest / "existing.txt").write_text("keep me")
    rc = cli_main(["pack-bundle", str(dest)])
    assert rc != 0
    assert (dest / "existing.txt").read_text() == "keep me"
    assert not (dest / "MANIFEST.json").exists()


def test_pack_bundle_force_overwrites(tmp_path: Path):
    dest = tmp_path / "bundle"
    dest.mkdir()
    (dest / "preexisting.txt").write_text("keep me")
    rc = cli_main(["pack-bundle", "--force", str(dest)])
    assert rc == 0
    # User file untouched.
    assert (dest / "preexisting.txt").read_text() == "keep me"
    # Bundle materialized.
    assert (dest / "MANIFEST.json").is_file()


def test_pack_bundle_skill_install_hint_templated(tmp_path: Path):
    dest = tmp_path / "bundle"
    cli_main(["pack-bundle", str(dest)])
    for skill_dir in (dest / ".claude" / "skills").iterdir():
        if not (skill_dir / "SKILL.md").is_file():
            continue
        text = (skill_dir / "SKILL.md").read_text()
        assert "git+https" not in text, f"{skill_dir.name}: install hint not templated"
        assert "./setup.sh" in text or "packed bundle" in text


def test_pack_bundle_archive_produces_tarball(tmp_path: Path):
    dest = tmp_path / "bundle"
    rc = cli_main(["pack-bundle", "--archive", str(dest)])
    assert rc == 0
    # Archive lands next to the folder, named with platform + py311.
    archives = sorted(tmp_path.glob("bundle-*.tar.gz"))
    assert archives, "expected one tarball"
    archive = archives[0]
    assert "py311" in archive.name
    # Extract into a fresh dir and verify it's complete.
    import tarfile
    extract_into = tmp_path / "verify"
    extract_into.mkdir()
    with tarfile.open(archive) as tf:
        tf.extractall(extract_into)
    assert (extract_into / "bundle" / "MANIFEST.json").is_file()


def test_pack_bundle_run_configs_propka_uses_local_structure(tmp_path: Path):
    """The propka_pH* configs must use ./structures/1aki.pdb so they're
    runnable offline (modulo propka being installed)."""
    dest = tmp_path / "bundle"
    cli_main(["pack-bundle", str(dest)])
    for ph in (5, 7):
        cfg = json.loads((dest / "run_configs" / f"propka_pH{ph}.json").read_text())
        assert cfg["pipeline_mode"] == "general_md_prep"
        assert cfg["protonation_policy"] == "propka"
        assert cfg["ph"] == float(ph)
        assert cfg["input"]["structure_path"] == "./structures/1aki.pdb"


def test_pack_bundle_setup_sh_has_check_only_and_no_curl_default(tmp_path: Path):
    """setup.sh must NOT pipe-install uv by default; --check-only mode exists."""
    dest = tmp_path / "bundle"
    cli_main(["pack-bundle", str(dest)])
    text = (dest / "setup.sh").read_text()
    # --check-only and --auto-install-uv are present
    assert "--check-only" in text
    assert "--auto-install-uv" in text
    # The curl install is gated behind --auto-install-uv (i.e. the curl line
    # appears AFTER the AUTO_INSTALL_UV check, not at top-level).
    assert "AUTO_INSTALL_UV" in text
    # Critical: the install command uses --no-cache --no-index --offline when
    # vendor/ is present (per critique-loop R3-3).
    assert "--no-cache" in text
    assert "--no-index" in text
    assert "--offline" in text


def test_pack_bundle_run_simulation_sh_has_arg_parsing(tmp_path: Path):
    dest = tmp_path / "bundle"
    cli_main(["pack-bundle", str(dest)])
    text = (dest / "run_simulation.sh").read_text()
    assert "--config" in text and "--run-id" in text and "--runs-root" in text
    assert "--help" in text
    # Bash strict mode
    assert "set -euo pipefail" in text


# ---- pack-bundle: end-to-end smoke (slow, gmx-gated) ------------------


@pytest.mark.slow
@pytest.mark.skipif(shutil.which("gmx") is None, reason="gmx not installed")
def test_pack_bundle_end_to_end_runs_md(tmp_path: Path):
    """Pack a bundle, run setup.sh --check-only, then run_simulation.sh —
    full MD pipeline on the bundled lysozyme. Asserts readiness=ready."""
    dest = tmp_path / "bundle"
    cli_main(["pack-bundle", str(dest)])

    # setup.sh --check-only must succeed (no install attempted).
    env = os.environ.copy()
    venv_bin = Path(sys.executable).parent
    env["PATH"] = f"{venv_bin}:{env.get('PATH', '')}"
    r = subprocess.run(
        [str(dest / "setup.sh"), "--check-only"],
        cwd=str(dest), env=env, capture_output=True, text=True,
    )
    assert r.returncode == 0, f"setup.sh --check-only failed:\n{r.stdout}\n{r.stderr}"
    assert "environment OK" in r.stdout

    # run_simulation.sh executes the pipeline.
    r = subprocess.run(
        [str(dest / "run_simulation.sh"), "--run-id", "smoke"],
        cwd=str(dest), env=env, capture_output=True, text=True, timeout=600,
    )
    assert r.returncode == 0, f"run_simulation.sh failed:\n{r.stdout[-2000:]}\n{r.stderr[-2000:]}"
    report = (dest / "runs" / "smoke" / "REPORT.md").read_text()
    assert "readiness: **ready**" in report
