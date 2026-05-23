"""Tests for the tutorial-bundle pipeline (markdown → notebook → PDF)."""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

import nbformat
import pytest

from mdagent.cli import main as cli_main
from mdagent._resources.tutorials._build import build as build_mod


# ---- Fast unit tests --------------------------------------------------


def test_strip_directives_extracts_metadata():
    text = """<!-- mdagent:title My Tutorial -->
<!-- mdagent:requires mdagent,gromacs -->

# Heading

Some prose.
"""
    from mdagent._resources.tutorials._build.build import TutorialMeta, _strip_directives
    meta = TutorialMeta()
    cleaned, pending = _strip_directives(text, meta)
    assert meta.title == "My Tutorial"
    assert meta.requires == ["mdagent", "gromacs"]
    assert "<!-- mdagent:" not in cleaned
    assert "# Heading" in cleaned


def test_strip_directives_cell_tag_pending():
    text = """Prose.

<!-- mdagent:cell-tag requires-gmx -->
```python
print("hello")
```
"""
    from mdagent._resources.tutorials._build.build import TutorialMeta, _strip_directives
    meta = TutorialMeta()
    cleaned, pending = _strip_directives(text, meta)
    # pending_tags carries (line_index, [tags]) entries
    assert pending, pending
    assert "requires-gmx" in pending[0][1]


def test_split_blocks_python_and_bash():
    text = """Prose markdown.

```python
print("py")
```

More prose.

```bash
echo "sh"
```

Closing prose.
"""
    blocks = build_mod._split_blocks(text, [])
    kinds = [b.kind for b in blocks]
    # Expect: markdown, code(python), markdown, code(bash), markdown
    assert kinds == ["markdown", "code", "markdown", "code", "markdown"]
    assert blocks[1].source.strip() == 'print("py")'
    # Bash gets a %%bash prefix.
    assert blocks[3].source.startswith("%%bash\n")
    assert "echo" in blocks[3].source


def test_split_blocks_leaves_non_python_fences_in_markdown():
    """Fenced code without language=python|bash stays inside the markdown cell."""
    text = """Prose.

```json
{"a": 1}
```

End prose.
"""
    blocks = build_mod._split_blocks(text, [])
    assert all(b.kind == "markdown" for b in blocks)
    # Original fence content is preserved.
    assert any("```json" in b.source for b in blocks)


def test_build_notebook_emits_preface_and_validates():
    text = """<!-- mdagent:title Demo -->
<!-- mdagent:requires mdagent -->

# Demo

```python
1 + 1
```
"""
    nb = build_mod.build_notebook(text)
    nbformat.validate(nb)
    # First cell is the preface markdown.
    assert nb.cells[0].cell_type == "markdown"
    assert "shipped without output" in nb.cells[0].source.lower() or "About this notebook" in nb.cells[0].source
    # Python cell present.
    assert any(c.cell_type == "code" and c.source.strip() == "1 + 1" for c in nb.cells)


def test_every_packaged_tutorial_builds_a_valid_notebook(tmp_path: Path):
    """Build all 8 packaged tutorials into a tmp dir; nbformat.validate each."""
    src = build_mod.__file__
    src_dir = Path(src).parent.parent  # _build/build.py -> _build -> tutorials
    payload = build_mod.build_all(
        source=src_dir,
        out=tmp_path,
        notebooks=True,
        pdf=False,
    )
    assert payload["notebooks_written"], payload
    assert len(payload["notebooks_written"]) == 8, payload  # tutorials 01..08
    for ipynb_path in payload["notebooks_written"]:
        nb = nbformat.read(ipynb_path, as_version=4)
        nbformat.validate(nb)
        for cell in nb.cells:
            if cell.cell_type != "code":
                continue
            src_text = cell.source
            if src_text.startswith("%%bash"):
                continue  # cell magic; not Python
            # Compile to catch syntax errors.
            compile(src_text, ipynb_path, "exec")


