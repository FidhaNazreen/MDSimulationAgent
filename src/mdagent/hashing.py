"""Content-hashing utilities. All hashes are sha256 hex (64 lowercase chars)."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable

_CHUNK = 1 << 20  # 1 MiB


def sha256_file(path: str | os.PathLike[str]) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(_CHUNK):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_dir(root: str | os.PathLike[str]) -> str:
    """Recursive directory content hash.

    Iterates every regular file under root in sorted (relative-path) order
    and hashes the concatenation of `<relpath>\\0<file_hash>\\n`. Symlinks
    and special files are skipped — a hash of a directory containing only
    symlinks is the empty-hash.
    """
    root = Path(root)
    if not root.is_dir():
        raise ValueError(f"sha256_dir: not a directory: {root}")
    h = hashlib.sha256()
    files: list[tuple[str, Path]] = []
    for p in root.rglob("*"):
        if p.is_file() and not p.is_symlink():
            rel = p.relative_to(root).as_posix()
            files.append((rel, p))
    files.sort(key=lambda x: x[0])
    for rel, p in files:
        h.update(rel.encode("utf-8"))
        h.update(b"\x00")
        h.update(sha256_file(p).encode("ascii"))
        h.update(b"\n")
    return h.hexdigest()


def canonical_json(obj: Any) -> str:
    """Canonical JSON: sorted keys, no whitespace. Stable hash inputs."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_json(obj: Any) -> str:
    return sha256_text(canonical_json(obj))


def sha256_concat(*hex_hashes: str) -> str:
    """Composite hash of an ordered list of sha256 hex strings.

    Used to build composite fingerprints from component hashes.
    """
    h = hashlib.sha256()
    for x in hex_hashes:
        if len(x) != 64 or not all(c in "0123456789abcdef" for c in x):
            raise ValueError(f"sha256_concat: not a sha256 hex: {x!r}")
        h.update(x.encode("ascii"))
        h.update(b"\n")
    return h.hexdigest()


def sha256_source_files(paths: Iterable[str | os.PathLike[str]]) -> str:
    """Hash a fixed set of source files, sorted by absolute path."""
    items = sorted(str(Path(p).resolve()) for p in paths)
    h = hashlib.sha256()
    for absp in items:
        h.update(absp.encode("utf-8"))
        h.update(b"\x00")
        h.update(sha256_file(absp).encode("ascii"))
        h.update(b"\n")
    return h.hexdigest()
