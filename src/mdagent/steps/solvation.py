"""Solvation — box + solvate + ions.

v0 implementation:
  - `gmx editconf` to create the simulation box (dodecahedron, 1.0 nm padding).
  - `gmx solvate` to fill with bulk water.
  - Write `ions.mdp`, `gmx grompp` to produce ions.tpr.
  - `gmx genion -neutral` (and optionally `-conc <M>`) to neutralize charge.
  - Parse pre- and post-ion total charge from `grompp` output.
  - Emit `charge_accounting.json` recording the four-stage record from R2-17.

Per R4-1, in tutorial mode there are no retained crystal waters, so the
'bulk_solvent' index is the entire SOL group; we pass the group name
"SOL" to genion via stdin. Positional bulk-only indexing kicks in only
when the architecture's general-mode water retention lands.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from ..hashing import sha256_file, sha256_text
from .base import StepContext, StepOutcome, find_input

_TOTAL_CHARGE_RE = re.compile(r"System has non-zero total charge: ([-+]?\d+\.?\d*)", re.MULTILINE)
_ATOMS_RE = re.compile(r"There are: (\d+) Atoms", re.MULTILINE)


def _run_gmx(
    argv: list[str],
    cwd: Path,
    *,
    stdin_bytes: bytes | None = None,
    timeout: float | None = 300.0,
) -> tuple[subprocess.CompletedProcess[bytes], float]:
    env = os.environ.copy()
    env.setdefault("LC_ALL", "C")
    env.setdefault("LANG", "C")
    t0 = time.monotonic()
    proc = subprocess.run(
        argv,
        cwd=str(cwd),
        env=env,
        input=stdin_bytes,
        capture_output=True,
        timeout=timeout,
    )
    return proc, time.monotonic() - t0


def _parse_total_charge(stderr_text: str) -> float | None:
    """Find 'System has non-zero total charge' or fall back to other markers."""
    m = _TOTAL_CHARGE_RE.search(stderr_text)
    if m:
        return float(m.group(1))
    # If grompp printed total charge = 0 (no message), report 0.
    if "Total charge: 0" in stderr_text or "Number of states with non-zero charge: 0" in stderr_text:
        return 0.0
    # Last resort: scan for 'Total charge'
    for line in stderr_text.splitlines():
        if "Total charge" in line:
            for token in line.split():
                try:
                    return float(token)
                except ValueError:
                    continue
    return None


def _count_top_molecule(top_text: str, molecule_name: str) -> int:
    """Return the count for a molecule name in the final [ molecules ] section.

    Picks the LAST [ molecules ] block (genion can leave older blocks if a
    top was edited oddly). Counts only the lines matching the name.
    """
    sections = top_text.split("[ molecules ]")
    if len(sections) < 2:
        return 0
    block = sections[-1]
    total = 0
    for line in block.splitlines():
        line = line.strip()
        if not line or line.startswith(";") or line.startswith("["):
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[0] == molecule_name:
            try:
                total += int(parts[1])
            except ValueError:
                pass
    return total


def run(ctx: StepContext) -> StepOutcome:
    cfg = ctx.run_config
    box_geometry = cfg.get_field("box.geometry") or "dodecahedron"
    padding_nm = cfg.get_field("box.padding_nm") or 1.0
    ion_mode = cfg.get_field("ion_strategy.mode") or "neutralize_only"
    salt_M = cfg.get_field("ion_strategy.salt_M")
    cation = cfg.get_field("ion_strategy.cation") or "NA"
    anion = cfg.get_field("ion_strategy.anion") or "CL"
    random_seed = cfg.get_field("ion_strategy.random_seed") or 42
    water = cfg.get_field("water_model") or "spc"

    apo_gro_ref = find_input(ctx.inputs, "system_apo_gro")
    apo_top_ref = find_input(ctx.inputs, "system_apo_top")
    if apo_gro_ref is None or apo_top_ref is None:
        return StepOutcome(failure={"code": "ConfigMissing", "message": "system_apo_gro/top input missing"})

    # Copy inputs into the step dir so all artifacts are co-located.
    apo_gro = ctx.step_dir / "system_apo.gro"
    apo_top = ctx.step_dir / "system_apo.top"
    apo_gro.write_bytes(Path(apo_gro_ref["artifact_uri"].removeprefix("local://")).read_bytes())
    apo_top.write_bytes(Path(apo_top_ref["artifact_uri"].removeprefix("local://")).read_bytes())

    # posre.itp lives next to the topology and is #include'd. Copy if present.
    posre_ref = find_input(ctx.inputs, "posre")
    if posre_ref is not None:
        posre_src = Path(posre_ref["artifact_uri"].removeprefix("local://"))
        (ctx.step_dir / posre_src.name).write_bytes(posre_src.read_bytes())

    executor_calls: list[dict[str, Any]] = []

    # 1. editconf
    box_gro = ctx.step_dir / "system_box.gro"
    argv = ["gmx", "editconf", "-f", str(apo_gro), "-o", str(box_gro), "-c", "-d", str(padding_nm), "-bt", box_geometry]
    proc, wall = _run_gmx(argv, ctx.step_dir)
    executor_calls.append({"argv": argv, "exit_status": proc.returncode, "wall_time_s": wall})
    if proc.returncode != 0:
        return StepOutcome(
            failure={"code": "NonZeroExitError", "message": "gmx editconf failed", "context": {"stderr": proc.stderr.decode(errors="replace")[-1500:]}},
            executor_calls=executor_calls,
        )

    # 2. solvate (this modifies apo_top in place by appending SOL count)
    solv_gro = ctx.step_dir / "system_solvated.gro"
    argv = ["gmx", "solvate", "-cp", str(box_gro), "-cs", "spc216.gro", "-o", str(solv_gro), "-p", str(apo_top)]
    proc, wall = _run_gmx(argv, ctx.step_dir)
    executor_calls.append({"argv": argv, "exit_status": proc.returncode, "wall_time_s": wall})
    if proc.returncode != 0:
        return StepOutcome(
            failure={"code": "NonZeroExitError", "message": "gmx solvate failed", "context": {"stderr": proc.stderr.decode(errors="replace")[-1500:]}},
            executor_calls=executor_calls,
        )
    n_sol_after_solvate = _count_top_molecule(apo_top.read_text(), "SOL")

    # 3. write ions.mdp and grompp it (consistency_gate stage 1)
    from ..mdp import IONS_MDP
    ions_mdp = ctx.step_dir / "ions.mdp"
    ions_mdp.write_text(IONS_MDP)
    ions_tpr = ctx.step_dir / "ions.tpr"
    # `-maxwarn 1` here is intentional: at this stage the system still has the
    # protein's net charge (not yet neutralized), so grompp will emit a
    # "net charge + Ewald" warning. That's exactly what genion is about to
    # fix. The post-genion grompp keeps `-maxwarn 0` so the final neutralized
    # system passes the full consistency_gate.
    argv = ["gmx", "grompp", "-f", str(ions_mdp), "-c", str(solv_gro), "-p", str(apo_top), "-o", str(ions_tpr), "-maxwarn", "1"]
    proc, wall = _run_gmx(argv, ctx.step_dir)
    executor_calls.append({"argv": argv, "exit_status": proc.returncode, "wall_time_s": wall})
    grompp_stderr = proc.stderr.decode(errors="replace")
    if proc.returncode != 0:
        return StepOutcome(
            failure={"code": "ConsistencyGateFailure", "message": "ions grompp failed", "context": {"stderr": grompp_stderr[-1500:]}},
            executor_calls=executor_calls,
        )
    pre_ion_charge = _parse_total_charge(grompp_stderr) or 0.0

    # 4. genion
    if ion_mode == "neutralize_only":
        genion_flags = ["-neutral"]
    elif ion_mode == "physiological_salt":
        salt = float(salt_M) if salt_M is not None else 0.15
        genion_flags = ["-neutral", "-conc", str(salt)]
    elif ion_mode == "custom":
        salt = float(salt_M) if salt_M is not None else 0.0
        genion_flags = ["-conc", str(salt)] if salt > 0 else ["-neutral"]
    else:
        return StepOutcome(
            failure={"code": "ConfigMissing", "message": f"unknown ion_strategy.mode={ion_mode}"},
            executor_calls=executor_calls,
        )

    final_gro = ctx.step_dir / "system_ions.gro"
    final_top = ctx.step_dir / "system_ions.top"
    # genion modifies the .top in place. Copy apo_top → final_top so genion edits final_top.
    final_top.write_bytes(apo_top.read_bytes())
    argv = [
        "gmx", "genion",
        "-s", str(ions_tpr),
        "-o", str(final_gro),
        "-p", str(final_top),
        "-pname", cation,
        "-nname", anion,
        "-seed", str(random_seed),
    ] + genion_flags
    # genion asks "Group?" — answer with the bulk-solvent group name.
    proc, wall = _run_gmx(argv, ctx.step_dir, stdin_bytes=b"SOL\n")
    executor_calls.append({"argv": argv, "exit_status": proc.returncode, "wall_time_s": wall})
    if proc.returncode != 0:
        return StepOutcome(
            failure={"code": "NonZeroExitError", "message": "gmx genion failed", "context": {"stderr": proc.stderr.decode(errors="replace")[-1500:]}},
            executor_calls=executor_calls,
        )

    # 5. consistency_gate stage 2: re-grompp the neutralized system.
    final_tpr = ctx.step_dir / "system_ions.tpr"
    argv = ["gmx", "grompp", "-f", str(ions_mdp), "-c", str(final_gro), "-p", str(final_top), "-o", str(final_tpr), "-maxwarn", "0"]
    proc, wall = _run_gmx(argv, ctx.step_dir)
    executor_calls.append({"argv": argv, "exit_status": proc.returncode, "wall_time_s": wall})
    post_ion_grompp_stderr = proc.stderr.decode(errors="replace")
    if proc.returncode != 0:
        return StepOutcome(
            failure={"code": "ConsistencyGateFailure", "message": "post-ion grompp failed", "context": {"stderr": post_ion_grompp_stderr[-1500:]}},
            executor_calls=executor_calls,
        )

    # 6. Four-stage charge accounting.
    final_top_text = final_top.read_text()
    actual_cations = _count_top_molecule(final_top_text, cation)
    actual_anions = _count_top_molecule(final_top_text, anion)
    n_sol_final = _count_top_molecule(final_top_text, "SOL")
    final_charge = _parse_total_charge(post_ion_grompp_stderr) or 0.0

    expected_cations_int = max(0, int(round(-pre_ion_charge)))
    expected_anions_int = max(0, int(round(pre_ion_charge)))

    charge_accounting = {
        "pre_ion_total_charge": pre_ion_charge,
        "expected_cations": expected_cations_int,
        "expected_anions": expected_anions_int,
        "actual_cations": actual_cations,
        "actual_anions": actual_anions,
        "final_total_charge": final_charge,
        "n_sol_after_solvate": n_sol_after_solvate,
        "n_sol_final": n_sol_final,
        "tolerance_e": 1e-3,
        "passes": abs(final_charge) < 1e-3
                  and actual_cations == expected_cations_int
                  and actual_anions == expected_anions_int,
    }
    ca_path = ctx.step_dir / "charge_accounting.json"
    ca_path.write_text(json.dumps(charge_accounting, indent=2, sort_keys=True))

    warnings: list[dict[str, Any]] = []
    if not charge_accounting["passes"]:
        warnings.append({
            "class": "chemistry",
            "severity": "blocking",
            "message": "charge accounting mismatch",
            "context": charge_accounting,
        })
        return StepOutcome(
            failure={"code": "ChargeAccountingMismatch", "message": "post-ion charge accounting did not balance", "context": charge_accounting},
            executor_calls=executor_calls,
            warnings=warnings,
        )

    return StepOutcome(
        outputs=[
            {"artifact_uri": f"local://{final_gro}", "content_hash": sha256_file(final_gro), "role": "system_ions_gro"},
            {"artifact_uri": f"local://{final_top}", "content_hash": sha256_file(final_top), "role": "system_ions_top"},
            {"artifact_uri": f"local://{final_tpr}", "content_hash": sha256_file(final_tpr), "role": "system_ions_tpr"},
            {"artifact_uri": f"local://{ca_path}", "content_hash": sha256_text(ca_path.read_text()), "role": "charge_accounting"},
        ],
        executor_calls=executor_calls,
        extra={
            "n_sol_after_solvate": n_sol_after_solvate,
            "n_sol_final": n_sol_final,
            "actual_cations": actual_cations,
            "actual_anions": actual_anions,
            "pre_ion_charge": pre_ion_charge,
            "final_charge": final_charge,
        },
    )
