"""Schema loading + validation. Schemas live in schemas/v0.1.0/ relative to the repo root."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import jsonschema

SCHEMA_VERSION = "0.1.0"


def schemas_dir() -> Path:
    """Resolve the packaged schemas/<version>/ dir.

    Works for both editable and standard wheel installs via
    `importlib.resources.files`.
    """
    from ._resources import schemas_dir as _resources_schemas_dir
    return _resources_schemas_dir(SCHEMA_VERSION)


@lru_cache(maxsize=None)
def load_schema(name: str) -> dict[str, Any]:
    """Load a JSON schema by file name (without .schema.json suffix)."""
    path = schemas_dir() / f"{name}.schema.json"
    if not path.is_file():
        raise FileNotFoundError(f"schema not found: {path}")
    with open(path) as f:
        return json.load(f)


@lru_cache(maxsize=None)
def load_step_definitions() -> dict[str, Any]:
    path = schemas_dir() / "step_definitions.json"
    with open(path) as f:
        return json.load(f)


def validate(instance: Any, schema_name: str) -> None:
    """Raise jsonschema.ValidationError if instance doesn't match the schema."""
    schema = load_schema(schema_name)
    jsonschema.validate(instance=instance, schema=schema)
