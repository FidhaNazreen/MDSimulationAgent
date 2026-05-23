"""Thin wrapper over the optional `propka` library.

`propka` is shipped as an optional dependency. When it's importable we
predict per-residue pKa values; otherwise the caller falls back to
fixed pH-7 defaults.

Output schema lives at `schemas/v0.1.0/protonation_analysis.schema.json`.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any

# Residue types we care about (titratable in the standard force fields)
_TITRATABLE = frozenset({"HIS", "ASP", "GLU", "LYS", "ARG", "CYS", "TYR", "GLN"})


def propka_available() -> bool:
    try:
        import propka.run  # noqa: F401
        return True
    except ImportError:
        return False


def propka_version() -> str | None:
    try:
        from importlib.metadata import version
        return version("propka")
    except Exception:
        return None


def analyze(pdb_path: str | Path, ph: float = 7.0) -> dict[str, Any]:
    """Run PROPKA on `pdb_path` and return a JSON-schema-compliant dict.

    Raises ImportError if propka isn't installed.
    Raises RuntimeError on propka analysis failures (with the underlying
    exception chained).
    """
    import propka.run  # type: ignore

    src = Path(pdb_path)
    # propka writes scratch files next to the input by default; sandbox it.
    with tempfile.TemporaryDirectory() as td:
        sandbox = Path(td) / src.name
        sandbox.write_bytes(src.read_bytes())
        try:
            mol = propka.run.single(str(sandbox), write_pka=False)
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"propka analysis failed: {e}") from e

    # The default conformation key for a standard PDB is typically '1A'.
    conformations = list(mol.conformations.values())
    if not conformations:
        raise RuntimeError("propka returned no conformations")
    conf = conformations[0]

    residues: list[dict[str, Any]] = []
    seen: set[tuple[str, int, str]] = set()
    for grp in conf.groups:
        atom = getattr(grp, "atom", None)
        restype = getattr(grp, "residue_type", None)
        if atom is None or restype is None:
            continue
        if restype not in _TITRATABLE:
            continue
        chain = getattr(atom, "chain_id", "") or ""
        resid = int(getattr(atom, "res_num", 0))
        key = (chain, resid, restype)
        if key in seen:
            continue  # PROPKA may yield duplicate entries for multi-atom groups
        seen.add(key)
        pka = grp.pka_value
        predicted_protonated = (
            None if pka is None or pka == 99.99 else bool(pka > ph)
        )
        residues.append({
            "chain": chain,
            "resid": resid,
            "residue_type": restype,
            "pka_value": float(pka) if pka is not None else None,
            "predicted_protonated": predicted_protonated,
        })

    return {
        "schema_version": "0.1.0",
        "method": "propka",
        "propka_version": propka_version(),
        "ph_assumed": float(ph),
        "residues": residues,
        "warnings": [],
    }
