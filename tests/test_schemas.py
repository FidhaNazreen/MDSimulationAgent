"""Schema validation tests — valid + invalid examples per schema."""

from __future__ import annotations

import pytest
from jsonschema import ValidationError

from mdagent import (
    SCHEMA_VERSION,
    load_schema,
    load_step_definitions,
    validate,
    validate_field_paths_against_schema,
)


def test_schema_version_constant() -> None:
    assert SCHEMA_VERSION == "0.1.0"


def test_run_config_schema_loads() -> None:
    schema = load_schema("run_config")
    assert schema["title"] == "RunConfig"


def test_minimal_run_config_validates(minimal_run_config) -> None:
    validate(minimal_run_config, "run_config")


def test_lysozyme_run_config_validates(lysozyme_run_config) -> None:
    validate(lysozyme_run_config, "run_config")


def test_run_config_rejects_unknown_field(minimal_run_config) -> None:
    minimal_run_config["bogus_field"] = "x"
    with pytest.raises(ValidationError):
        validate(minimal_run_config, "run_config")


def test_run_config_rejects_bad_ph(lysozyme_run_config) -> None:
    lysozyme_run_config["ph"] = 99.0
    with pytest.raises(ValidationError):
        validate(lysozyme_run_config, "run_config")


def test_run_config_rejects_bad_box_geometry(lysozyme_run_config) -> None:
    lysozyme_run_config["box"]["geometry"] = "triclinic"
    with pytest.raises(ValidationError):
        validate(lysozyme_run_config, "run_config")


def test_run_config_rejects_negative_padding(lysozyme_run_config) -> None:
    lysozyme_run_config["box"]["padding_nm"] = -1.0
    with pytest.raises(ValidationError):
        validate(lysozyme_run_config, "run_config")


def test_run_config_requires_either_pdb_id_or_path(minimal_run_config) -> None:
    minimal_run_config["input"] = {}
    with pytest.raises(ValidationError):
        validate(minimal_run_config, "run_config")


def test_step_definitions_loads_and_orders_correctly() -> None:
    defs = load_step_definitions()
    orders = [s["order"] for s in defs["steps"]]
    assert orders == sorted(orders), "steps must be listed in DAG order"
    ids = [s["step_id"] for s in defs["steps"]]
    assert ids[0] == "step_00_preflight_early"
    assert ids[-1] == "step_08_report"


def test_every_step_depends_on_config_field_resolves_in_schema() -> None:
    """All depends_on_config_fields must point to real fields in run_config.schema.json."""
    defs = load_step_definitions()
    all_fields: list[str] = []
    for step in defs["steps"]:
        all_fields.extend(step["depends_on_config_fields"])
    invalid = validate_field_paths_against_schema(all_fields)
    assert invalid == [], f"unresolved field paths: {invalid}"


def test_step_fingerprint_schema_loads() -> None:
    schema = load_schema("step_fingerprint")
    assert schema["title"] == "StepFingerprint"


def test_step_report_schema_loads() -> None:
    schema = load_schema("step_report")
    assert schema["title"] == "StepReport"


def test_step_index_schema_loads() -> None:
    schema = load_schema("step_index")
    assert schema["title"] == "RunIndex"
