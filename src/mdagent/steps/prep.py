"""StructurePrep — analyze + transform (v0 minimal implementation).

In `tutorial_reproduction` mode on 1AKI nothing actually needs to be
transformed: the structure has no MSE, no altloc letters worth resolving,
no missing backbone, and the crystal waters were stripped at ingest.
So this v0 implementation:

  - emits observations.json (chain ids, residue counts, HIS residues, CYS
    residues that may form disulfides — purely informational),
  - emits an empty mutations.json (no transformations applied),
  - passes the ingest's working.pdb through as the output `working_pdb`.

A richer prep (PROPKA protonation analysis, altloc resolution, MSE→MET,
disulfide detection, ordered-water classification) is past v0 — those
agents become real when `general_md_prep` mode lands.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

from ..hashing import sha256_file, sha256_text
from .base import StepContext, StepOutcome, find_input


def run(ctx: StepContext) -> StepOutcome:
    working_ref = find_input(ctx.inputs, "working_pdb")
    if working_ref is None:
        return StepOutcome(failure={"code": "ConfigMissing", "message": "working_pdb input missing"})

    src_path = Path(working_ref["artifact_uri"].removeprefix("local://"))
    text = src_path.read_text()

    chain_res_counts: dict[str, Counter[str]] = defaultdict(Counter)
    his_residues: list[dict[str, int | str]] = []
    cys_residues: list[dict[str, int | str]] = []
    titratable_residues: list[dict[str, int | str]] = []
    seen_residue_keys: set[tuple[str, str, int]] = set()  # (resname, chain, resid)

    # Every residue type that pdb2gmx -inter will prompt about.
    titratable_restypes = {
        "LYS": "LYSINE",
        "ARG": "ARGININE",
        "ASP": "ASPARTIC ACID",
        "GLU": "GLUTAMIC ACID",
        "GLN": "GLUTAMINE",
        "HIS": "HISTIDINE",
        "HID": "HISTIDINE",
        "HIE": "HISTIDINE",
        "HIP": "HISTIDINE",
        "CYS": "CYSTEINE",
    }

    for line in text.splitlines():
        if not line.startswith("ATOM"):
            continue
        resname = line[17:20].strip()
        chain = line[21:22].strip() or "_"
        try:
            resid = int(line[22:26])
        except ValueError:
            continue
        key = (resname, chain, resid)
        if key in seen_residue_keys:
            continue
        seen_residue_keys.add(key)
        chain_res_counts[chain][resname] += 1
        if resname in ("HIS", "HID", "HIE", "HIP"):
            his_residues.append({"chain": chain, "resid": resid, "as_read": resname})
        elif resname == "CYS":
            cys_residues.append({"chain": chain, "resid": resid})
        if resname in titratable_restypes:
            titratable_residues.append({
                "chain": chain,
                "resid": resid,
                "residue_name": resname,
                "prompt_name": titratable_restypes[resname],
            })

    observations = {
        "chains": sorted(chain_res_counts.keys()),
        "residue_counts_by_chain": {k: dict(v) for k, v in chain_res_counts.items()},
        "histidines": his_residues,
        "cysteines": cys_residues,
        "titratable_residues": titratable_residues,
    }
    obs_path = ctx.step_dir / "observations.json"
    obs_path.write_text(json.dumps(observations, indent=2, sort_keys=True))

    mutations: list[dict[str, str]] = []  # tutorial mode applies no transformations
    mut_path = ctx.step_dir / "mutations.json"
    mut_path.write_text(json.dumps({"mutations": mutations}, indent=2, sort_keys=True))

    # Pass working_pdb through (copied so the prep step's outputs are
    # self-contained and the orchestrator can content-hash them).
    out_pdb = ctx.step_dir / "working.pdb"
    out_pdb.write_bytes(src_path.read_bytes())

    return StepOutcome(
        outputs=[
            {"artifact_uri": f"local://{out_pdb}", "content_hash": sha256_file(out_pdb), "role": "working_pdb"},
            {"artifact_uri": f"local://{obs_path}", "content_hash": sha256_text(obs_path.read_text()), "role": "observations"},
            {"artifact_uri": f"local://{mut_path}", "content_hash": sha256_text(mut_path.read_text()), "role": "mutations"},
        ],
        extra={"n_chains": len(observations["chains"]), "n_his": len(his_residues), "n_cys": len(cys_residues)},
    )
