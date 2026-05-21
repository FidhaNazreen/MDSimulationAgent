"""mdagent — agentic system for GROMACS-based MD simulation workflows."""

__version__ = "0.1.0"

from .schemas import SCHEMA_VERSION, validate, load_schema, load_step_definitions
from .run_config import RunConfig, RunConfigError, validate_field_paths_against_schema
from .step_report import StepReport, ArtifactRef, ExecutorCall, Warning_, FailureReason
from .fingerprint import (
    StepFingerprint,
    compute_step_fingerprint,
    composite_hash,
    hash_inputs,
    hash_mode,
    hash_tool_components,
    step_definition,
    EMPTY_HASH,
)
from .run_index import (
    RunIndex,
    IndexStep,
    RunLockError,
    acquire_run_lock,
    recover_stale_running,
)
from .executor import Task, ExecutionResult, ResourceRequest, LocalExecutor, Executor
from . import dialogue
from . import steps
from .orchestrator import run_workflow

__all__ = [
    "SCHEMA_VERSION",
    "validate",
    "load_schema",
    "load_step_definitions",
    "RunConfig",
    "RunConfigError",
    "validate_field_paths_against_schema",
    "StepReport",
    "ArtifactRef",
    "ExecutorCall",
    "Warning_",
    "FailureReason",
    "StepFingerprint",
    "compute_step_fingerprint",
    "composite_hash",
    "hash_inputs",
    "hash_mode",
    "hash_tool_components",
    "step_definition",
    "EMPTY_HASH",
    "RunIndex",
    "IndexStep",
    "RunLockError",
    "acquire_run_lock",
    "recover_stale_running",
    "Task",
    "ExecutionResult",
    "ResourceRequest",
    "LocalExecutor",
    "Executor",
    "dialogue",
    "steps",
    "run_workflow",
]
