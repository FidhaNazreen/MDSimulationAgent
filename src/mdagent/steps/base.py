"""Shared types for step modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..run_config import RunConfig


@dataclass
class StepContext:
    """Everything a step needs to run.

    The orchestrator owns the index and the per-step subdir creation.
    Steps consume `inputs` (artifact refs from upstream step reports) and
    write outputs into `step_dir`.
    """

    step_id: str
    run_root: Path
    step_dir: Path
    run_config: RunConfig
    inputs: list[dict[str, str]] = field(default_factory=list)  # [{artifact_uri, content_hash, role?}]
    attempt: int = 1


@dataclass
class StepOutcome:
    """What the step produced.

    `outputs` is the list of (uri, content_hash, role) refs that downstream
    steps may consume. `warnings` are surfaced into the step report and
    eventually into the final REPORT.md. `failure` is non-None when the
    step failed; the orchestrator translates it to step_report.failure_reason.
    """

    outputs: list[dict[str, str]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    executor_calls: list[dict[str, Any]] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)
    failure: dict[str, Any] | None = None  # {code, message, context?}

    @property
    def ok(self) -> bool:
        return self.failure is None


def find_input(inputs: list[dict[str, str]], role: str) -> dict[str, str] | None:
    for inp in inputs:
        if inp.get("role") == role:
            return inp
    return None
