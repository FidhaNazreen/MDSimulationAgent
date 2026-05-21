"""ShortEM — energy minimization as validation gate.

`gmx grompp -f em.mdp -c system_ions.gro -p system_ions.top -o em.tpr`
then `gmx mdrun -deffnm em -nt 1`.

Reads the convergence curve out of `em.log` and classifies the result:
  - converged       : final fmax < emtol (the configured tolerance)
  - needs_longer_em : step cap hit before convergence, no divergence
  - diverged        : energies/forces blew up (NaN or > a sane bound)
  - stuck           : made progress for a while then stopped without converging

Only the convergence verdict feeds `readiness_status` — non-convergence
is not necessarily a failure of the step (the run completed), but it sets
the readiness to `not_validated` per the architecture.
"""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from ..hashing import sha256_file, sha256_text
from ..mdp import render_em_mdp
from .base import StepContext, StepOutcome, find_input

_FMAX_LINE_RE = re.compile(r"\s*Maximum force\s*=\s*([0-9.eE+-]+)")
_STEPS_LINE_RE = re.compile(r"\s*Steepest Descents converged to .* in\s*(\d+)\s*steps")
_NOT_CONV_RE = re.compile(r"Steepest Descents did not converge", re.IGNORECASE)


def _run_gmx(argv: list[str], cwd: Path, *, timeout: float | None = 600.0):
    env = os.environ.copy()
    env.setdefault("LC_ALL", "C")
    env.setdefault("LANG", "C")
    t0 = time.monotonic()
    proc = subprocess.run(argv, cwd=str(cwd), env=env, capture_output=True, timeout=timeout)
    return proc, time.monotonic() - t0


def _parse_em_log(log_text: str, em_tol: float) -> dict[str, Any]:
    fmax_final: float | None = None
    nsteps: int | None = None
    verdict: str
    for line in log_text.splitlines():
        m = _FMAX_LINE_RE.match(line)
        if m:
            try:
                fmax_final = float(m.group(1))
            except ValueError:
                pass
        m = _STEPS_LINE_RE.match(line)
        if m:
            try:
                nsteps = int(m.group(1))
            except ValueError:
                pass

    if fmax_final is None:
        verdict = "stuck"  # could not parse — treat as inconclusive
    elif math.isnan(fmax_final) or math.isinf(fmax_final) or abs(fmax_final) > 1e9:
        verdict = "diverged"
    elif fmax_final < em_tol:
        verdict = "converged"
    elif _NOT_CONV_RE.search(log_text):
        verdict = "needs_longer_em"
    else:
        verdict = "needs_longer_em"

    return {"fmax_final": fmax_final, "nsteps": nsteps, "verdict": verdict}


def run(ctx: StepContext) -> StepOutcome:
    cfg = ctx.run_config
    step_cap = cfg.get_field("em.step_cap") or 1000
    em_tol = float(cfg.get_field("em.fmax_tol_kjmolnm") or 1000.0)

    gro_ref = find_input(ctx.inputs, "system_ions_gro")
    top_ref = find_input(ctx.inputs, "system_ions_top")
    if gro_ref is None or top_ref is None:
        return StepOutcome(failure={"code": "ConfigMissing", "message": "system_ions_gro/top missing"})

    # Co-locate inputs.
    gro = ctx.step_dir / "system_ions.gro"
    top = ctx.step_dir / "system_ions.top"
    gro.write_bytes(Path(gro_ref["artifact_uri"].removeprefix("local://")).read_bytes())
    top.write_bytes(Path(top_ref["artifact_uri"].removeprefix("local://")).read_bytes())
    # Copy any sibling itps so grompp can resolve #includes (posre.itp, etc.).
    src_dir = Path(top_ref["artifact_uri"].removeprefix("local://")).parent
    for p in src_dir.glob("*.itp"):
        (ctx.step_dir / p.name).write_bytes(p.read_bytes())

    mdp_path = ctx.step_dir / "em.mdp"
    mdp_text = render_em_mdp(step_cap=int(step_cap), fmax_tol_kjmolnm=em_tol)
    mdp_path.write_text(mdp_text)

    executor_calls: list[dict[str, Any]] = []

    tpr = ctx.step_dir / "em.tpr"
    argv = ["gmx", "grompp", "-f", str(mdp_path), "-c", str(gro), "-p", str(top), "-o", str(tpr), "-maxwarn", "0"]
    proc, wall = _run_gmx(argv, ctx.step_dir)
    executor_calls.append({"argv": argv, "exit_status": proc.returncode, "wall_time_s": wall})
    if proc.returncode != 0:
        return StepOutcome(
            failure={"code": "ConsistencyGateFailure", "message": "em grompp failed", "context": {"stderr": proc.stderr.decode(errors='replace')[-1500:]}},
            executor_calls=executor_calls,
        )

    # mdrun with explicit single thread to keep the test deterministic on any host.
    argv = ["gmx", "mdrun", "-s", str(tpr), "-deffnm", "em", "-nt", "1", "-v"]
    proc, wall = _run_gmx(argv, ctx.step_dir, timeout=600.0)
    executor_calls.append({"argv": argv, "exit_status": proc.returncode, "wall_time_s": wall})
    if proc.returncode != 0:
        # mdrun can exit non-zero on real-life numerical issues; we still try to read the log.
        log_text = (ctx.step_dir / "em.log").read_text() if (ctx.step_dir / "em.log").is_file() else ""
        verdict = _parse_em_log(log_text, em_tol)
        return StepOutcome(
            failure={"code": "EMDiverged" if verdict["verdict"] == "diverged" else "NonZeroExitError",
                     "message": f"mdrun failed (verdict={verdict['verdict']})",
                     "context": {**verdict, "stderr": proc.stderr.decode(errors='replace')[-1500:]}},
            executor_calls=executor_calls,
        )

    log_text = (ctx.step_dir / "em.log").read_text()
    em_verdict = _parse_em_log(log_text, em_tol)

    convergence_path = ctx.step_dir / "em_convergence.json"
    convergence_path.write_text(json.dumps(em_verdict, indent=2, sort_keys=True))

    em_gro = ctx.step_dir / "em.gro"
    if not em_gro.is_file():
        return StepOutcome(
            failure={"code": "NonZeroExitError", "message": "em.gro not produced", "context": em_verdict},
            executor_calls=executor_calls,
        )

    warnings: list[dict[str, Any]] = []
    if em_verdict["verdict"] != "converged":
        warnings.append({
            "class": "physics",
            "severity": "warning" if em_verdict["verdict"] == "needs_longer_em" else "blocking",
            "message": f"EM verdict: {em_verdict['verdict']}",
            "context": em_verdict,
        })
        if em_verdict["verdict"] in ("diverged", "stuck"):
            return StepOutcome(
                failure={"code": "EMStuck" if em_verdict["verdict"] == "stuck" else "EMDiverged",
                         "message": f"EM did not converge: {em_verdict['verdict']}",
                         "context": em_verdict},
                executor_calls=executor_calls,
                warnings=warnings,
            )

    return StepOutcome(
        outputs=[
            {"artifact_uri": f"local://{em_gro}", "content_hash": sha256_file(em_gro), "role": "em_gro"},
            {"artifact_uri": f"local://{ctx.step_dir / 'em.log'}", "content_hash": sha256_file(ctx.step_dir / 'em.log'), "role": "em_log"},
            {"artifact_uri": f"local://{convergence_path}", "content_hash": sha256_text(convergence_path.read_text()), "role": "em_convergence"},
        ],
        executor_calls=executor_calls,
        warnings=warnings,
        extra=em_verdict,
    )
