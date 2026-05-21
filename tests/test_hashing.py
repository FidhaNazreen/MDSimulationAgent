"""Hashing utility tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from mdagent.hashing import (
    canonical_json,
    sha256_bytes,
    sha256_concat,
    sha256_dir,
    sha256_file,
    sha256_json,
    sha256_source_files,
    sha256_text,
)

KNOWN_EMPTY = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def test_sha256_bytes_empty() -> None:
    assert sha256_bytes(b"") == KNOWN_EMPTY


def test_sha256_text_matches_bytes() -> None:
    assert sha256_text("hello") == sha256_bytes(b"hello")


def test_canonical_json_is_stable() -> None:
    j1 = canonical_json({"b": 2, "a": 1, "c": [3, 1, 2]})
    j2 = canonical_json({"a": 1, "b": 2, "c": [3, 1, 2]})
    assert j1 == j2 == '{"a":1,"b":2,"c":[3,1,2]}'


def test_sha256_json_is_order_independent() -> None:
    assert sha256_json({"a": 1, "b": 2}) == sha256_json({"b": 2, "a": 1})
    assert sha256_json({"a": 1, "b": 2}) != sha256_json({"a": 2, "b": 1})


def test_sha256_file_round_trip(tmp_path: Path) -> None:
    p = tmp_path / "f.txt"
    p.write_text("hello")
    assert sha256_file(p) == sha256_text("hello")


def test_sha256_dir_deterministic(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("alpha")
    (tmp_path / "b.txt").write_text("bravo")
    h1 = sha256_dir(tmp_path)
    h2 = sha256_dir(tmp_path)
    assert h1 == h2


def test_sha256_dir_changes_with_content(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("alpha")
    h1 = sha256_dir(tmp_path)
    (tmp_path / "a.txt").write_text("ALPHA")
    h2 = sha256_dir(tmp_path)
    assert h1 != h2


def test_sha256_dir_changes_with_added_file(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("alpha")
    h1 = sha256_dir(tmp_path)
    (tmp_path / "b.txt").write_text("bravo")
    h2 = sha256_dir(tmp_path)
    assert h1 != h2


def test_sha256_dir_rejects_non_dir(tmp_path: Path) -> None:
    p = tmp_path / "f.txt"
    p.write_text("x")
    with pytest.raises(ValueError):
        sha256_dir(p)


def test_sha256_concat_validates_hex() -> None:
    with pytest.raises(ValueError):
        sha256_concat("notahex")


def test_sha256_concat_is_order_sensitive() -> None:
    a, b = "a" * 64, "b" * 64
    assert sha256_concat(a, b) != sha256_concat(b, a)


def test_sha256_source_files_deterministic(tmp_path: Path) -> None:
    (tmp_path / "x.py").write_text("print(1)")
    (tmp_path / "y.py").write_text("print(2)")
    paths = [tmp_path / "y.py", tmp_path / "x.py"]
    h1 = sha256_source_files(paths)
    h2 = sha256_source_files(reversed(paths))
    assert h1 == h2  # sorted internally
