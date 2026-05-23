"""Topology — drive `pdb2gmx` via DialogueRunner.

Two paths:

  - **tutorial_reproduction mode** (default for 1AKI parity): invoke
    `gmx pdb2gmx -ff <ff> -water <water> -ignh -ter`. Termini answered from
    `termini_policy`; all per-residue protonation states resolved
    automatically by gmx (HIS auto via H-bond network, LYS+/ARG+/ASP-/GLU-
    fixed defaults).

  - **general_md_prep mode**: same plus `-inter`. Every titratable residue
    (LYS/ARG/ASP/GLU/GLN/HIS/CYS) becomes a per-residue prompt. The plan
    is built from `StructurePrep.observations.titratable_residues` and
    persisted to `protonation_decisions.json` so the chosen answer per
    residue is auditable.

A richer Topology (PROPKA-driven HIS choices, explicit disulfide handling
via `-ss`, multichain `-chainsep`/`-merge`) is past this slice.
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

# Default protonation-prompt answers at pH 7 for OPLS-AA / AMBER / CHARMM:
# (matching the option index pdb2gmx prints, which is FF-stable for these.)
#   LYSINE       0 = LYS (neutral, charge 0),       1 = LYSH (protonated, +1)
#   ARGININE     0 = LYS-like neutral / sometimes only one option (varies by FF)
#                Modern OPLS exposes 0 only (always-protonated); we answer "0".
#   ASPARTIC ACID 0 = ASP (deprotonated, -1),       1 = ASPH (protonated)
#   GLUTAMIC ACID 0 = GLU (deprotonated, -1),       1 = GLUH (protonated)
#   GLUTAMINE     0 = GLN (default — only one option in most FFs)
#   HISTIDINE     0 = HID (delta-protonated),  1 = HIE (epsilon),  2 = HIP (doubly)
#                 Default for OPLS at pH 7: HIE = 1.
#   CYSTEINE      0 = CYS (free, -SH),    1 = CYS2 (disulfide-bonded, no H)
#                 We default to 0 (free); disulfide pairs need the -ss flow.
_PROTONATION_DEFAULTS: dict[str, str] = {
    "LYSINE": "1",
    "ARGININE": "0",
    "ASPARTIC ACID": "0",
    "GLUTAMIC ACID": "0",
    "GLUTAMINE": "0",
    "HISTIDINE": "1",
    "CYSTEINE": "0",
}


def _pka_aware_answer(prompt_name: str, pka_value: float | None, ph: float) -> tuple[str, str]:
    """Pick the pdb2gmx option index based on a PROPKA-style pKa vs pH.

    Returns (answer_index, source). When pka_value is None (no propka
    info) the answer is the fixed pH-7 default and source is
    "policy_default_pH7"; otherwise it's "propka@pH{ph}".

    The mapping mirrors `_PROTONATION_DEFAULTS` keys; option indices
    match the OPLS-AA pdb2gmx prompt ordering (verified in slice 7).
    """
    if pka_value is None or pka_value == 99.99:
        return _PROTONATION_DEFAULTS.get(prompt_name, "0"), "policy_default_pH7"
    protonated = pka_value > ph
    source = f"propka@pH{ph}"
    if prompt_name == "LYSINE":
        return ("1" if protonated else "0"), source
    if prompt_name == "ASPARTIC ACID" or prompt_name == "GLUTAMIC ACID":
        return ("1" if protonated else "0"), source
    if prompt_name == "HISTIDINE":
        # OPLS HIS options: 0=HID, 1=HIE, 2=HIP. Default neutral = HIE.
        return ("2" if protonated else "1"), source
    # ARG / GLN / CYS: keep the fixed default — these are largely
    # unaffected by physiological pH or governed by separate flows
    # (CYS pairs go through SS_YN; ARG is always charged in practice).
    return _PROTONATION_DEFAULTS.get(prompt_name, "0"), source


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
    pipeline_mode = cfg.get_field("pipeline_mode") or "tutorial_reproduction"

    working_ref = find_input(ctx.inputs, "working_pdb")
    if working_ref is None:
        return StepOutcome(failure={"code": "ConfigMissing", "message": "working_pdb input missing"})
    working_src = Path(working_ref["artifact_uri"].removeprefix("local://"))

    # In general_md_prep mode, drive per-residue prompts via -inter. The
    # plan is built from the prep step's titratable_residues list (read
    # from observations.json) plus the optional propka-driven pKa
    # predictions (read from protonation_analysis.json if it exists).
    use_inter = (pipeline_mode == "general_md_prep")
    titratable_residues: list[dict[str, Any]] = []
    pka_by_key: dict[tuple[str, int, str], dict[str, Any]] = {}
    protonation_method = "ff_default_pH7"
    if use_inter:
        obs_path = ctx.run_root / "step_03_structure_prep" / "observations.json"
        if obs_path.is_file():
            try:
                obs = json.loads(obs_path.read_text())
                titratable_residues = list(obs.get("titratable_residues", []))
            except (OSError, json.JSONDecodeError):
                titratable_residues = []
        pka_path = ctx.run_root / "step_03_structure_prep" / "protonation_analysis.json"
        if pka_path.is_file():
            try:
                analysis = json.loads(pka_path.read_text())
                for entry in analysis.get("residues", []):
                    key = (entry["chain"], int(entry["resid"]), entry["residue_type"])
                    pka_by_key[key] = entry
                protonation_method = analysis.get("method", "propka")
            except (OSError, json.JSONDecodeError, KeyError):
                pka_by_key = {}

    # Copy working.pdb into the step dir so pdb2gmx's outputs are
    # co-located with their input.
    pdb_local = ctx.step_dir / "working.pdb"
    pdb_local.write_bytes(working_src.read_bytes())

    n_term_cfg = cfg.get_field("termini_policy.n_term_default")
    c_term_cfg = cfg.get_field("termini_policy.c_term_default")
    n_term_answer = _termini_answer(PromptKind.TER_N_CHOICE, n_term_cfg)
    c_term_answer = _termini_answer(PromptKind.TER_C_CHOICE, c_term_cfg)

    # Build the per-residue protonation_decisions list (only populated in
    # general mode; in tutorial mode pdb2gmx auto-resolves).
    protonation_decisions: list[dict[str, Any]] = []
    ph = float(cfg.get_field("ph") or 7.0)
    if use_inter:
        for res in titratable_residues:
            restype = res["prompt_name"]
            # Look up pKa by (chain, resid, residue_name). pKa file keys
            # use the three-letter code (HIS/ASP/...).
            pka_entry = pka_by_key.get((res["chain"], int(res["resid"]), res["residue_name"]))
            pka_value = pka_entry["pka_value"] if pka_entry else None
            answer, source = _pka_aware_answer(restype, pka_value, ph)
            protonation_decisions.append({
                "chain": res["chain"],
                "resid": int(res["resid"]),
                "residue_name": res["residue_name"],
                "prompt_name": restype,
                "answer_index": answer,
                "source": source,
                "pka_value": pka_value,
                "ph_assumed": ph,
            })

    topology_plan: dict[str, Any] = {
        "force_field": ff,
        "water_model": water,
        "pipeline_mode": pipeline_mode,
        "termini": {"n_term_answer": n_term_answer, "c_term_answer": c_term_answer},
        "protonation_decisions": protonation_decisions,
        "disulfides": [],  # -ss handling lives in a later slice
        "chain_policy": {"chainsep": "id_or_ter", "merge_groups": []},
        "water_naming": {"bulk": "SOL"},
    }
    plan_path = ctx.step_dir / "topology_plan.json"
    plan_path.write_text(json.dumps(topology_plan, indent=2, sort_keys=True))

    static_plan = StaticPlan()
    static_plan.add_answer(PromptKind.TER_N_CHOICE, n_term_answer, plan_field="termini.n_term_answer")
    static_plan.add_answer(PromptKind.TER_C_CHOICE, c_term_answer, plan_field="termini.c_term_answer")
    for decision in protonation_decisions:
        static_plan.add_answer(
            PromptKind.INTER_RESIDUE_CHOICE,
            decision["answer_index"],
            plan_field=f"protonation.{decision['residue_name']}.{decision['resid']}",
            context={"residue_type": decision["prompt_name"], "resid": decision["resid"]},
            context_keys=("residue_type", "resid"),
        )
    # Disulfide policy (v0): accept every CYS pair that pdb2gmx structurally
    # detected. This matches the architecture's R2-27 "auto_detect" default.
    static_plan.add_answer(
        PromptKind.SS_YN, "y",
        plan_field="disulfide_policy.auto_detect_accept",
    )

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
    if use_inter:
        argv.append("-inter")
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

    # Record the actual decisions made (from the exchange log), so even if
    # policy_default ever overrides a planned answer we have the audit
    # trail. Each exchange against an INTER_RESIDUE_CHOICE prompt becomes
    # one entry; TER prompts are recorded under termini.
    actual_protonation_decisions: list[dict[str, Any]] = []
    for exch in result.exchanges:
        if exch.prompt.kind != PromptKind.INTER_RESIDUE_CHOICE:
            continue
        ctx_dict = exch.prompt.context
        actual_protonation_decisions.append({
            "residue_type": ctx_dict.get("residue_type"),
            "resid": ctx_dict.get("resid"),
            "answer_index": exch.answer,
            "answer_label": exch.prompt.options.get(exch.answer),
            "answer_source": exch.answer_source,
        })
    decisions_path = ctx.step_dir / "protonation_decisions.json"
    decisions_path.write_text(json.dumps({
        "planned": protonation_decisions,
        "actual": actual_protonation_decisions,
    }, indent=2, sort_keys=False))

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
            {"artifact_uri": f"local://{decisions_path}", "content_hash": sha256_text(decisions_path.read_text()), "role": "protonation_decisions"},
        ],
        executor_calls=executor_calls,
        extra={
            "force_field": ff,
            "water_model": water,
            "n_exchanges": len(result.exchanges),
            "exit_status": result.exit_status,
        },
    )
