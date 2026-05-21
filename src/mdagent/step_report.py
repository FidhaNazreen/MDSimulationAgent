"""StepReport: per-step immutable record of inputs, outputs, executor calls, warnings."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .schemas import SCHEMA_VERSION, validate


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass
class ArtifactRef:
    artifact_uri: str
    content_hash: str
    role: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"artifact_uri": self.artifact_uri, "content_hash": self.content_hash}
        if self.role is not None:
            d["role"] = self.role
        return d


@dataclass
class ExecutorCall:
    argv: list[str]
    exit_status: int
    wall_time_s: float
    cwd: str | None = None
    env_resolved: dict[str, str] | None = None
    stdout_path: str | None = None
    stderr_path: str | None = None
    scheduler_metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"argv": list(self.argv), "exit_status": self.exit_status, "wall_time_s": self.wall_time_s}
        if self.cwd is not None:
            d["cwd"] = self.cwd
        if self.env_resolved is not None:
            d["env_resolved"] = dict(self.env_resolved)
        if self.stdout_path is not None:
            d["stdout_path"] = self.stdout_path
        if self.stderr_path is not None:
            d["stderr_path"] = self.stderr_path
        if self.scheduler_metadata is not None:
            d["scheduler_metadata"] = dict(self.scheduler_metadata)
        return d


@dataclass
class Warning_:
    cls: str
    severity: str
    message: str
    context: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"class": self.cls, "severity": self.severity, "message": self.message}
        if self.context is not None:
            d["context"] = dict(self.context)
        return d


@dataclass
class FailureReason:
    code: str
    message: str
    context: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.context is not None:
            d["context"] = dict(self.context)
        return d


@dataclass
class StepReport:
    step_id: str
    attempt: int
    status: str
    started_at: str = field(default_factory=utc_now_iso)
    ended_at: str | None = None
    inputs: list[ArtifactRef] = field(default_factory=list)
    outputs: list[ArtifactRef] = field(default_factory=list)
    executor_calls: list[ExecutorCall] = field(default_factory=list)
    warnings: list[Warning_] = field(default_factory=list)
    failure_reason: FailureReason | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "step_id": self.step_id,
            "attempt": self.attempt,
            "status": self.status,
            "started_at": self.started_at,
            "inputs": [a.to_dict() for a in self.inputs],
            "outputs": [a.to_dict() for a in self.outputs],
            "executor_calls": [c.to_dict() for c in self.executor_calls],
        }
        if self.ended_at is not None:
            d["ended_at"] = self.ended_at
        if self.warnings:
            d["warnings"] = [w.to_dict() for w in self.warnings]
        if self.failure_reason is not None:
            d["failure_reason"] = self.failure_reason.to_dict()
        return d

    def write(self, path: str | Path) -> None:
        """Validate and atomically write the report. Temp+rename within the same directory."""
        data = self.to_dict()
        validate(data, "step_report")
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=".step_report-", suffix=".json", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=2, sort_keys=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_name, path)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    @classmethod
    def read(cls, path: str | Path) -> dict[str, Any]:
        """Load and validate a step report from disk. Returns the validated dict.

        (We return the dict rather than reconstructing the dataclass because
        reports are read-only after creation; the dict view is sufficient for
        invalidation logic and report rendering.)
        """
        with open(path) as f:
            data = json.load(f)
        validate(data, "step_report")
        return data
