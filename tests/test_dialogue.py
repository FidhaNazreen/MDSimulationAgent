"""DialogueRunner tests — exercises the PTY loop against a mock interactive process."""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from mdagent.dialogue import (
    DialoguePlan,
    DialogueRunner,
    NonZeroExitError,
    Prompt,
    PromptKind,
    PromptMismatchError,
    PromptRecognizer,
    StaticPlan,
    UnexpectedPromptError,
)
from mdagent.dialogue.types import DialogueTimeoutError


MOCK_SCRIPT = Path(__file__).parent / "fixtures" / "mock_interactive.py"


# ---- Mock recognizer ---------------------------------------------------

_FF_RE = re.compile(r"Select the Force Field:.*?Choice:\s*$", re.DOTALL)
_HIS_RE = re.compile(
    r"Histidine HIS\s+(?P<resid>\d+)\s+chain\s+(?P<chain>\S+)\s+choice\s+\[[^\]]*\]:\s*$",
    re.DOTALL,
)
_YN_RE = re.compile(r"\(y/n\):\s*$", re.DOTALL)


@dataclass
class MockRecognizer:
    binary: str = "mock_interactive"
    version: str = "test"

    def recognize(self, buffer: str) -> Prompt | None:
        if _FF_RE.search(buffer):
            return Prompt(kind=PromptKind.SELECT_FF, raw_text=buffer[-300:], options={"0": "A", "1": "B"})
        m = _HIS_RE.search(buffer)
        if m:
            return Prompt(
                kind=PromptKind.HIS_CHOICE,
                raw_text=buffer[-300:],
                options={"0": "HID", "1": "HIE", "2": "HIP"},
                context={"resid": int(m.group("resid")), "chain": m.group("chain")},
            )
        if _YN_RE.search(buffer):
            return Prompt(kind=PromptKind.YN_GENERIC, raw_text=buffer[-200:], options={"y": "yes", "n": "no"})
        return None


# ---- Scenario helpers --------------------------------------------------


def _write_scenario(tmp_path: Path, scenario: dict[str, Any]) -> Path:
    p = tmp_path / "scenario.json"
    p.write_text(json.dumps(scenario))
    return p


def _argv(scenario_path: Path) -> list[str]:
    return [sys.executable, str(MOCK_SCRIPT), "--scenario", str(scenario_path)]


# ---- Happy path --------------------------------------------------------


def test_runner_happy_path(tmp_path: Path) -> None:
    scenario = {
        "exit_status": 0,
        "steps": [
            {"prompt": "Select the Force Field:\n0: A\n1: B\nChoice: ", "validate_answer": ["0", "1"]},
            {"prompt": "Histidine HIS 15 chain A choice [0=HID,1=HIE,2=HIP]: ", "validate_answer": ["0", "1", "2"]},
        ],
    }
    sp = _write_scenario(tmp_path, scenario)
    plan = StaticPlan()
    plan.add_answer(PromptKind.SELECT_FF, "1", plan_field="force_field")
    plan.add_answer(PromptKind.HIS_CHOICE, "1", plan_field="protonation.HIS.15.A")

    runner = DialogueRunner(MockRecognizer(), read_timeout_s=10.0)
    result, diag = runner.run(_argv(sp), cwd=tmp_path, plan=plan)

    assert result.ok
    assert [e.prompt.kind for e in result.exchanges] == [PromptKind.SELECT_FF, PromptKind.HIS_CHOICE]
    assert [e.answer for e in result.exchanges] == ["1", "1"]
    assert all(e.answer_source == "plan" for e in result.exchanges)
    assert "[mock] done" in result.raw_transcript
    assert diag.discoveries == []


# ---- Context-keyed plan ------------------------------------------------


def test_runner_context_keyed_plan(tmp_path: Path) -> None:
    scenario = {
        "exit_status": 0,
        "steps": [
            {"prompt": "Histidine HIS 15 chain A choice [0=HID,1=HIE,2=HIP]: ", "validate_answer": ["0", "1", "2"]},
            {"prompt": "Histidine HIS 47 chain A choice [0=HID,1=HIE,2=HIP]: ", "validate_answer": ["0", "1", "2"]},
        ],
    }
    sp = _write_scenario(tmp_path, scenario)
    plan = StaticPlan()
    plan.add_answer(
        PromptKind.HIS_CHOICE, "0", plan_field="protonation.HIS.15.A",
        context={"resid": 15, "chain": "A"}, context_keys=("resid", "chain"),
    )
    plan.add_answer(
        PromptKind.HIS_CHOICE, "2", plan_field="protonation.HIS.47.A",
        context={"resid": 47, "chain": "A"}, context_keys=("resid", "chain"),
    )

    runner = DialogueRunner(MockRecognizer(), read_timeout_s=10.0)
    result, _ = runner.run(_argv(sp), cwd=tmp_path, plan=plan)

    assert [e.answer for e in result.exchanges] == ["0", "2"]
    assert [e.prompt.context["resid"] for e in result.exchanges] == [15, 47]


