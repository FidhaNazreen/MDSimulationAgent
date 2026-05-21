"""Topology — drive `pdb2gmx` via DialogueRunner.

v0 behavior (tutorial mode on 1AKI):
  - Build a `topology_plan.json` recording FF/water/termini policy.
  - Invoke `gmx pdb2gmx -ff <ff> -water <water> -ignh -ter` via DialogueRunner.
  - Answer N- and C-terminus prompts from `termini_policy` (defaults: 0 = ionized).
  - Persist the decision trace (`pdb2gmx_transcript.json`).
  - Outputs: `system_apo.gro`, `system_apo.top`, `posre.itp`.

A richer Topology (PROPKA-driven HIS choices via `-inter`, explicit disulfide
handling via `-ss`, multichain `-chainsep`/`-merge`) is past v0.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from ..dialogue import (
    DialogueRunner,
    Pdb2GmxPromptRecognizer,
    StaticPlan,
)
from ..dialogue.types import PromptKind, Prompt
from ..hashing import sha256_file, sha256_text
from .base import StepContext, StepOutcome, find_input

# Default `0` for both termini = NH3+ at N-term, COO- at C-term (the
# tutorial defaults, matching pdb2gmx 2026.2 option ordering).
_TERMINI_DEFAULT_ANSWER = "0"


def _termini_answer(prompt_kind: PromptKind, cfg_field: str | None) -> str:
    # Mapping from configured termini state to pdb2gmx option index for OPLS-AA:
    #   N-term: 0=NH3+, 1=NH2, 2=Zwitter, 3=None
    #   C-term: 0=COO-, 1=Zwitter, 2=COOH, 3=None
    if cfg_field is None:
        return _TERMINI_DEFAULT_ANSWER
    if prompt_kind == PromptKind.TER_N_CHOICE:
        return {"charged": "0", "NH3+": "0", "NH2": "1", "neutral": "1", "ACE": "3"}.get(cfg_field, "0")
    if prompt_kind == PromptKind.TER_C_CHOICE:
        return {"charged": "0", "COO-": "0", "Zwitter": "1", "COOH": "2", "neutral": "2", "NME": "3"}.get(cfg_field, "0")
    return _TERMINI_DEFAULT_ANSWER


def run(ctx: StepContext) -> StepOutcome:
    cfg = ctx.run_config
    ff = cfg.get_field("force_field") or "oplsaa"
    water = cfg.get_field("water_model") or "spc"

    working_ref = find_input(ctx.inputs, "working_pdb")
    if working_ref is None:
        return StepOutcome(failure={"code": "ConfigMissing", "message": "working_pdb input missing"})
    working_src = Path(working_ref["artifact_uri"].removeprefix("local://"))

    # Copy working.pdb into the step dir so pdb2gmx's outputs are
    # co-located with their input.
    pdb_local = ctx.step_dir / "working.pdb"
    pdb_local.write_bytes(working_src.read_bytes())

    n_term_cfg = cfg.get_field("termini_policy.n_term_default")
    c_term_cfg = cfg.get_field("termini_policy.c_term_default")
    n_term_answer = _termini_answer(PromptKind.TER_N_CHOICE, n_term_cfg)
    c_term_answer = _termini_answer(PromptKind.TER_C_CHOICE, c_term_cfg)

    topology_plan: dict[str, Any] = {
        "force_field": ff,
        "water_model": water,
        "termini": {"n_term_answer": n_term_answer, "c_term_answer": c_term_answer},
        "protonation_decisions": [],  # v0: rely on pdb2gmx automatic HIS resolution; no -inter
        "disulfides": [],              # v0: rely on pdb2gmx automatic detection; no -ss prompt
        "chain_policy": {"chainsep": "id_or_ter", "merge_groups": []},
        "water_naming": {"bulk": "SOL"},
    }
    plan_path = ctx.step_dir / "topology_plan.json"
    plan_path.write_text(json.dumps(topology_plan, indent=2, sort_keys=True))

    static_plan = StaticPlan()
    static_plan.add_answer(PromptKind.TER_N_CHOICE, n_term_answer, plan_field="termini.n_term_answer")
    static_plan.add_answer(PromptKind.TER_C_CHOICE, c_term_answer, plan_field="termini.c_term_answer")

    recognizer = Pdb2GmxPromptRecognizer()
    runner = DialogueRunner(recognizer, read_timeout_s=120.0, idle_after_answer_s=0.2)

    argv = [
        "gmx", "pdb2gmx",
        "-f", str(pdb_local),
        "-o", "system_apo.gro",
        "-p", "system_apo.top",
        "-i", "posre.itp",
        "-ff", ff,
        "-water", water,
        "-ignh",
        "-ter",
    ]
    try:
        result, _diag = runner.run(argv, cwd=ctx.step_dir, plan=static_plan)
    except Exception as e:  # noqa: BLE001
        return StepOutcome(failure={
            "code": "UnexpectedPromptError" if type(e).__name__ == "UnexpectedPromptError" else "NonZeroExitError",
            "message": f"pdb2gmx via DialogueRunner failed: {e}",
            "context": {"argv": argv},
        })

    transcript_path = ctx.step_dir / "pdb2gmx_transcript.json"
    transcript_path.write_text(json.dumps(result.to_dict(), indent=2, sort_keys=True))

    gro = ctx.step_dir / "system_apo.gro"
    top = ctx.step_dir / "system_apo.top"
    posre = ctx.step_dir / "posre.itp"
    for p in (gro, top, posre):
        if not p.is_file():
            return StepOutcome(failure={
                "code": "NonZeroExitError",
                "message": f"pdb2gmx did not produce expected output {p.name}",
            })

    executor_calls = [{
        "argv": list(argv),
        "exit_status": result.exit_status,
        "wall_time_s": result.wall_time_s,
        "cwd": str(ctx.step_dir),
    }]

    return StepOutcome(
        outputs=[
            {"artifact_uri": f"local://{gro}", "content_hash": sha256_file(gro), "role": "system_apo_gro"},
            {"artifact_uri": f"local://{top}", "content_hash": sha256_file(top), "role": "system_apo_top"},
            {"artifact_uri": f"local://{posre}", "content_hash": sha256_file(posre), "role": "posre"},
            {"artifact_uri": f"local://{plan_path}", "content_hash": sha256_text(plan_path.read_text()), "role": "topology_plan"},
            {"artifact_uri": f"local://{transcript_path}", "content_hash": sha256_text(transcript_path.read_text()), "role": "pdb2gmx_transcript"},
        ],
        executor_calls=executor_calls,
        extra={
            "force_field": ff,
            "water_model": water,
            "n_exchanges": len(result.exchanges),
            "exit_status": result.exit_status,
        },
    )
