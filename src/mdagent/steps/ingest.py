"""StructureIngest — fetch and normalize the input structure.

Three formats are supported on input:
  - PDB (legacy) — fetched from `https://files.rcsb.org/download/<ID>.pdb`.
  - mmCIF (canonical, per R3-25) — fetched from `<ID>.cif`.
  - Local file at `input.structure_path` (either format; detected by suffix).

Format selection follows `input.format_preference`:
  - `pdb` : use PDB end-to-end. No `coordinate_id_map.json` is emitted.
  - `mmcif` : use mmCIF as canonical. Derive a PDB for pdb2gmx and emit
    `coordinate_id_map.json` mapping canonical mmCIF residue IDs to
    derived PDB chain/resid/icode, with injectivity verification per
    R4-2 / R5 nitpick #1.
  - `auto` (default) : mmcif when `pipeline_mode='general_md_prep'`, pdb
    otherwise. Keeps tutorial_reproduction transparent and switches
    canonical to mmcif for general mode.

Tutorial-mode stripping (HETATMs out of `working.pdb`) is applied
regardless of source format so `pdb2gmx` doesn't choke on crystal waters.

The CoordinateIdMap is built from gemmi's structured iteration over the
mmCIF and is **hard-failed** with `CoordinateIdMapNotInjective` if any
derived (chain, resid, icode) tuple collides across multiple canonical
residues.
"""

from __future__ import annotations

import io
import json
import urllib.request
from pathlib import Path
from typing import Any

import gemmi

from ..hashing import sha256_file, sha256_text
from .base import StepContext, StepOutcome

RCSB_PDB_TEMPLATE = "https://files.rcsb.org/download/{pdb_id}.pdb"
RCSB_CIF_TEMPLATE = "https://files.rcsb.org/download/{pdb_id}.cif"


def _resolve_format(cfg) -> str:
    pref = cfg.get_field("input.format_preference") or "auto"
    if pref != "auto":
        return pref
    mode = cfg.get_field("pipeline_mode") or "tutorial_reproduction"
    return "mmcif" if mode == "general_md_prep" else "pdb"


def _fetch(url: str, dest: Path) -> None:
    with urllib.request.urlopen(url, timeout=30) as resp:
        dest.write_bytes(resp.read())


def _build_coordinate_id_map(structure: gemmi.Structure) -> dict[str, Any]:
    """Walk gemmi's residue iteration; build canonical→derived rows.

    Derived ids follow PDB conventions: single-letter `chain`, integer
    `resid`, single-char `icode`. Collisions on those derived tuples
    flag the map as `lossy_with_diff`.
    """
    residues_rows: list[dict[str, Any]] = []
    derived_index: dict[tuple[str, int, str], list[dict[str, Any]]] = {}

    for model_idx, model in enumerate(structure, start=1):
        for chain in model:
            label_asym_id = chain.name  # gemmi exposes this as `Chain.name`
            for residue in chain:
                # gemmi.Residue gives seqid (.seqid.num, .seqid.icode), name, label_seq, auth_seq
                rid = residue.seqid
                canonical = {
                    "model": model_idx,
                    "label_asym_id": label_asym_id,
                    "auth_asym_id": label_asym_id,  # gemmi treats these as the same in default ingest
                    "label_seq_id": getattr(residue, "label_seq", None) or None,
                    "auth_seq_id": rid.num,
                    "insertion_code": rid.icode.strip() or "",
                    "residue_name": residue.name,
                }
                derived = {
                    "chain": label_asym_id[:1] or " ",
                    "resid": rid.num,
                    "icode": rid.icode.strip() or "",
                    "residue_name": residue.name,
                }
                residues_rows.append({"canonical": canonical, "derived_pdb": derived})
                key = (derived["chain"], derived["resid"], derived["icode"])
                derived_index.setdefault(key, []).append({"canonical": canonical, "derived_pdb": derived})

    collisions = [v for v in derived_index.values() if len(v) > 1]
    if collisions:
        lossy_diff: list[dict[str, Any]] = []
        for grp in collisions:
            head = grp[0]
            others = grp[1:]
            lossy_diff.append({
                "canonical": head["canonical"],
                "collides_with": [g["canonical"] for g in others],
            })
        return {
            "schema_version": "0.1.0",
            "injectivity": "lossy_with_diff",
            "lossy_diff": lossy_diff,
            "residues": residues_rows,
        }
    return {
        "schema_version": "0.1.0",
        "injectivity": "verified",
        "residues": residues_rows,
    }


