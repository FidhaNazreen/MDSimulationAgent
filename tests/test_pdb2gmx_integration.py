"""Integration test: drive real `gmx pdb2gmx` end-to-end via DialogueRunner.

Skipped when `gmx` is not on PATH so the suite stays green for contributors
without GROMACS installed.

Pins to the brew-bottled `gmx 2026.2` for now. Tutorial reference is
GROMACS 2024.3 per the architecture; this test exists to validate the
DialogueRunner mechanics against a *real* `pdb2gmx`, not to assert
tutorial-counts equivalence.
"""

from __future__ import annotations

import shutil
import subprocess
import urllib.request
from pathlib import Path
from textwrap import dedent

import pytest

from mdagent.dialogue import (
    DialogueRunner,
    Pdb2GmxPromptRecognizer,
    StaticPlan,
)
from mdagent.dialogue.types import Prompt, PromptKind


pytestmark = pytest.mark.skipif(
    shutil.which("gmx") is None,
    reason="GROMACS not installed on PATH",
)

LYSOZYME_URL = "https://files.rcsb.org/download/1AKI.pdb"


@pytest.fixture(scope="module")
def lysozyme_pdb(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Fetch 1AKI.pdb once per module; strip HETATM lines (crystal waters)."""
    d = tmp_path_factory.mktemp("lysozyme")
    raw_path = d / "1aki.pdb"
    clean_path = d / "1aki_clean.pdb"
    try:
        with urllib.request.urlopen(LYSOZYME_URL, timeout=30) as resp:
            raw_path.write_bytes(resp.read())
    except (OSError, urllib.error.URLError) as e:
        pytest.skip(f"could not fetch {LYSOZYME_URL}: {e}")
    # Strip crystallographic waters / non-protein atoms.
    raw = raw_path.read_text().splitlines(keepends=True)
    clean = [line for line in raw if not line.startswith("HETATM")]
    clean_path.write_text("".join(clean))
    return clean_path


def _gmx_version() -> str:
    out = subprocess.run(["gmx", "--version"], capture_output=True, text=True)
    for line in out.stdout.splitlines() + out.stderr.splitlines():
        line = line.strip()
        if line.startswith("GROMACS version:"):
            return line.split(":", 1)[1].strip()
    return "unknown"


def test_gmx_is_2026_x():
    """Pin sanity: the slice was probed against 2026.x. Other versions may shift prompt text."""
    v = _gmx_version()
    assert v.startswith("2026"), f"this test was probed against gmx 2026.x; saw {v!r}"


def test_pdb2gmx_termini_drive_end_to_end(tmp_path: Path, lysozyme_pdb: Path) -> None:
    """Drive `gmx pdb2gmx -ter` on 1AKI through DialogueRunner.

    Expectations:
      - Exactly two prompts surface: N-terminus (LYS-1) and C-terminus (LEU-129).
      - Plan answers '0' (default ionized form) for both.
      - pdb2gmx exits 0 and produces system.gro + system.top + posre.itp.
    """
    work = tmp_path
    # pdb2gmx writes outputs relative to cwd, so set cwd to a clean workdir
    # and copy the input PDB inside.
    pdb = work / "1aki_clean.pdb"
    pdb.write_bytes(lysozyme_pdb.read_bytes())

    plan = StaticPlan()
    plan.add_answer(PromptKind.TER_N_CHOICE, "0", plan_field="termini.n_term")
    plan.add_answer(PromptKind.TER_C_CHOICE, "0", plan_field="termini.c_term")

    recognizer = Pdb2GmxPromptRecognizer()
    runner = DialogueRunner(recognizer, read_timeout_s=60.0, idle_after_answer_s=0.2)

    result, diag = runner.run(
        [
            "gmx",
            "pdb2gmx",
            "-f", str(pdb),
            "-o", "system.gro",
            "-p", "system.top",
            "-i", "posre.itp",
            "-ff", "oplsaa",
            "-water", "spc",
            "-ignh",
            "-ter",
        ],
        cwd=work,
        plan=plan,
    )

    assert result.ok, f"pdb2gmx exited {result.exit_status}"
    assert (work / "system.gro").is_file()
    assert (work / "system.top").is_file()
    assert (work / "posre.itp").is_file()

    kinds = [e.prompt.kind for e in result.exchanges]
    assert kinds == [PromptKind.TER_N_CHOICE, PromptKind.TER_C_CHOICE]
    n_term = result.exchanges[0]
    c_term = result.exchanges[1]
    assert n_term.prompt.context == {"residue": "LYS", "resid": 1}
    assert c_term.prompt.context == {"residue": "LEU", "resid": 129}
    assert n_term.answer == "0"
    assert c_term.answer == "0"
    assert n_term.answer_source == "plan"
    assert diag.discoveries == []


def test_pdb2gmx_topology_has_expected_marker(tmp_path: Path, lysozyme_pdb: Path) -> None:
    """Sanity-check the generated topology is OPLS-AA + SPC."""
    work = tmp_path
    pdb = work / "1aki_clean.pdb"
    pdb.write_bytes(lysozyme_pdb.read_bytes())

    plan = StaticPlan()
    plan.add_answer(PromptKind.TER_N_CHOICE, "0", plan_field="termini.n_term")
    plan.add_answer(PromptKind.TER_C_CHOICE, "0", plan_field="termini.c_term")

    runner = DialogueRunner(Pdb2GmxPromptRecognizer(), read_timeout_s=60.0, idle_after_answer_s=0.2)
    runner.run(
        ["gmx", "pdb2gmx", "-f", str(pdb), "-o", "system.gro", "-p", "system.top",
         "-i", "posre.itp", "-ff", "oplsaa", "-water", "spc", "-ignh", "-ter"],
        cwd=work,
        plan=plan,
    )

    top = (work / "system.top").read_text()
    assert "oplsaa.ff/forcefield.itp" in top
    assert "spc.itp" in top.lower() or "spce.itp" in top.lower() or "tip3p.itp" not in top.lower()
