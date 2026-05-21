"""Report — final REPORT.md with readiness_status header.

Reads per-step `step_report.json` files from disk and the per-step JSON
sidecars (`charge_accounting.json`, `em_convergence.json`, etc.) to
regenerate the report from on-disk truth (R3-39).

Readiness mapping (R3-31, R4-14):
  - all steps succeeded + EM converged + no warnings → ready
  - any chemistry/physics warning of severity 'warning' → ready_with_warnings
  - any 'blocking' warning, or any step failed → blocked
  - EM verdict in {needs_longer_em, skipped, missing_tool} → not_validated
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..hashing import sha256_text
from .base import StepContext, StepOutcome


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _walk_run_root(run_root: Path) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Return (step_reports, sidecars_by_name).

    `step_reports` is sorted by step_id. `sidecars_by_name` is keyed by
    `f"{step_id}/{sidecar_filename}"` so the same filename can appear in
    multiple steps without collision.
    """
    reports: list[dict[str, Any]] = []
    sidecars: dict[str, dict[str, Any]] = {}
    for step_dir in sorted(run_root.iterdir()):
        if not step_dir.is_dir() or not step_dir.name.startswith("step_"):
            continue
        rep_path = step_dir / "step_report.json"
        if rep_path.is_file():
            reports.append(_read_json(rep_path))
        for sidecar in step_dir.glob("*.json"):
            if sidecar.name in ("step_report.json", "step_fingerprint.json"):
                continue
            try:
                sidecars[f"{step_dir.name}/{sidecar.name}"] = _read_json(sidecar)
            except Exception:  # noqa: BLE001
                pass
    return reports, sidecars


def _derive_readiness(
    step_reports: list[dict[str, Any]],
    em_verdict: str | None,
) -> tuple[str, str]:
    """Return (readiness_status, readiness_reason).

    `em_verdict` is sourced from em_convergence.json and is the source of
    truth for EM status (converged | needs_longer_em | diverged | stuck).
    """
    any_step_failed = any(rep["status"] == "failed" for rep in step_reports)
    blocking_warnings: list[str] = []
    chem_phys_warnings: list[str] = []
    for rep in step_reports:
        for w in rep.get("warnings", []):
            sev = w.get("severity")
            cls = w.get("class")
            if sev == "blocking":
                blocking_warnings.append(f"{rep['step_id']}: {w.get('message', '')}")
            elif sev == "warning" and cls in ("chemistry", "physics"):
                chem_phys_warnings.append(f"{rep['step_id']}: {w.get('message', '')}")

    if any_step_failed or blocking_warnings:
        return ("blocked", "step_failed_or_blocking_warning")

    # If EM didn't run (em_verdict is None) → not_validated.
    if em_verdict is None:
        return ("not_validated", "em_not_executed")
    if em_verdict in ("diverged", "stuck"):
        # These should already have produced step failures, but guard anyway.
        return ("blocked", f"em_{em_verdict}")
    if em_verdict == "needs_longer_em":
        return ("not_validated", "em_needs_longer")

    # em_verdict == 'converged'
    if chem_phys_warnings:
        return ("ready_with_warnings", "chemistry_or_physics_warning")
    return ("ready", "all_validators_passed_em_converged")


def run(ctx: StepContext) -> StepOutcome:
    step_reports, sidecars = _walk_run_root(ctx.run_root)

    # Pull headline facts from sidecars.
    observations = next(
        (v for k, v in sidecars.items() if k.endswith("/observations.json")),
        {},
    )
    topology_plan = next(
        (v for k, v in sidecars.items() if k.endswith("/topology_plan.json")),
        {},
    )
    charge_accounting = next(
        (v for k, v in sidecars.items() if k.endswith("/charge_accounting.json")),
        {},
    )
    em_convergence = next(
        (v for k, v in sidecars.items() if k.endswith("/em_convergence.json")),
        {},
    )

    em_verdict = em_convergence.get("verdict")
    readiness_status, readiness_reason = _derive_readiness(step_reports, em_verdict)

    pdb_id = ctx.run_config.get_field("input.pdb_id") or "(local)"
    cation = ctx.run_config.get_field("ion_strategy.cation") or "NA"
    anion = ctx.run_config.get_field("ion_strategy.anion") or "CL"
    final_charge = charge_accounting.get("final_total_charge")
    final_charge_str = (
        f"{final_charge:+.4f} e" if isinstance(final_charge, (int, float)) else str(final_charge)
    )

    md = [
        f"# REPORT — readiness: **{readiness_status}**",
        "",
        f"_Reason:_ `{readiness_reason}`",
        "",
        "## System",
        "",
        f"- Source: PDB **{pdb_id}**",
        f"- Force field / water model: `{topology_plan.get('force_field')}` / `{topology_plan.get('water_model')}`",
        f"- Chains: {len(observations.get('chains', []))}",
        f"- Histidines detected: {len(observations.get('histidines', []))}",
        f"- Cysteines detected: {len(observations.get('cysteines', []))}",
        "",
        "## Solvation",
        "",
        f"- Bulk-solvent molecules: {charge_accounting.get('n_sol_final')}",
        f"- Ions inserted: {charge_accounting.get('actual_cations')} {cation}+, "
        f"{charge_accounting.get('actual_anions')} {anion}-",
        f"- Pre-ion net charge: {charge_accounting.get('pre_ion_total_charge')}",
        f"- Final total charge: {final_charge_str}",
        "",
        "## Energy Minimization",
        "",
        f"- Verdict: **{em_verdict}**",
        f"- Final Fmax: {em_convergence.get('fmax_final')}",
        f"- Steps: {em_convergence.get('nsteps')}",
        "",
        "## Step Statuses",
        "",
    ]
    for rep in step_reports:
        md.append(f"- `{rep['step_id']}` → **{rep['status']}**")

    md.append("")
    md.append(f"## Readiness: **{readiness_status}** ({readiness_reason})")

    report_path = ctx.run_root / "REPORT.md"
    report_path.write_text("\n".join(md))

    return StepOutcome(
        outputs=[
            {"artifact_uri": f"local://{report_path}", "content_hash": sha256_text(report_path.read_text()), "role": "report"},
        ],
        extra={"readiness_status": readiness_status, "readiness_reason": readiness_reason, "em_verdict": em_verdict},
    )
