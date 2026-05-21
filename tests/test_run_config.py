"""RunConfig tests."""

from __future__ import annotations

import pytest
from jsonschema import ValidationError

from mdagent import RunConfig


def test_construction_validates(minimal_run_config) -> None:
    cfg = RunConfig.from_dict(minimal_run_config)
    assert cfg.data["pipeline_mode"] == "tutorial_reproduction"


def test_construction_rejects_invalid(minimal_run_config) -> None:
    minimal_run_config["pipeline_mode"] = "freeform"
    with pytest.raises(ValidationError):
        RunConfig.from_dict(minimal_run_config)


def test_get_field_dotted_path(lysozyme_run_config) -> None:
    cfg = RunConfig.from_dict(lysozyme_run_config)
    assert cfg.get_field("force_field") == "oplsaa"
    assert cfg.get_field("box.geometry") == "dodecahedron"
    assert cfg.get_field("ion_strategy.random_seed") == 42


def test_get_field_missing_returns_none(minimal_run_config) -> None:
    cfg = RunConfig.from_dict(minimal_run_config)
    assert cfg.get_field("box.padding_nm") is None
    assert cfg.get_field("nonexistent.path") is None


def test_parameters_subset_includes_unset_fields_as_none(minimal_run_config) -> None:
    cfg = RunConfig.from_dict(minimal_run_config)
    sub = cfg.parameters_subset(["force_field", "water_model", "box.padding_nm"])
    assert sub == {"box.padding_nm": None, "force_field": None, "water_model": None}


def test_parameters_subset_is_sorted_for_stable_hashing(lysozyme_run_config) -> None:
    cfg = RunConfig.from_dict(lysozyme_run_config)
    sub = cfg.parameters_subset(["water_model", "force_field", "ph"])
    assert list(sub.keys()) == sorted(sub.keys()) == ["force_field", "ph", "water_model"]


def test_parameters_hash_changes_when_value_changes(lysozyme_run_config) -> None:
    fields = ["force_field", "water_model", "box.padding_nm"]
    cfg1 = RunConfig.from_dict(lysozyme_run_config)
    h1 = cfg1.parameters_hash(fields)
    lysozyme_run_config["box"]["padding_nm"] = 1.5
    cfg2 = RunConfig.from_dict(lysozyme_run_config)
    h2 = cfg2.parameters_hash(fields)
    assert h1 != h2


def test_parameters_hash_unaffected_by_non_listed_fields(lysozyme_run_config) -> None:
    fields = ["force_field", "water_model"]
    cfg1 = RunConfig.from_dict(lysozyme_run_config)
    h1 = cfg1.parameters_hash(fields)
    lysozyme_run_config["box"]["padding_nm"] = 1.5
    cfg2 = RunConfig.from_dict(lysozyme_run_config)
    h2 = cfg2.parameters_hash(fields)
    assert h1 == h2, "fields not in projection must not change parameters_hash"
