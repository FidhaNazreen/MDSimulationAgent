"""MDP file templates for the v0 golden path.

The templates here are minimal but match the canonical GROMACS lysozyme
tutorial defaults for ions placement and steepest-descent energy
minimization. They are intentionally small — once the architecture grows
beyond v0 these should be replaced with a real templating system that
records the template hash in StepFingerprint.tool_components.
"""

from __future__ import annotations

from pathlib import Path

IONS_MDP = """\
; ions.mdp — used by gmx grompp before genion to produce a .tpr
; for ion insertion. No real dynamics is run; this is a placeholder.

integrator      = steep
nsteps          = 0
cutoff-scheme   = Verlet
nstlist         = 1
rlist           = 1.0
coulombtype     = PME
rcoulomb        = 1.0
vdw-type        = cut-off
rvdw            = 1.0
pbc             = xyz
"""

EM_MDP_TEMPLATE = """\
; em.mdp — steepest-descent energy minimization for v0 golden path.

integrator      = steep
nsteps          = {step_cap}
emtol           = {fmax_tol_kjmolnm}
emstep          = 0.01
cutoff-scheme   = Verlet
nstlist         = 10
rlist           = 1.0
coulombtype     = PME
rcoulomb        = 1.0
vdw-type        = cut-off
rvdw            = 1.0
pbc             = xyz
nstenergy       = 10
nstlog          = 10
"""


def render_em_mdp(*, step_cap: int = 1000, fmax_tol_kjmolnm: float = 1000.0) -> str:
    return EM_MDP_TEMPLATE.format(step_cap=step_cap, fmax_tol_kjmolnm=fmax_tol_kjmolnm)


def write_mdp(path: str | Path, content: str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