def test_tutorial_md_files_skip_readme():
    """build_all only processes NN_*.md files; README.md / _* are skipped."""
    from mdagent._resources.tutorials._build.build import _TUTORIAL_MD_RE
    assert _TUTORIAL_MD_RE.match("01_getting_started.md")
    assert _TUTORIAL_MD_RE.match("08_failure_triage.md")
    assert not _TUTORIAL_MD_RE.match("README.md")
    assert not _TUTORIAL_MD_RE.match("_build_notes.md")


# ---- CLI: extract -----------------------------------------------------


def test_tutorials_extract_materializes_bundle(tmp_path: Path):
    rc = cli_main(["tutorials", "extract", str(tmp_path)])
    assert rc == 0
    # 8 markdown + 8 notebooks + README + _shared/pdf.css + _build/build.py
    md_files = sorted(p.name for p in tmp_path.glob("*.md"))
    ipynb_files = sorted(p.name for p in tmp_path.glob("*.ipynb"))
    assert "README.md" in md_files
    assert len([n for n in md_files if n[:3].rstrip("_").isdigit() or n[:2].isdigit()]) == 8
    assert len(ipynb_files) == 8
    assert (tmp_path / "_shared" / "pdf.css").is_file()
    assert (tmp_path / "_build" / "build.py").is_file()
    # No __pycache__ should sneak in.
    assert not any("__pycache__" in str(p) for p in tmp_path.rglob("*"))
    # No __init__.py either (they're package markers, not bundle files).
    assert not list(tmp_path.glob("**/__init__.py"))


def test_tutorials_extract_refuses_non_empty_without_force(tmp_path: Path):
    (tmp_path / "preexisting.txt").write_text("keep me")
    rc = cli_main(["tutorials", "extract", str(tmp_path)])
    assert rc != 0
    assert (tmp_path / "preexisting.txt").read_text() == "keep me"
    assert not list(tmp_path.glob("*.ipynb"))


def test_tutorials_extract_force_overwrites_bundle_files_only(tmp_path: Path):
    (tmp_path / "preexisting.txt").write_text("keep me")
    rc = cli_main(["tutorials", "extract", "--force", str(tmp_path)])
    assert rc == 0
    assert (tmp_path / "preexisting.txt").read_text() == "keep me"  # untouched
    assert (tmp_path / "01_getting_started.md").is_file()


# ---- CLI: build -------------------------------------------------------


def test_tutorials_build_subcommand(tmp_path: Path):
    """`mdagent tutorials build --source src --out out` rebuilds notebooks."""
    # First extract into a working dir.
    work = tmp_path / "work"
    cli_main(["tutorials", "extract", str(work)])
    # Delete the auto-generated notebooks and rebuild.
    for ipynb in work.glob("*.ipynb"):
        ipynb.unlink()
    rc = cli_main(["tutorials", "build", "--source", str(work), "--out", str(work)])
    assert rc == 0
    assert len(list(work.glob("*.ipynb"))) == 8


# ---- PDF (optional; skipped if weasyprint or its native libs are missing) --


@pytest.mark.skipif(
    importlib.util.find_spec("weasyprint") is None or importlib.util.find_spec("markdown_it") is None,
    reason="weasyprint or markdown-it-py not installed",
)
def test_pdf_round_trip_for_one_tutorial(tmp_path: Path):
    """Build one PDF from a packaged tutorial; assert it starts with %PDF-.

    Skipped if the OS doesn't have pango/cairo (the underlying RuntimeError
    is caught explicitly so the test is informative, not flaky)."""
    text = """<!-- mdagent:title PDF Round Trip -->

# Heading

Some prose with a table:

| A | B |
|---|---|
| 1 | 2 |

```python
print("x")
```
"""
    try:
        pdf_bytes = build_mod.build_pdf(text, src_filename="x.md")
    except RuntimeError as e:
        pytest.skip(f"weasyprint native libs unavailable: {e}")
    assert pdf_bytes[:4] == b"%PDF"
    assert len(pdf_bytes) > 1000  # not a stub