def _derive_pdb_from_mmcif(cif_path: Path, derived_pdb_path: Path) -> gemmi.Structure:
    """Load mmCIF via gemmi, write a PDB representation usable by pdb2gmx."""
    structure = gemmi.read_structure(str(cif_path))
    structure.setup_entities()
    structure.write_pdb(str(derived_pdb_path))
    return structure


def run(ctx: StepContext) -> StepOutcome:
    cfg = ctx.run_config
    pdb_id = cfg.get_field("input.pdb_id")
    structure_path = cfg.get_field("input.structure_path")
    pipeline_mode = cfg.get_field("pipeline_mode")
    fmt = _resolve_format(cfg)

    if pdb_id is None and structure_path is None:
        return StepOutcome(failure={
            "code": "ConfigMissing",
            "message": "input.pdb_id or input.structure_path must be set",
        })

    original_path = ctx.step_dir / ("original.cif" if fmt == "mmcif" else "original.pdb")
    derived_pdb_path = ctx.step_dir / "derived.pdb"
    working_path = ctx.step_dir / "working.pdb"
    coord_map_path = ctx.step_dir / "coordinate_id_map.json"

    # ---- Fetch / copy input.
    if pdb_id is not None:
        url = (RCSB_CIF_TEMPLATE if fmt == "mmcif" else RCSB_PDB_TEMPLATE).format(pdb_id=pdb_id.upper())
        try:
            _fetch(url, original_path)
        except Exception as e:  # noqa: BLE001
            return StepOutcome(failure={
                "code": "NonZeroExitError",
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

    outputs: list[dict[str, str]] = [{
        "artifact_uri": f"local://{original_path}",
        "content_hash": sha256_file(original_path),
        "role": "original_structure",
    }]

    # ---- Derive PDB + (optional) coordinate_id_map.
    if fmt == "mmcif":
        try:
            structure = _derive_pdb_from_mmcif(original_path, derived_pdb_path)
        except Exception as e:  # noqa: BLE001
            return StepOutcome(failure={
                "code": "NonZeroExitError",
                "message": f"mmCIF parse / PDB derivation failed: {e}",
            })
        coord_map = _build_coordinate_id_map(structure)
        coord_map_path.write_text(json.dumps(coord_map, indent=2, sort_keys=True))
        outputs.append({
            "artifact_uri": f"local://{coord_map_path}",
            "content_hash": sha256_text(coord_map_path.read_text()),
            "role": "coordinate_id_map",
        })

        # In strict-config-required (or any) mode, if topology-affecting
        # residues collide, refuse to proceed. v0 enforces full coordinate
        # injectivity per the R5 nitpick #1.
        if coord_map["injectivity"] != "verified":
            return StepOutcome(
                failure={
                    "code": "CoordinateIdMapNotInjective",
                    "message": "derived PDB residue identifiers are not injective; mmCIF→PDB bridge would map ambiguously",
                    "context": {"lossy_diff": coord_map.get("lossy_diff", [])[:10]},
                },
                outputs=outputs,
            )

        outputs.append({
            "artifact_uri": f"local://{derived_pdb_path}",
            "content_hash": sha256_file(derived_pdb_path),
            "role": "derived_pdb",
        })
        # The working.pdb is the derived PDB (possibly stripped) — same path.
        source_for_working = derived_pdb_path
    else:
        # PDB ingest — source for working == original.
        source_for_working = original_path

    # ---- Tutorial-mode HETATM strip.
    raw_lines = source_for_working.read_text().splitlines(keepends=True)
    if pipeline_mode == "tutorial_reproduction":
        working_lines = [ln for ln in raw_lines if not ln.startswith("HETATM")]
        n_stripped = sum(1 for ln in raw_lines if ln.startswith("HETATM"))
    else:
        working_lines = raw_lines
        n_stripped = 0
    working_path.write_text("".join(working_lines))
    outputs.append({
        "artifact_uri": f"local://{working_path}",
        "content_hash": sha256_file(working_path),
        "role": "working_pdb",
    })

    return StepOutcome(
        outputs=outputs,
        extra={
            "source": "rcsb" if pdb_id else "local",
            "pdb_id": pdb_id,
            "format": fmt,
            "n_hetatm_stripped": n_stripped,
        },
    )
