"""Production MD — free dynamics, continuing from NPT.

Set `production.enabled = false` in the config to stop the pipeline
after NPT (useful for quick prep / test runs that don't want long MD).
"""

from __future__ import annotations

from pathlib import Path

from ..mdp import render_production_mdp
from .base import StepContext, StepOutcome, find_input
from ._md_driver import run_phase


def run(ctx: StepContext) -> StepOutcome:
    cfg = ctx.run_config
    enabled = cfg.get_field("production.enabled")
    if enabled is False:
        return StepOutcome(extra={"skipped": True, "reason": "production.enabled=false"})

    nsteps = cfg.get_field("production.nsteps") or 500000
    dt_ps = cfg.get_field("production.dt_ps") or 0.002
    T = cfg.get_field("production.temperature_K") or 300.0
    P = cfg.get_field("production.pressure_bar") or 1.0
    nstxout_compressed = cfg.get_field("production.nstxout_compressed") or 5000

    npt_gro = find_input(ctx.inputs, "npt_gro")
    npt_cpt = find_input(ctx.inputs, "npt_cpt")
    ions_top = find_input(ctx.inputs, "system_ions_top")
    if npt_gro is None or npt_cpt is None or ions_top is None:
        return StepOutcome(failure={"code": "ConfigMissing", "message": "npt_gro/npt_cpt/system_ions_top missing"})

    mdp = render_production_mdp(
        nsteps=int(nsteps), dt_ps=float(dt_ps),
        temperature_K=float(T), pressure_bar=float(P),
        nstxout_compressed=int(nstxout_compressed),
    )

    # Production may run for a long time. Allow up to 6 hours of wall.
    result = run_phase(
        ctx,
        phase_name="production",
        mdp_text=mdp,
        in_gro=Path(npt_gro["artifact_uri"].removeprefix("local://")),
        in_top=Path(ions_top["artifact_uri"].removeprefix("local://")),
        in_cpt=Path(npt_cpt["artifact_uri"].removeprefix("local://")),
        deffnm="production",
        nt=1,
        mdrun_timeout_s=21600.0,
    )

    if not result["ok"]:
        return StepOutcome(failure=result["failure"], executor_calls=result["executor_calls"])
    return StepOutcome(
        outputs=result["outputs"],
        executor_calls=result["executor_calls"],
        extra={"nsteps": int(nsteps), "dt_ps": float(dt_ps), "temperature_K": float(T), "pressure_bar": float(P)},
    )
