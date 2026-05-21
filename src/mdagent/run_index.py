"""RunIndex: the single mutable index.json at a run root.

Holds step ordering, status, fingerprint composites, and artifact roles.
Written exclusively via temp+atomic-rename. Protected by an fcntl run-lock.

The invalidation walker compares each succeeded step's current composite
against the recorded composite and marks mismatches (plus all DAG
descendants) as 'invalidated'. The orchestrator then resumes at the first
non-succeeded step.
"""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .schemas import SCHEMA_VERSION, load_step_definitions, validate

VALID_STATES = {"planned", "running", "succeeded", "failed", "skipped", "invalidated"}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass
class IndexStep:
    step_id: str
    order: int
    status: str
    current_attempt: int | None = None
    step_report_uri: str | None = None
    step_fingerprint_uri: str | None = None
    fingerprint_composite: str | None = None
    artifacts: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"step_id": self.step_id, "order": self.order, "status": self.status}
        if self.current_attempt is not None:
            d["current_attempt"] = self.current_attempt
        if self.step_report_uri is not None:
            d["step_report_uri"] = self.step_report_uri
        if self.step_fingerprint_uri is not None:
            d["step_fingerprint_uri"] = self.step_fingerprint_uri
        if self.fingerprint_composite is not None:
            d["fingerprint_composite"] = self.fingerprint_composite
        if self.artifacts:
            d["artifacts"] = [dict(a) for a in self.artifacts]
        return d


class RunLockError(RuntimeError):
    """Failed to acquire (or detected an unexpected) run lock."""


class RunIndex:
    """In-memory model of a run's index.json. Persist via .write()."""

    def __init__(
        self,
        run_id: str,
        steps: list[IndexStep],
        run_config_hash: str | None = None,
        created_at: str | None = None,
        updated_at: str | None = None,
        lock_holder_pid: int | None = None,
    ):
        self.run_id = run_id
        self.steps = sorted(steps, key=lambda s: s.order)
        self.run_config_hash = run_config_hash
        self.created_at = created_at or utc_now_iso()
        self.updated_at = updated_at
        self.lock_holder_pid = lock_holder_pid

    @classmethod
    def initialize(cls, run_id: str, run_config_hash: str) -> "RunIndex":
        """Build a fresh RunIndex from step_definitions.json."""
        defs = load_step_definitions()
        steps = [
            IndexStep(step_id=s["step_id"], order=s["order"], status="planned")
            for s in defs["steps"]
        ]
        return cls(run_id=run_id, steps=steps, run_config_hash=run_config_hash)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "run_id": self.run_id,
            "created_at": self.created_at,
            "steps": [s.to_dict() for s in self.steps],
        }
        if self.updated_at is not None:
            d["updated_at"] = self.updated_at
        if self.run_config_hash is not None:
            d["run_config_hash"] = self.run_config_hash
        if self.lock_holder_pid is not None:
            d["lock_holder_pid"] = self.lock_holder_pid
        return d

    def write(self, path: str | Path) -> None:
        self.updated_at = utc_now_iso()
        data = self.to_dict()
        validate(data, "step_index")
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=".index-", suffix=".json", dir=str(path.parent))
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
    def read(cls, path: str | Path) -> "RunIndex":
        with open(path) as f:
            data = json.load(f)
        validate(data, "step_index")
        return cls(
            run_id=data["run_id"],
            steps=[
                IndexStep(
                    step_id=s["step_id"],
                    order=s["order"],
                    status=s["status"],
                    current_attempt=s.get("current_attempt"),
                    step_report_uri=s.get("step_report_uri"),
                    step_fingerprint_uri=s.get("step_fingerprint_uri"),
                    fingerprint_composite=s.get("fingerprint_composite"),
                    artifacts=list(s.get("artifacts", [])),
                )
                for s in data["steps"]
            ],
            run_config_hash=data.get("run_config_hash"),
            created_at=data["created_at"],
            updated_at=data.get("updated_at"),
            lock_holder_pid=data.get("lock_holder_pid"),
        )

    # ---- step lookup / mutation ----------------------------------------

    def step(self, step_id: str) -> IndexStep:
        for s in self.steps:
            if s.step_id == step_id:
                return s
        raise KeyError(f"unknown step_id: {step_id}")

    def set_status(self, step_id: str, status: str) -> None:
        if status not in VALID_STATES:
            raise ValueError(f"invalid status: {status}")
        self.step(step_id).status = status

    def downstream_of(self, step_id: str) -> list[IndexStep]:
        """Return all steps after `step_id` in the linear order."""
        target = self.step(step_id)
        return [s for s in self.steps if s.order > target.order]

    def first_non_succeeded(self) -> IndexStep | None:
        """First step in order that is not 'succeeded'. None if all succeeded."""
        for s in self.steps:
            if s.status != "succeeded":
                return s
        return None

    # ---- invalidation walker -------------------------------------------

    def invalidate_from(self, step_id: str) -> list[str]:
        """Mark `step_id` and all downstream steps as 'invalidated'.

        Returns the list of step_ids that changed state (so the caller can log).
        """
        changed: list[str] = []
        target = self.step(step_id)
        if target.status != "invalidated":
            target.status = "invalidated"
            changed.append(target.step_id)
        for s in self.downstream_of(step_id):
            if s.status != "invalidated":
                s.status = "invalidated"
                changed.append(s.step_id)
        return changed

    def apply_fingerprint_check(
        self, step_id: str, recomputed_composite: str
    ) -> bool:
        """Compare the recorded composite for `step_id` against `recomputed_composite`.

        If they differ (or the step has no recorded composite while it's
        marked 'succeeded'), invalidate the step and its downstream. Returns
        True if invalidation happened.
        """
        s = self.step(step_id)
        if s.status != "succeeded":
            return False
        if s.fingerprint_composite is None or s.fingerprint_composite != recomputed_composite:
            self.invalidate_from(step_id)
            return True
        return False


