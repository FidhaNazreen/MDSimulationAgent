"""Starter kit tests.

The fast suite verifies the in-place behaviour of `init-project`. A
wheel-marked test additionally builds the wheel, installs into a clean
venv, materializes the kit there, and (if gmx is present) runs the
smoke pipeline.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


# ---- Fast (in-place) tests ---------------------------------------------


def test_init_project_creates_expected_tree(tmp_path: Path) -> None:
    from mdagent.cli import main
    target = tmp_path / "newproj"
    rc = main(["init-project", str(target)])
    assert rc == 0

    # Assert manifest covers every expected file.
    manifest = json.loads((target / "MANIFEST.json").read_text())
    for entry in manifest["files"]:
        assert (target / entry["path"]).is_file(), f"missing {entry['path']}"

    # Skills installed.
    skills = sorted(p.name for p in (target / ".claude" / "skills").iterdir()
                    if (p / "SKILL.md").is_file())
    assert skills == ["md-prep-structure", "md-run-workflow", "md-visualize"]

    # verify.sh is executable.
    verify = target / "verify.sh"
    assert verify.is_file()
    assert os.access(verify, os.X_OK)

    # The kit's MANIFEST.json was annotated with the materialization metadata.
    assert "materialized_at" in manifest
    assert "materialized_by_mdagent_version" in manifest

    # Skill-install manifest was written too.
    install_manifest = json.loads((target / ".claude" / "skills" / ".mdagent-install.json").read_text())
    assert sorted(install_manifest["managed_skills"]) == ["md-prep-structure", "md-run-workflow", "md-visualize"]


def test_init_project_refuses_non_empty_without_force(tmp_path: Path) -> None:
    from mdagent.cli import main
    target = tmp_path / "newproj"
    target.mkdir()
    (target / "preexisting.txt").write_text("don't clobber me")
    rc = main(["init-project", str(target)])
    assert rc != 0  # refused
    # Pre-existing file untouched.
    assert (target / "preexisting.txt").read_text() == "don't clobber me"
    # Kit files NOT materialized.
    assert not (target / "MANIFEST.json").exists()


def test_init_project_force_overwrites_kit_only(tmp_path: Path) -> None:
    from mdagent.cli import main
    target = tmp_path / "newproj"
    target.mkdir()
    # User file unrelated to the kit.
    (target / "my_notes.txt").write_text("keep me please")
    # Pre-existing file with a kit-managed name (should get overwritten).
    target_readme = target / "README.md"
    target_readme.write_text("(old content)")

    rc = main(["init-project", "--force", str(target)])
    assert rc == 0
    assert (target / "my_notes.txt").read_text() == "keep me please"  # untouched
    assert "(old content)" not in target_readme.read_text()  # overwritten


def test_init_project_no_install_skills_flag(tmp_path: Path) -> None:
    from mdagent.cli import main
    target = tmp_path / "newproj"
    rc = main(["init-project", "--no-install-skills", str(target)])
    assert rc == 0
    # Kit files present...
    assert (target / "MANIFEST.json").exists()
    # ...but .claude/skills/ was NOT populated.
    assert not (target / ".claude").exists()


def test_install_skills_force_removes_stale_dirs(tmp_path: Path) -> None:
    from mdagent.cli import main
    # First install creates the manifest + skill dirs.
    main(["install-skills", "--project", str(tmp_path)])
    skills_root = tmp_path / ".claude" / "skills"

    # Simulate a "stale" managed skill leftover from an older mdagent version.
    stale = skills_root / "md-stale-skill"
    stale.mkdir()
    (stale / "SKILL.md").write_text("---\nname: md-stale-skill\n---\n")
    # Add it to the manifest so --force will pick it up.
    install_manifest_path = skills_root / ".mdagent-install.json"
    m = json.loads(install_manifest_path.read_text())
    m["managed_skills"].append("md-stale-skill")
    install_manifest_path.write_text(json.dumps(m))

    # Also add a user-owned skill that should NOT be removed.
    user_skill = skills_root / "user-own-skill"
    user_skill.mkdir()
    (user_skill / "SKILL.md").write_text("---\nname: user-own-skill\n---\n")

    # --force re-install: stale dir removed, user-owned dir preserved.
    rc = main(["install-skills", "--project", str(tmp_path), "--force"])
    assert rc == 0
    assert not stale.exists(), "--force should have removed the stale managed skill"
    assert user_skill.exists(), "--force must not touch user-owned sibling skills"


def test_relative_structure_path_resolves_against_config_dir(tmp_path: Path) -> None:
    """RunConfig.from_file should resolve a relative structure_path
    against the config file's directory, not against cwd."""
    from mdagent import RunConfig

    cfg_dir = tmp_path / "configs"
    struct_dir = tmp_path / "structures"
    cfg_dir.mkdir()
    struct_dir.mkdir()
    pdb = struct_dir / "x.pdb"
    pdb.write_text("ATOM  1  N   ALA A   1       0.000   0.000   0.000  1.00  0.00           N\n")
    cfg_path = cfg_dir / "x.json"
    cfg_path.write_text(json.dumps({
        "schema_version": "0.1.0",
        "pipeline_mode": "tutorial_reproduction",
        "interaction_mode": "noninteractive_defaults",
        "input": {"structure_path": "../structures/x.pdb"},
    }))

    # Run from a totally different cwd to prove the resolution.
    old_cwd = os.getcwd()
    try:
        os.chdir("/")
        cfg = RunConfig.from_file(cfg_path)
        resolved = cfg.get_field("input.structure_path")
        assert Path(resolved).is_absolute(), resolved
        assert Path(resolved).is_file(), resolved
    finally:
        os.chdir(old_cwd)


