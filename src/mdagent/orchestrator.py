"""Orchestrator — the v0 golden-path runner.

Runs the nine-step DAG in order, acquiring a run lock, persisting per-step
step_report and step_fingerprint records, and maintaining the run index.
The visualization step is wired but skipped in v0 unless explicitly enabled.

Steps consume artifacts from upstream step outputs via `ctx.inputs`, which
the orchestrator assembles from the index's artifact roles.
"""

from __future__ import annotations

import importlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .fingerprint import EMPTY_HASH, StepFingerprint, compute_step_fingerprint, step_definition
from .hashing import sha256_dir, sha256_source_files
from .provenance import (
    em_tool_components,
    solvation_tool_components,
    stub_components,
    topology_tool_components,
)
from .run_config import RunConfig
from .run_index import IndexStep, RunIndex, acquire_run_lock, recover_stale_running, utc_now_iso
from .schemas import schemas_dir
from .step_report import (
    ArtifactRef,
    ExecutorCall,
    FailureReason,
    StepReport,
    Warning_,
)
from .steps.base import StepContext, StepOutcome

# Which inputs each step expects (by role name) from the upstream pipeline.
_STEP_INPUT_ROLES: dict[str, tuple[str, ...]] = {
    "step_00_preflight_early": (),
    "step_01_structure_ingest": (),
    "step_02_classifier": ("working_pdb",),
    "step_03_structure_prep": ("working_pdb",),
    "step_04_topology": ("working_pdb",),
    "step_05_solvation": ("system_apo_gro", "system_apo_top", "posre"),
    "step_06_em": ("system_ions_gro", "system_ions_top"),
    "step_07_nvt": ("em_gro", "system_ions_top"),
    "step_08_npt": ("nvt_gro", "nvt_cpt", "system_ions_top"),
    "step_09_production": ("npt_gro", "npt_cpt", "system_ions_top"),
    "step_10_analysis": ("production_xtc", "production_tpr"),
    # Visualization can render any prior checkpoint by role; orchestrator
    # feeds in every artifact emitted so far (handled specially inside
    # `run_workflow`).
    "step_11_visualization": (),
    "step_12_report": (),
}

# Which step module to invoke for each step_id. step_00 (Preflight) and
# step_07 (Visualization) are skipped in v0 — preflight is implicit (we
# already error out at config-load time), and visualization is opt-in.
_STEP_MODULE: dict[str, str] = {
    "step_01_structure_ingest": "mdagent.steps.ingest",
    "step_02_classifier": "mdagent.steps.classifier",
    "step_03_structure_prep": "mdagent.steps.prep",
    "step_04_topology": "mdagent.steps.topology",
    "step_05_solvation": "mdagent.steps.solvation",
    "step_06_em": "mdagent.steps.em",
    "step_07_nvt": "mdagent.steps.nvt",
    "step_08_npt": "mdagent.steps.npt",
    "step_09_production": "mdagent.steps.production",
    "step_10_analysis": "mdagent.steps.analysis",
    "step_11_visualization": "mdagent.steps.visualization",
    "step_12_report": "mdagent.steps.report",
}