# ---- run lock -----------------------------------------------------------


@contextmanager
def acquire_run_lock(run_root: str | Path) -> Iterator[int]:
    """Acquire an exclusive fcntl lock on <run_root>/.lock.

    Writes the current PID into the lock file (atomic open + write). The
    context yields the lock file descriptor; the file is unlinked on release.

    Raises RunLockError if the lock is held by another live process.
    """
    run_root = Path(run_root)
    run_root.mkdir(parents=True, exist_ok=True)
    lock_path = run_root / ".lock"
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as e:
        existing_pid = _read_lock_pid(lock_path)
        os.close(fd)
        raise RunLockError(
            f"run lock at {lock_path} held by pid={existing_pid} (alive={_pid_alive(existing_pid)})"
        ) from e
    # Lock acquired; we now own the fd + lock file cleanup.
    try:
        os.ftruncate(fd, 0)
        os.write(fd, str(os.getpid()).encode("ascii"))
        os.fsync(fd)
        yield fd
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
        try:
            os.unlink(lock_path)
        except FileNotFoundError:
            pass


def _read_lock_pid(lock_path: Path) -> int | None:
    try:
        with open(lock_path) as f:
            txt = f.read().strip()
        return int(txt) if txt else None
    except (FileNotFoundError, ValueError):
        return None


def _pid_alive(pid: int | None) -> bool:
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False
    except OSError:
        return False


def recover_stale_running(index: RunIndex) -> list[str]:
    """If any step is in 'running' state but no live PID holds the lock,
    mark it 'failed' with crash-recovery reason. Returns step_ids fixed.

    Caller is expected to be holding the lock itself when calling this.
    """
    fixed: list[str] = []
    if index.lock_holder_pid is None or not _pid_alive(index.lock_holder_pid):
        for s in index.steps:
            if s.status == "running":
                s.status = "failed"
                fixed.append(s.step_id)
    return fixed