# ---- Policy default fallback -------------------------------------------


def test_runner_uses_policy_default_when_plan_silent(tmp_path: Path) -> None:
    scenario = {
        "exit_status": 0,
        "steps": [
            {"prompt": "Select the Force Field:\n0: A\n1: B\nChoice: ", "validate_answer": ["0", "1"]},
        ],
    }
    sp = _write_scenario(tmp_path, scenario)
    plan = StaticPlan()  # empty

    def policy(prompt: Prompt) -> tuple[str, str] | None:
        if prompt.kind == PromptKind.SELECT_FF:
            return ("0", "policy.default.force_field")
        return None

    runner = DialogueRunner(MockRecognizer(), read_timeout_s=10.0)
    result, _ = runner.run(_argv(sp), cwd=tmp_path, plan=plan, policy_default=policy)

    assert result.ok
    assert result.exchanges[0].answer == "0"
    assert result.exchanges[0].answer_source == "policy_default"


# ---- Unexpected prompt -------------------------------------------------


def test_runner_raises_on_unexpected_prompt(tmp_path: Path) -> None:
    scenario = {
        "exit_status": 0,
        "steps": [
            # YN_GENERIC is recognized but our plan has no answer.
            {"prompt": "Continue (y/n): ", "validate_answer": ["y", "n"]},
        ],
    }
    sp = _write_scenario(tmp_path, scenario)
    plan = StaticPlan()  # has no YN answer

    runner = DialogueRunner(MockRecognizer(), read_timeout_s=5.0)
    with pytest.raises(UnexpectedPromptError) as exc:
        runner.run(_argv(sp), cwd=tmp_path, plan=plan)
    assert "yn_generic" in str(exc.value)
    assert exc.value.argv is not None and exc.value.argv[-1].endswith("scenario.json")


def test_runner_raises_on_truly_unrecognized_output(tmp_path: Path) -> None:
    # Use a scenario whose prompt the recognizer doesn't classify at all.
    scenario = {
        "exit_status": 0,
        "steps": [
            {"prompt": "weird and unfamiliar prompt > ", "validate_answer": ["x"]},
        ],
    }
    sp = _write_scenario(tmp_path, scenario)
    runner = DialogueRunner(MockRecognizer(), read_timeout_s=3.0)
    with pytest.raises((UnexpectedPromptError, DialogueTimeoutError)):
        runner.run(_argv(sp), cwd=tmp_path, plan=StaticPlan())


# ---- Discovery mode ----------------------------------------------------


def test_runner_discovery_mode_records_unknown_plan_answers(tmp_path: Path) -> None:
    """In discovery mode, a recognized prompt with no plan answer logs a discovery and sends empty."""
    scenario = {
        "exit_status": 0,
        "steps": [
            # Use FF prompt which recognizer matches; plan is empty.
            # mock_interactive will reject the empty answer (not in {"0","1"}),
            # so we expect NonZeroExitError after one discovery is logged.
            {"prompt": "Select the Force Field:\n0: A\n1: B\nChoice: ", "validate_answer": ["0", "1"]},
        ],
    }
    sp = _write_scenario(tmp_path, scenario)
    runner = DialogueRunner(MockRecognizer(), read_timeout_s=5.0)
    with pytest.raises(NonZeroExitError):
        runner.run(_argv(sp), cwd=tmp_path, plan=StaticPlan(), mode="discovery")


# ---- Non-zero exit -----------------------------------------------------


def test_runner_raises_on_nonzero_exit(tmp_path: Path) -> None:
    scenario = {
        "exit_status": 5,
        "steps": [
            {"prompt": "Select the Force Field:\n0: A\n1: B\nChoice: ", "validate_answer": ["0", "1"]},
        ],
    }
    sp = _write_scenario(tmp_path, scenario)
    plan = StaticPlan()
    plan.add_answer(PromptKind.SELECT_FF, "0", plan_field="force_field")

    runner = DialogueRunner(MockRecognizer(), read_timeout_s=5.0)
    with pytest.raises(NonZeroExitError) as exc:
        runner.run(_argv(sp), cwd=tmp_path, plan=plan)
    assert exc.value.exit_status == 5
