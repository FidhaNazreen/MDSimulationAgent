"""StepFingerprint tests — determinism + per-component change detection."""

from __future__ import annotations

from pathlib import Path

import pytest

from mdagent import (
    EMPTY_HASH,
    RunConfig,
    StepFingerprint,
    composite_hash,
    compute_step_fingerprint,
    hash_inputs,
    hash_mode,
    hash_tool_components,
    step_definition,
)


def test_composite_is_deterministic(all_seven_components) -> None:
    c1 = composite_hash(**all_seven_components)
    c2 = composite_hash(**all_seven_components)
    assert c1 == c2
    assert len(c1) == 64


def test_composite_changes_when_any_component_changes(all_seven_components) -> None:
    base = composite_hash(**all_seven_components)
    for key in all_seven_components:
        mutated = dict(all_seven_components)
        mutated[key] = "9" * 64
        assert composite_hash(**mutated) != base, f"component {key} change did not affect composite"


def test_hash_inputs_is_order_independent() -> None:
    a = {"artifact_uri": "local://a", "content_hash": "a" * 64}
    b = {"artifact_uri": "local://b", "content_hash": "b" * 64}
    assert hash_inputs([a, b]) == hash_inputs([b, a])


def test_hash_inputs_differs_when_content_hash_changes() -> None:
    a = {"artifact_uri": "local://a", "content_hash": "a" * 64}
    a2 = {"artifact_uri": "local://a", "content_hash": "9" * 64}
    assert hash_inputs([a]) != hash_inputs([a2])


def test_hash_inputs_ignores_role_field() -> None:
    a = {"artifact_uri": "local://a", "content_hash": "a" * 64, "role": "cleaned_pdb"}
    a_no_role = {"artifact_uri": "local://a", "content_hash": "a" * 64}
    assert hash_inputs([a]) == hash_inputs([a_no_role])


def test_hash_mode_distinguishes_modes() -> None:
    h1 = hash_mode("tutorial_reproduction", "interactive")
    h2 = hash_mode("tutorial_reproduction", "noninteractive_defaults")
    h3 = hash_mode("general_md_prep", "interactive")
    assert len({h1, h2, h3}) == 3


# ---- compute_step_fingerprint end-to-end -------------------------------


def _resolved_tools_for(step_id: str) -> dict[str, str]:
    sdef = step_definition(step_id)
    return {c: f"resolved-{c}-v1" for c in sdef.get("tool_components", [])}


@pytest.fixture
def topology_inputs() -> list[dict[str, str]]:
    return [{"artifact_uri": "local://step_03/working.pdb", "content_hash": "1" * 64}]


def test_compute_step_fingerprint_validates_against_schema(lysozyme_run_config, topology_inputs) -> None:
    cfg = RunConfig.from_dict(lysozyme_run_config)
    fp = compute_step_fingerprint(
        step_id="step_04_topology",
        run_config=cfg,
        inputs=topology_inputs,
        profile_hash=EMPTY_HASH,
        schema_hash="9" * 64,
        code_hash="a" * 64,
        resolved_tool_components=_resolved_tools_for("step_04_topology"),
    )
    # write+read round-trip exercises the schema validator
    assert fp.composite != EMPTY_HASH
    assert len(fp.composite) == 64
    assert "force_field" in fp.depends_on_config_fields


def test_compute_step_fingerprint_raises_on_missing_tool_components(
    lysozyme_run_config, topology_inputs
) -> None:
    cfg = RunConfig.from_dict(lysozyme_run_config)
    with pytest.raises(ValueError, match="missing resolved tool components"):
        compute_step_fingerprint(
            step_id="step_04_topology",
            run_config=cfg,
            inputs=topology_inputs,
            profile_hash=EMPTY_HASH,
            schema_hash="9" * 64,
            code_hash="a" * 64,
            resolved_tool_components={},  # missing required ones
        )


