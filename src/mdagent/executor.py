"""Executor abstraction for non-interactive commands.

Interactive processes (like `pdb2gmx`) go through `mdagent.dialogue.DialogueRunner`
which has its own PTY-driven path. This module covers the simpler case: fire a
command, capture stdout/stderr, return a structured result.

Designed so a `RemoteExecutor` (SLURM, cloud) can be added later without
changing call sites.
"""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


@dataclass
class ResourceRequest:
    cpus: int = 1
    mem_gb: float | None = None
    gpu: int = 0
    walltime_s: float | None = None


@dataclass
class Task:
    """A single command to run.

    `argv` and `workdir` are required. `env` is merged on top of the parent
    process env at execution time. `path_map` is the URI→local-path resolution
    for staged inputs (no-op for LocalExecutor; meaningful for RemoteExecutor).
    """

    argv: list[str]
    workdir: str | Path
    env: dict[str, str] = field(default_factory=dict)
    stdin: bytes | None = None
    resources: ResourceRequest = field(default_factory=ResourceRequest)
    container_image: str | None = None
    path_map: dict[str, str] = field(default_factory=dict)


@dataclass
class ExecutionResult:
    exit_status: int
    wall_time_s: float
    host: str
    stdout_path: str | None = None
    stderr_path: str | None = None
    env_resolved: dict[str, str] | None = None
    scheduler_metadata: dict[str, Any] | None = None

    @property
    def ok(self) -> bool:
        return self.exit_status == 0


class Executor(Protocol):
    def run_sync(self, task: Task, timeout: float | None = None) -> ExecutionResult: ...


class LocalExecutor:
    """Subprocess-backed executor for non-interactive commands.

    For interactive commands use DialogueRunner (separate PTY path).
    """

    def __init__(self, default_env_overrides: dict[str, str] | None = None):
        # `LC_ALL=C` belongs here so every executor call gets it for free.
        defaults = {"LC_ALL": "C", "LANG": "C"}
        if default_env_overrides:
            defaults.update(default_env_overrides)
        self._default_env_overrides = defaults

    def run_sync(self, task: Task, timeout: float | None = None) -> ExecutionResult:
        workdir = Path(task.workdir)
        workdir.mkdir(parents=True, exist_ok=True)
        stdout_path = workdir / "stdout.log"
        stderr_path = workdir / "stderr.log"

        env_resolved = os.environ.copy()
        env_resolved.update(self._default_env_overrides)
        env_resolved.update(task.env)

        t0 = time.monotonic()
        with open(stdout_path, "wb") as out, open(stderr_path, "wb") as err:
            proc = subprocess.Popen(
                task.argv,
                cwd=str(workdir),
                env=env_resolved,
                stdin=subprocess.PIPE if task.stdin is not None else subprocess.DEVNULL,
                stdout=out,
                stderr=err,
            )
            try:
                proc.communicate(input=task.stdin, timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
                raise
        wall = time.monotonic() - t0

        return ExecutionResult(
            exit_status=proc.returncode,
            wall_time_s=wall,
            host=os.uname().nodename,
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            env_resolved=env_resolved,
        )
