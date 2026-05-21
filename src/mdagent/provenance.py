"""Provenance helpers: capture tool versions and FF directory hashes.

Builds the `resolved_tool_components` dicts that `compute_step_fingerprint`
expects, keyed by the same names that `step_definitions.json` declares.
"""

from __future__ import annotations

import os
import subprocess
from functools import lru_cache
from pathlib import Path

from .hashing import sha256_dir, sha256_text


@lru_cache(maxsize=None)
def gmx_version_stdout() -> str:
    """Return the trimmed `gmx --version` stdout. Hashable, cacheable."""
    out = subprocess.run(["gmx", "--version"], capture_output=True, text=True)
    return out.stdout


@lru_cache(maxsize=None)
def gmx_data_prefix() -> Path:
    """Resolve the GROMACS data prefix (the directory containing top/, share/, ...).

    Parses `Data prefix:` from `gmx --version`.
    """
    for line in gmx_version_stdout().splitlines() + subprocess.run(
        ["gmx", "--version"], capture_output=True, text=True
    ).stderr.splitlines():
        line = line.strip()
        if line.startswith("Data prefix:"):
            return Path(line.split(":", 1)[1].strip())
    raise RuntimeError("could not parse 'Data prefix:' from `gmx --version`")


def ff_dir_for(ff_name: str) -> Path:
    """Return the absolute path to a force-field directory like 'oplsaa.ff'."""
    candidate = gmx_data_prefix() / "share" / "gromacs" / "top" / f"{ff_name}.ff"
    if not candidate.is_dir():
        raise FileNotFoundError(f"force field dir not found: {candidate}")
    return candidate


def ff_dir_hash(ff_name: str) -> str:
    return sha256_dir(ff_dir_for(ff_name))


def topology_tool_components(*, ff_name: str, transcript_catalog_hash: str, dialogue_runner_code_hash: str) -> dict[str, str]:
    return {
        "tool_versions.gromacs": sha256_text(gmx_version_stdout()),
        "ff_dir_recursive_hash": ff_dir_hash(ff_name),
        "transcript_catalog_hash": transcript_catalog_hash,
        "dialogue_runner_code_hash": dialogue_runner_code_hash,
    }


def solvation_tool_components(
    *,
    ff_name: str,
    water_include_hash: str,
    ion_include_hash: str,
) -> dict[str, str]:
    return {
        "tool_versions.gromacs": sha256_text(gmx_version_stdout()),
        "ff_dir_recursive_hash": ff_dir_hash(ff_name),
        "water_model_include_hash": water_include_hash,
        "ion_include_hash": ion_include_hash,
    }


def em_tool_components(*, ff_name: str, em_mdp_template_hash: str) -> dict[str, str]:
    return {
        "tool_versions.gromacs": sha256_text(gmx_version_stdout()),
        "ff_dir_recursive_hash": ff_dir_hash(ff_name),
        "em_mdp_template_hash": em_mdp_template_hash,
    }


def stub_components(declared: list[str]) -> dict[str, str]:
    """For steps whose tool components we haven't wired up yet, stub each
    declared component to a stable placeholder. Lets the orchestrator move
    forward while preserving the invalidation contract (the placeholder
    won't change, so unchanged tools won't trigger spurious invalidation).
    """
    return {name: sha256_text(f"stub::{name}") for name in declared}


def hash_file_contents(path: str | os.PathLike[str]) -> str:
    from .hashing import sha256_file
    return sha256_file(path)
