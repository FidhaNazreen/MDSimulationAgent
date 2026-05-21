"""StructureIngest — fetch and normalize the input PDB.

v0 behavior (tutorial mode on 1AKI):
  - Resolve input from RunConfig: either `input.pdb_id` (fetch from RCSB)
    or `input.structure_path` (use local file).
  - Write `original.pdb` (raw) and `working.pdb` (the version downstream
    steps consume).
  - In `tutorial_reproduction` mode, strip HETATM lines from working.pdb
    so `pdb2gmx` doesn't choke on crystallographic waters / ligands.

The full architecture also has the mmCIF canonical ingest + coordinate_id_map
(R4-2). That's deferred past v0 — `tutorial_reproduction` mode on 1AKI does
not exercise the cases that need the map.
"""

from __future__ import annotations

import urllib.request
from pathlib import Path

from ..hashing import sha256_file
from .base import StepContext, StepOutcome

RCSB_URL_TEMPLATE = "https://files.rcsb.org/download/{pdb_id}.pdb"


def run(ctx: StepContext) -> StepOutcome:
    cfg = ctx.run_config
    pdb_id = cfg.get_field("input.pdb_id")
    structure_path = cfg.get_field("input.structure_path")
    pipeline_mode = cfg.get_field("pipeline_mode")

    if pdb_id is None and structure_path is None:
        return StepOutcome(failure={
            "code": "ConfigMissing",
            "message": "input.pdb_id or input.structure_path must be set",
        })

    original_path = ctx.step_dir / "original.pdb"
    working_path = ctx.step_dir / "working.pdb"

    if pdb_id is not None:
        url = RCSB_URL_TEMPLATE.format(pdb_id=pdb_id.upper())
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                original_path.write_bytes(resp.read())
        except Exception as e:  # noqa: BLE001 - we wrap into a structured failure
            return StepOutcome(failure={
                "code": "NonZeroExitError",  # network failure shoehorned into the taxonomy for v0
                "message": f"fetch failed for {pdb_id}: {e}",
                "context": {"url": url},
            })
    else:
        src = Path(structure_path)
        if not src.is_file():
            return StepOutcome(failure={
                "code": "ConfigMissing",
                "message": f"structure_path does not exist: {src}",
            })
        original_path.write_bytes(src.read_bytes())

    # Write working.pdb: tutorial mode strips HETATM; general mode passes
    # through (water/ligand handling is downstream in StructurePrep).
    raw_lines = original_path.read_text().splitlines(keepends=True)
    if pipeline_mode == "tutorial_reproduction":
        working_lines = [ln for ln in raw_lines if not ln.startswith("HETATM")]
        n_stripped = sum(1 for ln in raw_lines if ln.startswith("HETATM"))
    else:
        working_lines = raw_lines
        n_stripped = 0
    working_path.write_text("".join(working_lines))

    return StepOutcome(
        outputs=[
            {
                "artifact_uri": f"local://{original_path}",
                "content_hash": sha256_file(original_path),
                "role": "original_pdb",
            },
            {
                "artifact_uri": f"local://{working_path}",
                "content_hash": sha256_file(working_path),
                "role": "working_pdb",
            },
        ],
        extra={
            "source": "rcsb" if pdb_id else "local",
            "pdb_id": pdb_id,
            "n_hetatm_stripped": n_stripped,
        },
    )