def _resolved_tool_components(step_id: str, run_config: RunConfig) -> dict[str, str]:
    """Build the resolved tool-components dict for each step.

    Steps that don't need real tool resolution get stub components — stable
    placeholders that don't change unless the agent code does.
    """
    sdef = step_definition(step_id)
    declared = list(sdef.get("tool_components", []))
    ff = run_config.get_field("force_field") or "oplsaa"

    if step_id == "step_04_topology":
        from .hashing import sha256_text
        return topology_tool_components(
            ff_name=ff,
            transcript_catalog_hash=sha256_text("catalog::pdb2gmx@2026.2-v0"),
            dialogue_runner_code_hash=sha256_text("DialogueRunner::v0"),
        )
    if step_id == "step_05_solvation":
        from .hashing import sha256_text
        return solvation_tool_components(
            ff_name=ff,
            water_include_hash=sha256_text(f"water::{run_config.get_field('water_model') or 'spc'}"),
            ion_include_hash=sha256_text("ions::oplsaa-default"),
        )
    if step_id == "step_06_em":
        from .hashing import sha256_text
        from .mdp import EM_MDP_TEMPLATE
        return em_tool_components(
            ff_name=ff,
            em_mdp_template_hash=sha256_text(EM_MDP_TEMPLATE),
        )
    if step_id == "step_07_nvt":
        from .hashing import sha256_text
        from .mdp import NVT_MDP_TEMPLATE
        return {
            "tool_versions.gromacs": sha256_text(_provenance_gmx_version()),
            "ff_dir_recursive_hash": _provenance_ff_dir(ff),
            "nvt_mdp_template_hash": sha256_text(NVT_MDP_TEMPLATE),
        }
    if step_id == "step_08_npt":
        from .hashing import sha256_text
        from .mdp import NPT_MDP_TEMPLATE
        return {
            "tool_versions.gromacs": sha256_text(_provenance_gmx_version()),
            "ff_dir_recursive_hash": _provenance_ff_dir(ff),
            "npt_mdp_template_hash": sha256_text(NPT_MDP_TEMPLATE),
        }
    if step_id == "step_09_production":
        from .hashing import sha256_text
        from .mdp import PRODUCTION_MDP_TEMPLATE
        return {
            "tool_versions.gromacs": sha256_text(_provenance_gmx_version()),
            "ff_dir_recursive_hash": _provenance_ff_dir(ff),
            "production_mdp_template_hash": sha256_text(PRODUCTION_MDP_TEMPLATE),
        }
    return stub_components(declared)


def _provenance_gmx_version() -> str:
    from .provenance import gmx_version_stdout
    return gmx_version_stdout()


def _provenance_ff_dir(ff_name: str) -> str:
    from .provenance import ff_dir_hash
    return ff_dir_hash(ff_name)


def _invalidate_outdated_steps(
    *,
    index: RunIndex,
    run_config: RunConfig,
    schema_hash: str,
    code_hash: str,
) -> dict[str, dict[str, str]]:
    """Walk index in DAG order; for each succeeded step recompute its composite.

    If the composite matches the recorded one, populate `artifacts_by_role`
    with the step's persisted artifacts so downstream resumed steps see them.
    If it mismatches (or the step has no recorded composite), invalidate the
    step and all DAG descendants, and stop scanning (downstream is moot now).

    Returns the populated artifacts_by_role for the loop in run_workflow.
    """
    artifacts_by_role: dict[str, dict[str, str]] = {}
    for s in index.steps:
        if s.status == "skipped":
            continue
        if s.status != "succeeded":
            break
        step_id = s.step_id
        # Read inputs from this step's report — they're needed to recompute
        # inputs_hash deterministically.
        if not s.step_report_uri:
            # No report → cannot verify, conservatively invalidate.
            index.invalidate_from(step_id)
            break
        report_path = Path(s.step_report_uri.removeprefix("local://"))
        if not report_path.is_file():
            index.invalidate_from(step_id)
            break
        try:
            report = json.loads(report_path.read_text())
        except (OSError, json.JSONDecodeError):
            index.invalidate_from(step_id)
            break

        # Skip steps that don't compute fingerprints (preflight / vis / report).
        if step_id not in _STEP_MODULE:
            # Still populate artifacts_by_role from the recorded outputs.
            for art in (s.artifacts or []):
                role = art.get("role")
                if role:
                    artifacts_by_role[role] = dict(art)
            continue
        if step_id in ("step_11_visualization", "step_12_report"):
            for art in (s.artifacts or []):
                role = art.get("role")
                if role:
                    artifacts_by_role[role] = dict(art)
            continue

        inputs = report.get("inputs", [])
        try:
            resolved_tools = _resolved_tool_components(step_id, run_config)
            new_fp = compute_step_fingerprint(
                step_id=step_id,
                run_config=run_config,
                inputs=inputs,
                profile_hash=EMPTY_HASH,
                schema_hash=schema_hash,
                code_hash=code_hash,
                resolved_tool_components=resolved_tools,
            )
        except Exception:  # noqa: BLE001 — any failure → invalidate to be safe
            index.invalidate_from(step_id)
            break

        if s.fingerprint_composite != new_fp.composite:
            index.invalidate_from(step_id)
            break

        # Composite matches — keep as succeeded; surface artifacts.
        for art in (s.artifacts or []):
            role = art.get("role")
            if role:
                artifacts_by_role[role] = dict(art)
    return artifacts_by_role


