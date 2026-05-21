"""Shared `grompp + mdrun` driver for NVT / NPT / production phases.

The three phases differ only in mdp template and which upstream `.gro`
they consume; the `grompp + mdrun` mechanics are identical.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Any

from ..hashing import sha256_file
from .base import StepContext


def _run_gmx(argv: list[str], cwd: Path, *, timeout: float | None = 1800.0):
    env = os.environ.copy()
    env.setdefault("LC_ALL", "C")
    env.setdefault("LANG", "C")
    t0 = time.monotonic()
    proc = subprocess.run(argv, cwd=str(cwd), env=env, capture_output=True, timeout=timeout)
    return proc, time.monotonic() - t0


def run_phase(
    ctx: StepContext,
    *,
    phase_name: str,
    mdp_text: str,
    in_gro: Path,
    in_top: Path,
    in_cpt: Path | None = None,
    deffnm: str = "phase",
    nt: int = 1,
    mdrun_timeout_s: float = 1800.0,
) -> dict[str, Any]:
    """Execute one grompp+mdrun phase.

    Returns a dict with: {ok, executor_calls, outputs, failure?} that the
    caller embeds into its StepOutcome.

    All upstream artifact files (top, itp, gro, cpt) are copied into the
    step_dir so `gmx grompp -p` and `-c` can resolve relative includes
    cleanly even when the upstream paths move between runs.
    """
    step_dir = ctx.step_dir
    step_dir.mkdir(parents=True, exist_ok=True)

    # Co-locate inputs.
    local_top = step_dir / "system.top"
    local_top.write_bytes(in_top.read_bytes())
    # Pull every .itp from the topology source dir so #includes resolve.
    src_dir = in_top.parent
    for itp in src_dir.glob("*.itp"):
        (step_dir / itp.name).write_bytes(itp.read_bytes())

    local_gro = step_dir / "input.gro"
    local_gro.write_bytes(in_gro.read_bytes())

    local_cpt: Path | None = None
    if in_cpt is not None and in_cpt.is_file():
        local_cpt = step_dir / "input.cpt"
        local_cpt.write_bytes(in_cpt.read_bytes())

    mdp_path = step_dir / f"{phase_name}.mdp"
    mdp_path.write_text(mdp_text)

    executor_calls: list[dict[str, Any]] = []

    # grompp. Pass -r matching -c so position restraints (when activated
    # via -DPOSRES in the mdp) can find their reference coordinates.
    # When restraints aren't used, -r is ignored — safe to pass always.
    tpr_path = step_dir / f"{deffnm}.tpr"
    grompp_argv = [
        "gmx", "grompp",
        "-f", str(mdp_path),
        "-c", str(local_gro),
        "-r", str(local_gro),
        "-p", str(local_top),
        "-o", str(tpr_path),
        "-maxwarn", "0",
    ]
    if local_cpt is not None:
        grompp_argv += ["-t", str(local_cpt)]
    grompp_proc, wall = _run_gmx(grompp_argv, step_dir)
    executor_calls.append({"argv": grompp_argv, "exit_status": grompp_proc.returncode, "wall_time_s": wall})
    if grompp_proc.returncode != 0:
        return {
            "ok": False,
            "executor_calls": executor_calls,
            "failure": {
                "code": "ConsistencyGateFailure",
                "message": f"{phase_name} grompp failed",
                "context": {"stderr": grompp_proc.stderr.decode(errors='replace')[-1500:]},
            },
        }

    # mdrun
    mdrun_argv = ["gmx", "mdrun", "-s", str(tpr_path), "-deffnm", deffnm, "-nt", str(nt), "-v"]
    mdrun_proc, wall = _run_gmx(mdrun_argv, step_dir, timeout=mdrun_timeout_s)
    executor_calls.append({"argv": mdrun_argv, "exit_status": mdrun_proc.returncode, "wall_time_s": wall})
    if mdrun_proc.returncode != 0:
        return {
            "ok": False,
            "executor_calls": executor_calls,
            "failure": {
                "code": "NonZeroExitError",
                "message": f"{phase_name} mdrun failed",
                "context": {"stderr": mdrun_proc.stderr.decode(errors='replace')[-1500:]},
            },
        }

    out_gro = step_dir / f"{deffnm}.gro"
    out_cpt = step_dir / f"{deffnm}.cpt"
    out_log = step_dir / f"{deffnm}.log"
    out_edr = step_dir / f"{deffnm}.edr"
    out_xtc = step_dir / f"{deffnm}.xtc"

    if not out_gro.is_file():
        return {
            "ok": False,
            "executor_calls": executor_calls,
            "failure": {"code": "NonZeroExitError", "message": f"{phase_name} mdrun produced no {out_gro.name}"},
        }

    outputs: list[dict[str, str]] = []
    for path, role_suffix in [
        (out_gro, f"{phase_name}_gro"),
        (out_cpt, f"{phase_name}_cpt"),
        (out_log, f"{phase_name}_log"),
        (out_edr, f"{phase_name}_edr"),
        (out_xtc, f"{phase_name}_xtc"),
        (tpr_path, f"{phase_name}_tpr"),
        (local_top, f"{phase_name}_top"),
    ]:
        if path.is_file():
            outputs.append({
                "artifact_uri": f"local://{path}",
                "content_hash": sha256_file(path),
                "role": role_suffix,
            })

    return {"ok": True, "executor_calls": executor_calls, "outputs": outputs}
