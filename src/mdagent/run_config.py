"""RunConfig: the canonical run configuration object.

Backed by run_config.schema.json. The class is a thin wrapper around a
validated nested dict so adding a new field requires only a schema edit
plus a step_definitions.json reference — no Python dataclass churn.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .hashing import sha256_json
from .schemas import validate


class RunConfigError(ValueError):
    """Raised for any RunConfig validation or field-resolution failure."""


class RunConfig:
    def __init__(self, data: dict[str, Any]):
        validate(data, "run_config")
        self._data = data

    @classmethod
    def from_file(cls, path: str | Path) -> "RunConfig":
        with open(path) as f:
            data = json.load(f)
        return cls(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RunConfig":
        return cls(data)

    @property
    def data(self) -> dict[str, Any]:
        """Read-only view of the underlying dict. Mutate at your peril."""
        return self._data

    def get_field(self, dotted_path: str) -> Any:
        """Resolve a dotted path like 'box.padding_nm' against the config.

        Returns None when any intermediate key is absent (rather than
        raising), so step parameter projections are stable across configs
        that omit optional fields.
        """
        cur: Any = self._data
        for part in dotted_path.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                return None
        return cur

    def parameters_subset(self, fields: list[str]) -> dict[str, Any]:
        """Project the config onto a sorted list of dotted-path fields.

        The result is a {field_path: value} dict, intended to be hashed
        via sha256_json for the per-step parameters_hash. Fields with
        value None (unset) are still emitted with None — that way,
        *changing* an unset field to a real value invalidates downstream
        steps.
        """
        return {f: self.get_field(f) for f in sorted(fields)}

    def parameters_hash(self, fields: list[str]) -> str:
        return sha256_json(self.parameters_subset(fields))

    def whole_config_hash(self) -> str:
        return sha256_json(self._data)


def validate_field_paths_against_schema(fields: list[str]) -> list[str]:
    """Verify every dotted path resolves to a real field in run_config.schema.json.

    Returns a list of invalid paths (empty list = all valid).
    """
    from .schemas import load_schema

    schema = load_schema("run_config")
    invalid: list[str] = []
    for path in fields:
        if not _path_resolves_in_schema(schema, path):
            invalid.append(path)
    return invalid


def _path_resolves_in_schema(schema: dict[str, Any], path: str) -> bool:
    parts = path.split(".")
    cur = schema
    for part in parts:
        if not isinstance(cur, dict):
            return False
        props = cur.get("properties")
        if not isinstance(props, dict) or part not in props:
            return False
        cur = props[part]
    return True