def _full_fp(
    lysozyme_run_config, topology_inputs, *, code_hash="a" * 64, schema_hash="9" * 64,
    profile_hash=EMPTY_HASH, tool_overrides=None,
) -> StepFingerprint:
    cfg = RunConfig.from_dict(lysozyme_run_config)
    tools = _resolved_tools_for("step_04_topology")
    if tool_overrides:
        tools.update(tool_overrides)
    return compute_step_fingerprint(
        step_id="step_04_topology",
        run_config=cfg,
        inputs=topology_inputs,
        profile_hash=profile_hash,
        schema_hash=schema_hash,
        code_hash=code_hash,
        resolved_tool_components=tools,
    )


def test_input_change_invalidates_composite(lysozyme_run_config, topology_inputs) -> None:
    fp_a = _full_fp(lysozyme_run_config, topology_inputs)
    other = [{"artifact_uri": "local://step_03/working.pdb", "content_hash": "9" * 64}]
    fp_b = _full_fp(lysozyme_run_config, other)
    assert fp_a.composite != fp_b.composite
    assert fp_a.inputs_hash != fp_b.inputs_hash


def test_parameter_change_invalidates_composite(lysozyme_run_config, topology_inputs) -> None:
    """Change force_field — a topology depends_on_config_field — and composite must change."""
    fp_a = _full_fp(lysozyme_run_config, topology_inputs)
    lysozyme_run_config["force_field"] = "amber99sb-ildn"
    fp_b = _full_fp(lysozyme_run_config, topology_inputs)
    assert fp_a.composite != fp_b.composite
    assert fp_a.parameters_hash != fp_b.parameters_hash


def test_unrelated_parameter_change_does_not_invalidate(lysozyme_run_config, topology_inputs) -> None:
    """visualization.mode is NOT in step_04_topology.depends_on_config_fields → composite unchanged."""
    fp_a = _full_fp(lysozyme_run_config, topology_inputs)
    lysozyme_run_config["visualization"] = {"mode": "default"}
    fp_b = _full_fp(lysozyme_run_config, topology_inputs)
    assert fp_a.composite == fp_b.composite, "visualization change must not invalidate topology"


def test_profile_change_invalidates_composite(lysozyme_run_config, topology_inputs) -> None:
    fp_a = _full_fp(lysozyme_run_config, topology_inputs, profile_hash=EMPTY_HASH)
    fp_b = _full_fp(lysozyme_run_config, topology_inputs, profile_hash="7" * 64)
    assert fp_a.composite != fp_b.composite


def test_mode_change_invalidates_composite(lysozyme_run_config, topology_inputs) -> None:
    fp_a = _full_fp(lysozyme_run_config, topology_inputs)
    lysozyme_run_config["interaction_mode"] = "interactive"
    fp_b = _full_fp(lysozyme_run_config, topology_inputs)
    assert fp_a.composite != fp_b.composite
    assert fp_a.mode_hash != fp_b.mode_hash


def test_tool_change_invalidates_composite(lysozyme_run_config, topology_inputs) -> None:
    fp_a = _full_fp(lysozyme_run_config, topology_inputs)
    fp_b = _full_fp(
        lysozyme_run_config,
        topology_inputs,
        tool_overrides={"tool_versions.gromacs": "resolved-tool_versions.gromacs-v999"},
    )
    assert fp_a.composite != fp_b.composite


def test_schema_change_invalidates_composite(lysozyme_run_config, topology_inputs) -> None:
    fp_a = _full_fp(lysozyme_run_config, topology_inputs, schema_hash="9" * 64)
    fp_b = _full_fp(lysozyme_run_config, topology_inputs, schema_hash="8" * 64)
    assert fp_a.composite != fp_b.composite


def test_code_change_invalidates_composite(lysozyme_run_config, topology_inputs) -> None:
    fp_a = _full_fp(lysozyme_run_config, topology_inputs, code_hash="a" * 64)
    fp_b = _full_fp(lysozyme_run_config, topology_inputs, code_hash="b" * 64)
    assert fp_a.composite != fp_b.composite


def test_fingerprint_round_trip(tmp_path: Path, lysozyme_run_config, topology_inputs) -> None:
    fp = _full_fp(lysozyme_run_config, topology_inputs)
    path = tmp_path / "fp.json"
    fp.write(path)
    loaded = StepFingerprint.read(path)
    assert loaded.composite == fp.composite
    assert loaded.parameters_hash == fp.parameters_hash
    assert loaded.depends_on_config_fields == fp.depends_on_config_fields