def _build_step_report(
    *,
    step_id: str,
    attempt: int,
    status: str,
    started_at: str,
    inputs: list[dict[str, str]],
    outcome: StepOutcome,
) -> StepReport:
    return StepReport(
        step_id=step_id,
        attempt=attempt,
        status=status,
        started_at=started_at,
        ended_at=utc_now_iso(),
        inputs=[ArtifactRef(**i) for i in inputs],
        outputs=[ArtifactRef(**o) for o in outcome.outputs],
        executor_calls=[ExecutorCall(**c) for c in outcome.executor_calls],
        warnings=[Warning_(cls=w["class"], severity=w["severity"], message=w["message"], context=w.get("context")) for w in outcome.warnings],
        failure_reason=(FailureReason(**outcome.failure) if outcome.failure else None),
    )


def run_workflow(
    *,
    run_config_path: str | Path,
    runs_root: str | Path,
    run_id: str | None = None,
) -> tuple[Path, RunIndex]:
    """Execute the v0 golden-path workflow.

    Returns `(run_root, index)`. Raises on lock failure or unhandled errors;
    per-step failures are recorded in the index (status='failed') and
    propagated by stopping the run there.
    """
    cfg = RunConfig.from_file(run_config_path)
    runs_root_p = Path(runs_root)
    runs_root_p.mkdir(parents=True, exist_ok=True)

    if run_id is None:
        run_id = f"run-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    run_root = runs_root_p / run_id
    run_root.mkdir(parents=True, exist_ok=True)

    # Save the resolved run_config alongside the run for provenance.
    (run_root / "run_config.json").write_text(
        json.dumps(cfg.data, indent=2, sort_keys=True)
    )

    schema_hash = sha256_dir(schemas_dir())
    from . import (
        dialogue,
        executor,
        fingerprint,
        hashing,
        mdp,
        provenance,
        run_config as rc_mod,
        run_index as ri_mod,
        schemas,
        step_report,
        steps,
    )
    code_files = (
        [Path(m.__file__) for m in (dialogue, executor, fingerprint, hashing, mdp, provenance, rc_mod, ri_mod, schemas, step_report)]
        + [Path(m.__file__) for m in (steps,)]
        + [Path(m.__file__) for m in (
            steps.ingest, steps.classifier, steps.prep, steps.topology,
            steps.solvation, steps.em, steps.nvt, steps.npt, steps.production,
            steps.analysis, steps.visualization, steps.report,
        )]
    )
    code_hash = sha256_source_files([str(p) for p in code_files if p is not None])

    with acquire_run_lock(run_root) as _lock_fd:
        index_path = run_root / "index.json"
        if index_path.is_file():
            # Resume path — load existing index, recover stale state, then
            # walk fingerprints to invalidate steps whose preconditions
            # changed (input hash, config, profile, mode, tool, schema, code).
            index = RunIndex.read(index_path)
            # Config might have changed since the last run — update the
            # recorded hash. Step-level fingerprints catch the actual drift.
            index.run_config_hash = cfg.whole_config_hash()
            index.lock_holder_pid = _read_pid()
            stale_fixed = recover_stale_running(index)
            artifacts_by_role = _invalidate_outdated_steps(
                index=index,
                run_config=cfg,
                schema_hash=schema_hash,
                code_hash=code_hash,
            )
            index.write(index_path)
        else:
            # Fresh run.
            index = RunIndex.initialize(run_id=run_id, run_config_hash=cfg.whole_config_hash())
            index.lock_holder_pid = _read_pid()
            index.write(index_path)
            recover_stale_running(index)
            artifacts_by_role: dict[str, dict[str, str]] = {}

        # Walk steps in DAG order; skip Preflight + Visualization in v0.
        for idx_step in index.steps:
            step_id = idx_step.step_id
            # Resume optimization: a step already in 'succeeded' state has a
            # valid fingerprint (we verified it in _invalidate_outdated_steps).
            # Its artifacts are already in artifacts_by_role. Don't re-run.
            if idx_step.status == "succeeded":
                continue
            # Likewise, leave 'skipped' alone on resume.
            if idx_step.status == "skipped":
                continue

            if step_id == "step_00_preflight_early":
                idx_step.status = "skipped"
                index.write(index_path)
                continue
            if step_id == "step_11_visualization":
                if (cfg.get_field("visualization.mode") or "disabled") == "disabled":
                    idx_step.status = "skipped"
                    index.write(index_path)
                    continue
            if step_id == "step_09_production":
                if cfg.get_field("production.enabled") is False:
                    idx_step.status = "skipped"
                    index.write(index_path)
                    continue
            if step_id == "step_10_analysis":
                # Skip analysis when production didn't run, or when explicitly disabled.
                if cfg.get_field("production.enabled") is False or cfg.get_field("analysis.enabled") is False:
                    idx_step.status = "skipped"
                    index.write(index_path)
                    continue

            mod_path = _STEP_MODULE.get(step_id)
            if mod_path is None:
                idx_step.status = "skipped"
                index.write(index_path)
                continue

            # Assemble inputs for this step from prior outputs by role.
            inputs: list[dict[str, str]] = []
            for role in _STEP_INPUT_ROLES.get(step_id, ()):
                ref = artifacts_by_role.get(role)
                if ref is not None:
                    inputs.append(dict(ref))
            # Visualization wants everything that's been produced so far so
            # it can render any requested checkpoint.
            if step_id == "step_11_visualization":
                checkpoint_roles = {"working_pdb", "system_apo_gro", "system_ions_gro", "em_gro"}
                for role in checkpoint_roles:
                    ref = artifacts_by_role.get(role)
                    if ref is not None:
                        inputs.append(dict(ref))

            step_dir = run_root / step_id
            step_dir.mkdir(parents=True, exist_ok=True)
            ctx = StepContext(
                step_id=step_id,
                run_root=run_root,
                step_dir=step_dir,
                run_config=cfg,
                inputs=inputs,
                attempt=idx_step.current_attempt or 1,
            )

            # On a fresh attempt (first run, or after invalidation/failure),
            # bump the attempt counter so the step report has a unique
            # `attempt` number per retry.
            ctx.attempt = (idx_step.current_attempt or 0) + 1
            idx_step.current_attempt = ctx.attempt
            idx_step.status = "running"
            index.write(index_path)

            started = utc_now_iso()
            mod = importlib.import_module(mod_path)
            outcome: StepOutcome = mod.run(ctx)

            new_status = "succeeded" if outcome.ok else "failed"
            report = _build_step_report(
                step_id=step_id,
                attempt=ctx.attempt,
                status=new_status,
                started_at=started,
                inputs=inputs,
                outcome=outcome,
            )
            report_path = step_dir / "step_report.json"
            report.write(report_path)

            # Fingerprint (only for succeeded steps — fingerprinting a failed
            # step is meaningless for invalidation purposes).
            if outcome.ok:
                resolved_tools = _resolved_tool_components(step_id, cfg)
                fp = compute_step_fingerprint(
                    step_id=step_id,
                    run_config=cfg,
                    inputs=inputs,
                    profile_hash=EMPTY_HASH,
                    schema_hash=schema_hash,
                    code_hash=code_hash,
                    resolved_tool_components=resolved_tools,
                )
                fp_path = step_dir / "step_fingerprint.json"
                fp.write(fp_path)
                idx_step.step_fingerprint_uri = f"local://{fp_path}"
                idx_step.fingerprint_composite = fp.composite

            idx_step.status = new_status
            idx_step.step_report_uri = f"local://{report_path}"
            idx_step.artifacts = list(outcome.outputs)
            index.write(index_path)

            if not outcome.ok:
                # Stop the run on the first failure (v0 has no auto-retry).
                break

            # Register outputs by role for downstream consumption.
            for art in outcome.outputs:
                role = art.get("role")
                if role:
                    artifacts_by_role[role] = art

        return run_root, index


def _read_pid() -> int:
    import os
    return os.getpid()
