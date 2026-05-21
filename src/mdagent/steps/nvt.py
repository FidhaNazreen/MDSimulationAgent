"""NVT equilibration — position-restrained at constant temperature."""

from __future__ import annotations

from pathlib import Path

from ..mdp import render_nvt_mdp
from .base import StepContext, StepOutcome, find_input
from ._md_driver import run_phase


def run(ctx: StepContext) -> StepOutcome:
    cfg = ctx.run_config
    nsteps = cfg.get_field("nvt.nsteps") or 50000
    dt_ps = cfg.get_field("nvt.dt_ps") or 0.002
    T = cfg.get_field("nvt.temperature_K") or 300.0
    seed = cfg.get_field("nvt.random_seed") or cfg.get_field("ion_strategy.random_seed") or 42
    nstxout_compressed = cfg.get_field("nvt.nstxout_compressed") or 5000

    em_gro = find_input(ctx.inputs, "em_gro")
    ions_top = find_input(ctx.inputs, "system_ions_top")
    if em_gro is None or ions_top is None:
        return StepOutcome(failure={"code": "ConfigMissing", "message": "em_gro or system_ions_top missing"})

    mdp = render_nvt_mdp(
        nsteps=int(nsteps), dt_ps=float(dt_ps),
        temperature_K=float(T), random_seed=int(seed),
        nstxout_compressed=int(nstxout_compressed),
    )

    result = run_phase(
        ctx,
        phase_name="nvt",
        mdp_text=mdp,
        in_gro=Path(em_gro["artifact_uri"].removeprefix("local://")),
        in_top=Path(ions_top["artifact_uri"].removeprefix("local://")),
        deffnm="nvt",
        nt=1,
    )

    if not result["ok"]:
        return StepOutcome(failure=result["failure"], executor_calls=result["executor_calls"])
    return StepOutcome(
        outputs=result["outputs"],
        executor_calls=result["executor_calls"],
        extra={"nsteps": int(nsteps), "dt_ps": float(dt_ps), "temperature_K": float(T)},
    )
