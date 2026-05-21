"""Shared fixtures for the mdagent test suite."""

from __future__ import annotations

from typing import Any

import pytest


@pytest.fixture
def minimal_run_config() -> dict[str, Any]:
    """The smallest run_config that validates against run_config.schema.json."""
    return {
        "schema_version": "0.1.0",
        "pipeline_mode": "tutorial_reproduction",
        "interaction_mode": "noninteractive_defaults",
    }


@pytest.fixture
def lysozyme_run_config() -> dict[str, Any]:
    """A realistic 1AKI lysozyme-tutorial run config."""
    return {
        "schema_version": "0.1.0",
        "pipeline_mode": "tutorial_reproduction",
        "interaction_mode": "noninteractive_defaults",
        "input": {"pdb_id": "1AKI", "biological_assembly": "asymmetric_unit"},
        "force_field": "oplsaa",
        "water_model": "spc",
        "ph": 7.0,
        "protonation_policy": "propka",
        "altloc_policy": "highest_occupancy",
        "water_retention_policy": "strip_all",
        "box": {"geometry": "dodecahedron", "padding_nm": 1.0, "cutoff_nm": 1.0},
        "ion_strategy": {
            "mode": "neutralize_only",
            "cation": "NA",
            "anion": "CL",
            "random_seed": 42,
        },
        "em": {"step_cap": 1000, "fmax_tol_kjmolnm": 1000.0},
        "tool_versions": {"gromacs": "2024.3"},
    }


@pytest.fixture
def all_seven_components() -> dict[str, str]:
    """Synthetic 64-char sha256-hex strings for fingerprint composite tests."""
    return {
        "inputs_hash":     "a" * 64,
        "parameters_hash": "b" * 64,
        "profile_hash":    "c" * 64,
        "mode_hash":       "d" * 64,
        "tool_hash":       "e" * 64,
        "schema_hash":     "f" * 64,
        "code_hash":       "0" * 64,
    }