# ---- Wheel-installed smoke test ----------------------------------------


@pytest.mark.wheel
@pytest.mark.skipif(shutil.which("uv") is None, reason="uv not installed")
def test_starter_kit_init_and_smoke_from_wheel(tmp_path: Path) -> None:
    """Build the wheel, install in a fresh venv, materialize the kit,
    run verify.sh structural, and (if gmx is present) verify.sh --run-smoke."""
    repo = Path(__file__).resolve().parent.parent

    # Build wheel
    dist = tmp_path / "dist"
    dist.mkdir()
    r = subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(dist)],
        cwd=str(repo), capture_output=True, text=True,
    )
    assert r.returncode == 0, f"uv build failed:\n{r.stderr}"
    wheel = next(dist.glob("mdagent-*.whl"))

    # Fresh venv install
    venv = tmp_path / "venv"
    subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True, capture_output=True)
    bindir = venv / "bin"
    subprocess.run([str(bindir / "pip"), "install", str(wheel)], check=True, capture_output=True)
    mdagent_bin = bindir / "mdagent"

    # Materialize the kit from a directory that has NO MDSimulationAgent checkout.
    work = tmp_path / "newproj"
    r = subprocess.run([str(mdagent_bin), "init-project", str(work)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr

    # Assert manifest + every expected file.
    manifest = json.loads((work / "MANIFEST.json").read_text())
    for entry in manifest["files"]:
        assert (work / entry["path"]).is_file(), entry["path"]

    # Skills under .claude/skills/
    skills = sorted(p.name for p in (work / ".claude" / "skills").iterdir() if (p / "SKILL.md").is_file())
    assert skills == ["md-prep-structure", "md-run-workflow", "md-visualize"]

    # Run verify.sh (structural mode). Need mdagent on PATH for the script.
    env = os.environ.copy()
    env["PATH"] = f"{bindir}:{env.get('PATH', '')}"
    r = subprocess.run([str(work / "verify.sh")], cwd=str(work), env=env, capture_output=True, text=True)
    assert r.returncode == 0, f"verify.sh structural failed:\n{r.stdout}\n{r.stderr}"
    assert "starter kit verified" in r.stdout

    # Re-init refuses without --force.
    r = subprocess.run([str(mdagent_bin), "init-project", str(work)], capture_output=True, text=True)
    assert r.returncode != 0

    # --force succeeds.
    r = subprocess.run([str(mdagent_bin), "init-project", "--force", str(work)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


@pytest.mark.slow
@pytest.mark.skipif(shutil.which("gmx") is None, reason="gmx not installed; smoke needs GROMACS")
def test_starter_kit_run_smoke_succeeds(tmp_path: Path) -> None:
    """End-to-end smoke run from a materialized starter kit (no wheel involved).
    Uses the editable install."""
    from mdagent.cli import main
    target = tmp_path / "newproj"
    rc = main(["init-project", str(target)])
    assert rc == 0

    # Invoke verify.sh --run-smoke. We need `mdagent` to be on PATH; in tests
    # we use the venv's bin.
    venv_bin = Path(sys.executable).parent
    env = os.environ.copy()
    env["PATH"] = f"{venv_bin}:{env.get('PATH', '')}"
    r = subprocess.run([str(target / "verify.sh"), "--run-smoke"],
                       cwd=str(target), env=env, capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, f"smoke failed:\n{r.stdout}\n{r.stderr}"
    report = (target / "runs" / "smoke" / "REPORT.md").read_text()
    assert "readiness: **ready**" in report
