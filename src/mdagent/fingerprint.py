"""StepFingerprint: composite hash for resume invalidation.

A fingerprint is computed from seven component hashes. On resume, the
invalidation walker recomputes each succeeded step's composite; if it
differs from the recorded composite, the step and its DAG descendants
are marked 'invalidated' and the run restarts at the first non-succeeded
step.

The component hashes are:
  - inputs_hash     : hash of the step's input artifact set (uri+content_hash)
  - parameters_hash : hash of the RunConfig projection over depends_on_config_fields
  - profile_hash    : hash of the selected profile's content (or empty if none)
  - mode_hash       : hash of (pipeline_mode, interaction_mode)
  - tool_hash       : hash of the step's declared tool_components
  - schema_hash     : hash of the schemas/v0.1.0/ directory contents
  - code_hash       : hash of the source files owned by this step's agent
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .hashing import canonical_json, sha256_concat, sha256_json, sha256_text
from .run_config import RunConfig
from .schemas import SCHEMA_VERSION, load_step_definitions, validate

EMPTY_HASH = "0" * 64  # used when a component is intentionally absent


@dataclass
class StepFingerprint:
    step_id: str
    inputs_hash: str
    parameters_hash: str
    profile_hash: str
    mode_hash: str
    tool_hash: str
    schema_hash: str
    code_hash: str
    composite: str
    depends_on_config_fields: list[str]
    tool_components: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "step_id": self.step_id,
            "inputs_hash": self.inputs_hash,
            "parameters_hash": self.parameters_hash,
            "profile_hash": self.profile_hash,
            "mode_hash": self.mode_hash,
            "tool_hash": self.tool_hash,
            "schema_hash": self.schema_hash,
            "code_hash": self.code_hash,
            "composite": self.composite,
            "depends_on_config_fields": list(self.depends_on_config_fields),
            "tool_components": dict(self.tool_components),
        }

    def write(self, path: str | Path) -> None:
        data = self.to_dict()
        validate(data, "step_fingerprint")
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=".step_fingerprint-", suffix=".json", dir=str(path.parent))
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
    def read(cls, path: str | Path) -> "StepFingerprint":
        with open(path) as f:
            data = json.load(f)
        validate(data, "step_fingerprint")
        return cls(
            step_id=data["step_id"],
            inputs_hash=data["inputs_hash"],
            parameters_hash=data["parameters_hash"],
            profile_hash=data["profile_hash"],
            mode_hash=data["mode_hash"],
            tool_hash=data["tool_hash"],
            schema_hash=data["schema_hash"],
            code_hash=data["code_hash"],
            composite=data["composite"],
            depends_on_config_fields=list(data["depends_on_config_fields"]),
            tool_components=dict(data.get("tool_components", {})),
        )


def composite_hash(
    *,
    inputs_hash: str,
    parameters_hash: str,
    profile_hash: str,
    mode_hash: str,
    tool_hash: str,
    schema_hash: str,
    code_hash: str,
) -> str:
    return sha256_concat(
        inputs_hash,
        parameters_hash,
        profile_hash,
        mode_hash,
        tool_hash,
        schema_hash,
        code_hash,
    )


def hash_inputs(inputs: list[dict[str, Any]]) -> str:
    """Hash an ordered list of input artifact refs.

    Each ref is normalized to {artifact_uri, content_hash} (role is dropped
    so renaming a role doesn't invalidate downstream steps; the artifact's
    content_hash is the real identity).
    """
    normalized = sorted(
        ({"artifact_uri": x["artifact_uri"], "content_hash": x["content_hash"]} for x in inputs),
        key=lambda x: (x["artifact_uri"], x["content_hash"]),
    )
    return sha256_text(canonical_json(normalized))


def hash_mode(pipeline_mode: str, interaction_mode: str) -> str:
    return sha256_json({"pipeline_mode": pipeline_mode, "interaction_mode": interaction_mode})


def hash_tool_components(components: dict[str, str]) -> str:
    """Hash a {component_name: component_hash_or_version} dict.

    Caller is responsible for resolving real component hashes
    (e.g. running `gmx -version`, hashing the FF dir). This function
    just turns the resolved map into a single hash.
    """
    return sha256_json(components)


def step_definition(step_id: str) -> dict[str, Any]:
    """Look up a step's definition (depends_on_config_fields, tool_components, order)."""
    defs = load_step_definitions()
    for step in defs["steps"]:
        if step["step_id"] == step_id:
            return step
    raise KeyError(f"unknown step_id: {step_id}")


def compute_step_fingerprint(
    *,
    step_id: str,
    run_config: RunConfig,
    inputs: list[dict[str, Any]],
    profile_hash: str,
    schema_hash: str,
    code_hash: str,
    resolved_tool_components: dict[str, str],
) -> StepFingerprint:
    """Compose a StepFingerprint from the run config + step's resolved tool components.

    Inputs are already-hashed artifact refs ({artifact_uri, content_hash}).
    profile_hash, schema_hash, code_hash, and the tool component values are
    resolved by the caller (typically the orchestrator) and passed in.
    """
    sdef = step_definition(step_id)
    fields: list[str] = list(sdef["depends_on_config_fields"])
    declared_components: list[str] = list(sdef.get("tool_components", []))

    # Defensive: the resolved components must cover at least the declared
    # ones (extra resolved keys are allowed but logged via 'tool_components'
    # field on the fingerprint for audit).
    missing = [c for c in declared_components if c not in resolved_tool_components]
    if missing:
        raise ValueError(
            f"compute_step_fingerprint({step_id}): missing resolved tool components: {missing}"
        )

    inputs_hash = hash_inputs(inputs)
    parameters_hash = run_config.parameters_hash(fields)
    mode_hash = hash_mode(
        pipeline_mode=run_config.get_field("pipeline_mode"),
        interaction_mode=run_config.get_field("interaction_mode"),
    )
    tool_hash = hash_tool_components(resolved_tool_components)
    composite = composite_hash(
        inputs_hash=inputs_hash,
        parameters_hash=parameters_hash,
        profile_hash=profile_hash,
        mode_hash=mode_hash,
        tool_hash=tool_hash,
        schema_hash=schema_hash,
        code_hash=code_hash,
    )

    return StepFingerprint(
        step_id=step_id,
        inputs_hash=inputs_hash,
        parameters_hash=parameters_hash,
        profile_hash=profile_hash,
        mode_hash=mode_hash,
        tool_hash=tool_hash,
        schema_hash=schema_hash,
        code_hash=code_hash,
        composite=composite,
        depends_on_config_fields=fields,
        tool_components=dict(resolved_tool_components),
    )
