"""NPT equilibration — position-restrained at constant temperature + pressure.

Continues velocities + box from NVT via the -t <nvt.cpt> handoff.
"""

from __future__ import annotations

from pathlib import Path

from ..mdp import render_npt_mdp
from .base import StepContext, StepOutcome, find_input
from ._md_driver import run_phase


def run(ctx: StepContext) -> StepOutcome:
    cfg = ctx.run_config
    nsteps = cfg.get_field("npt.nsteps") or 50000
    dt_ps = cfg.get_field("npt.dt_ps") or 0.002
    T = cfg.get_field("npt.temperature_K") or 300.0
    P = cfg.get_field("npt.pressure_bar") or 1.0
    nstxout_compressed = cfg.get_field("npt.nstxout_compressed") or 5000

    nvt_gro = find_input(ctx.inputs, "nvt_gro")
    nvt_cpt = find_input(ctx.inputs, "nvt_cpt")
    ions_top = find_input(ctx.inputs, "system_ions_top")
    if nvt_gro is None or nvt_cpt is None or ions_top is None:
        return StepOutcome(failure={"code": "ConfigMissing", "message": "nvt_gro/nvt_cpt/system_ions_top missing"})

    mdp = render_npt_mdp(
        nsteps=int(nsteps), dt_ps=float(dt_ps),
        temperature_K=float(T), pressure_bar=float(P),
        nstxout_compressed=int(nstxout_compressed),
    )

    result = run_phase(
        ctx,
        phase_name="npt",
        mdp_text=mdp,
        in_gro=Path(nvt_gro["artifact_uri"].removeprefix("local://")),
        in_top=Path(ions_top["artifact_uri"].removeprefix("local://")),
        in_cpt=Path(nvt_cpt["artifact_uri"].removeprefix("local://")),
        deffnm="npt",
        nt=1,
    )

    if not result["ok"]:
        return StepOutcome(failure=result["failure"], executor_calls=result["executor_calls"])
    return StepOutcome(
        outputs=result["outputs"],
        executor_calls=result["executor_calls"],
        extra={"nsteps": int(nsteps), "dt_ps": float(dt_ps), "temperature_K": float(T), "pressure_bar": float(P)},
    )
