"""SystemClassifier — multi-label classification of the ingested structure.

v0 implementation: very small. Reads the working PDB, counts ATOM-record
residues, looks for HETATM / nucleic-acid residues / common membrane
markers. In `tutorial_reproduction` mode we only proceed if the structure
classifies as `chemistry={protein}` and there are no unsupported features.

A richer classifier (mmCIF-aware, biological-assembly-aware, OPM lookup)
is past v0.
"""

from __future__ import annotations

from collections import Counter

from ..hashing import sha256_text
from .base import StepContext, StepOutcome, find_input

PROTEIN_RESIDUES = {
    "ALA", "ARG", "ASN", "ASP", "CYS", "GLN", "GLU", "GLY", "HIS", "ILE",
    "LEU", "LYS", "MET", "PHE", "PRO", "SER", "THR", "TRP", "TYR", "VAL",
    "HID", "HIE", "HIP",  # FF-renamed variants
    "SEC", "PYL",
    "MSE",  # selenomethionine — counts as protein, gated by mse_policy elsewhere
}

NUCLEIC_RESIDUES = {"A", "C", "G", "U", "T", "DA", "DC", "DG", "DT", "DU"}


def run(ctx: StepContext) -> StepOutcome:
    working_ref = find_input(ctx.inputs, "working_pdb")
    if working_ref is None:
        return StepOutcome(failure={"code": "ConfigMissing", "message": "working_pdb input missing"})

    from pathlib import Path
    pdb_path = Path(working_ref["artifact_uri"].removeprefix("local://"))
    text = pdb_path.read_text()

    chemistry: set[str] = set()
    unsupported: list[str] = []
    res_counter: Counter[str] = Counter()
    chains: set[str] = set()

    for line in text.splitlines():
        if line.startswith("ATOM"):
            resname = line[17:20].strip()
            chain = line[21:22].strip()
            res_counter[resname] += 1
            if chain:
                chains.add(chain)
            if resname in PROTEIN_RESIDUES:
                chemistry.add("protein")
            elif resname in NUCLEIC_RESIDUES:
                chemistry.add("nucleic_acid")
                unsupported.append(f"nucleic_acid_residue: {resname}")
            else:
                # An ATOM record with a residue we don't recognize. Could be a
                # nonstandard cofactor (e.g. covalently bound) or a modified
                # residue we haven't enumerated. Surface as unsupported.
                unsupported.append(f"unknown_residue_in_atom: {resname}")
        elif line.startswith("HETATM"):
            resname = line[17:20].strip()
            if resname in ("HOH", "WAT", "SOL"):
                chemistry.add("water")
            else:
                chemistry.add("ligand")
                unsupported.append(f"hetatm_ligand: {resname}")

    assembly = "monomer" if len(chains) <= 1 else "homomultimer"
    environment_override = ctx.run_config.get_field("environment_override")
    environment = environment_override or "soluble"  # v0 default in tutorial mode

    pipeline_mode = ctx.run_config.get_field("pipeline_mode")
    v0_supported_chemistries = ({"protein"}, {"protein", "water"})

    classification = {
        "chemistry": sorted(chemistry),
        "assembly": assembly,
        "environment": environment,
        "unsupported_features": unsupported,
        "residue_counts": dict(res_counter),
        "chain_count": len(chains),
    }

    if chemistry in v0_supported_chemistries and not unsupported:
        # Proceed.
        path = ctx.step_dir / "classification.json"
        import json
        path.write_text(json.dumps(classification, indent=2, sort_keys=True))
        return StepOutcome(
            outputs=[{
                "artifact_uri": f"local://{path}",
                "content_hash": sha256_text(path.read_text()),
                "role": "classification",
            }],
            extra=classification,
        )

    return StepOutcome(
        failure={
            "code": "UnsupportedResidueError",
            "message": f"system classification not supported in v0: chemistry={sorted(chemistry)}, unsupported={unsupported}",
            "context": classification,
        }
    )
