"""Tutorial-bundle build pipeline.

Markdown (.md) is canonical. This script:

  1. Reads each .md.
  2. Strips ``<!-- mdagent:directive -->`` HTML comments AND consumes
     them into cell-level metadata.
  3. Splits the body into alternating markdown blocks and code fences
     (``` ```python ` → code cell; ``` ```bash ` → ``%%bash`` cell).
  4. Emits a Jupyter notebook (.ipynb) via ``nbformat``.
  5. Optionally renders a PDF via WeasyPrint (lazy import; not
     required for notebook generation).

Authoring contract:

  - ``` ```python ``` blocks become Python code cells.
  - ``` ```bash ``` blocks become Python code cells with ``%%bash``
    cell magic prepended.
  - All other fenced code blocks (``text``, ``json``, ``yaml``, no
    language) stay in the markdown cell as-is.
  - ``<!-- mdagent:requires <comma,list> -->``      — front-matter
    requirements list; renders a badge.
  - ``<!-- mdagent:title <title> -->``              — overrides the
    notebook title (default: first H1).
  - ``<!-- mdagent:cell-tag <tag> -->``             — adds a tag to
    the NEXT cell (markdown or code).
  - ``<!-- mdagent:kernel <kernelname> -->``        — sets the
    notebook kernel name (default: ``python3``).

This script is runnable standalone:

    python _build/build.py --source <DIR> --out <DIR> [--notebooks] [--pdf]

The mdagent CLI exposes the same behavior via:

    mdagent tutorials build --source DIR --out DIR [--notebooks] [--pdf]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# nbformat is a dev dep and a tutorials-extra dep; it's also fine in the
# base install for users running `mdagent tutorials build --notebooks`.
import nbformat

# Match `<!-- mdagent:KEY VALUE... -->`. VALUE captures everything to the
# closing comment minus surrounding whitespace.
_DIRECTIVE_RE = re.compile(r"<!--\s*mdagent:(?P<key>\S+)(?:\s+(?P<value>.+?))?\s*-->")

# Match opening ``` of a fenced block: capture the language (or empty).
_FENCE_OPEN_RE = re.compile(r"^```(\w*)\s*$")
_FENCE_CLOSE_RE = re.compile(r"^```\s*$")


@dataclass
class Block:
    kind: str             # 'markdown' | 'code'
    lang: str = ""        # for code: 'python' | 'bash' | other
    source: str = ""
    tags: list[str] = field(default_factory=list)


@dataclass
class TutorialMeta:
    title: str = ""
    kernel: str = "python3"
    requires: list[str] = field(default_factory=list)


def _strip_directives(text: str, meta: TutorialMeta) -> tuple[str, list[tuple[int, list[str]]]]:
    """Remove directives from `text` and consume them.

    Returns (cleaned_text, pending_tags) where `pending_tags` is a list
    of (line_index, [tag, ...]) collected from `cell-tag` directives —
    they attach to the NEXT non-empty cell encountered after that line.
    """
    pending_tags: list[tuple[int, list[str]]] = []
    cleaned_lines: list[str] = []
    for i, line in enumerate(text.splitlines()):
        m = _DIRECTIVE_RE.search(line)
        if m:
            key = m.group("key")
            value = (m.group("value") or "").strip()
            if key == "title":
                meta.title = value
            elif key == "kernel":
                meta.kernel = value
            elif key == "requires":
                meta.requires = [v.strip() for v in value.split(",") if v.strip()]
            elif key == "cell-tag":
                pending_tags.append((len(cleaned_lines), [t.strip() for t in value.split(",") if t.strip()]))
            # else: unknown directive — silently drop (forward compatibility)
            # Remove the directive from the line; if the line is now blank, drop it entirely.
            stripped_line = _DIRECTIVE_RE.sub("", line).rstrip()
            if stripped_line:
                cleaned_lines.append(stripped_line)
            # else: skip the now-empty line entirely
        else:
            cleaned_lines.append(line)
    return "\n".join(cleaned_lines), pending_tags


def _split_blocks(text: str, pending_tags: list[tuple[int, list[str]]]) -> list[Block]:
    """Walk lines; emit Block(markdown) until a code fence opens, then
    Block(code) until the matching close, alternating."""
    blocks: list[Block] = []
    current_md: list[str] = []
    in_code = False
    code_lang = ""
    code_buf: list[str] = []

    pending_idx = 0
    queued_tags: list[str] = []

    def maybe_consume_tags_for_line(line_no: int) -> None:
        nonlocal pending_idx, queued_tags
        while pending_idx < len(pending_tags) and pending_tags[pending_idx][0] <= line_no:
            queued_tags.extend(pending_tags[pending_idx][1])
            pending_idx += 1

    for ln, raw in enumerate(text.splitlines()):
        if not in_code:
            m = _FENCE_OPEN_RE.match(raw.strip())
            if m:
                # Flush any accumulated markdown
                if current_md:
                    md_source = "\n".join(current_md).strip("\n")
                    if md_source:
                        maybe_consume_tags_for_line(ln)
                        b = Block(kind="markdown", source=md_source)
                        b.tags = queued_tags
                        queued_tags = []
                        blocks.append(b)
                    current_md = []
                code_lang = m.group(1) or ""
                # `python` and `bash` get extracted as code cells; everything
                # else stays as a fenced markdown block.
                if code_lang in ("python", "bash"):
                    in_code = True
                    code_buf = []
                else:
                    current_md.append(raw)
            else:
                current_md.append(raw)
        else:
            if _FENCE_CLOSE_RE.match(raw.strip()):
                # Emit a code block
                src = "\n".join(code_buf)
                if code_lang == "bash":
                    src = "%%bash\n" + src
                maybe_consume_tags_for_line(ln)
                b = Block(kind="code", lang=code_lang, source=src)
                b.tags = queued_tags
                queued_tags = []
                blocks.append(b)
                in_code = False
                code_lang = ""
                code_buf = []
            else:
                code_buf.append(raw)

    # Flush trailing markdown
    if current_md:
        md_source = "\n".join(current_md).strip("\n")
        if md_source:
            maybe_consume_tags_for_line(len(text.splitlines()))
            b = Block(kind="markdown", source=md_source)
            b.tags = queued_tags
            queued_tags = []
            blocks.append(b)

    return blocks


def _preface_cell(meta: TutorialMeta) -> dict[str, Any]:
    """The "shipped without output" preface every tutorial gets."""
    requires_line = ""
    if meta.requires:
        requires_line = f"**Requirements:** {' · '.join(meta.requires)}\n\n"
    src = (
        f"> **About this notebook**\n>\n"
        f"> {requires_line}"
        "> Cells ship without output. Open in Jupyter and run them locally.\n"
        "> The companion `.md` has the same content with explanatory prose.\n"
        "> Some cells call `mdagent` / `gmx` / `vmd` — install those tools first.\n"
    )
    return nbformat.v4.new_markdown_cell(src)


def build_notebook(md_text: str, src_filename: str = "") -> nbformat.notebooknode.NotebookNode:
    meta = TutorialMeta()
    cleaned, pending_tags = _strip_directives(md_text, meta)
    blocks = _split_blocks(cleaned, pending_tags)

    nb = nbformat.v4.new_notebook()
    nb.cells = [_preface_cell(meta)]
    for b in blocks:
        if b.kind == "markdown":
            cell = nbformat.v4.new_markdown_cell(b.source)
        else:
            cell = nbformat.v4.new_code_cell(b.source)
        if b.tags:
            cell.metadata.setdefault("tags", []).extend(b.tags)
        nb.cells.append(cell)
    nb.metadata = {
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": meta.kernel},
        "language_info": {"name": "python", "version": "3.11"},
        "mdagent": {"title": meta.title, "requires": meta.requires, "source_filename": src_filename},
    }
    return nb


def _augment_macos_dyld_path() -> None:
    """On macOS, Homebrew's pango/cairo install under /opt/homebrew/lib
    or /usr/local/lib but those aren't on the default `dlopen` search
    path. WeasyPrint's ctypes-based loader fails as a result. Adding
    those prefixes to DYLD_FALLBACK_LIBRARY_PATH (which IS searched)
    fixes the load — but the env var must be set before weasyprint is
    imported, which is what this helper does."""
    import os, sys
    if sys.platform != "darwin":
        return
    existing = os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", "")
    candidates = ["/opt/homebrew/lib", "/usr/local/lib"]
    parts = existing.split(":") if existing else []
    for c in candidates:
        if Path(c).is_dir() and c not in parts:
            parts.append(c)
    if parts:
        os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = ":".join(parts)


def build_pdf(md_text: str, src_filename: str = "", css_path: Path | None = None) -> bytes:
    """Render `md_text` to a PDF via markdown-it-py + WeasyPrint (lazy imports)."""
    try:
        from markdown_it import MarkdownIt  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "PDF generation requires the `tutorials` extra (markdown-it-py): "
            "uv tool install --force 'mdagent[tutorials] @ git+...@<tag>'"
        ) from e
    _augment_macos_dyld_path()
    try:
        from weasyprint import HTML, CSS  # type: ignore
    except (ImportError, OSError) as e:
        # WeasyPrint requires native libs (pango, cairo, gobject-introspection)
        # which it tries to dlopen at import time. On macOS install via:
        #   brew install pango
        # On Debian/Ubuntu:
        #   sudo apt-get install libpango-1.0-0 libpangoft2-1.0-0
        raise RuntimeError(
            "WeasyPrint failed to load native libs. Install: "
            "macOS → `brew install pango`; "
            "Debian/Ubuntu → `sudo apt-get install libpango-1.0-0 libpangoft2-1.0-0`. "
            f"Underlying error: {e}"
        ) from e

    # Strip directives before rendering so they don't leak into HTML.
    meta = TutorialMeta()
    cleaned, _ = _strip_directives(md_text, meta)
    md = MarkdownIt("commonmark", {"html": False, "linkify": True, "typographer": True}).enable("table")
    html_body = md.render(cleaned)
    requires_line = ""
    if meta.requires:
        requires_line = (
            "<p class='requires'><strong>Requirements:</strong> "
            + " · ".join(meta.requires)
            + "</p>"
        )
    title_line = f"<h1 class='doc-title'>{meta.title}</h1>" if meta.title else ""
    full_html = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{meta.title or src_filename}</title></head><body>"
        + title_line
        + requires_line
        + html_body
        + "</body></html>"
    )
    css_args = []
    if css_path is not None and css_path.is_file():
        css_args.append(CSS(filename=str(css_path)))
    return HTML(string=full_html).write_pdf(stylesheets=css_args)


_TUTORIAL_MD_RE = re.compile(r"^\d{2}_.+\.md$")


def build_all(*, source: Path, out: Path, notebooks: bool, pdf: bool, css_path: Path | None = None) -> dict[str, Any]:
    """Build notebooks (and optionally PDFs) for every numbered tutorial markdown.

    Only files matching `NN_*.md` are built. README.md and other top-level
    markdown are intentionally skipped (they're indexes, not tutorials).
    """
    out.mkdir(parents=True, exist_ok=True)
    md_files = sorted(p for p in source.glob("*.md") if _TUTORIAL_MD_RE.match(p.name))
    written_nb: list[str] = []
    written_pdf: list[str] = []
    pdf_errors: list[str] = []
    for md in md_files:
        text = md.read_text()
        stem = md.stem
        if notebooks:
            nb = build_notebook(text, src_filename=md.name)
            dest = out / f"{stem}.ipynb"
            nbformat.write(nb, dest)
            written_nb.append(str(dest))
        if pdf:
            try:
                pdf_bytes = build_pdf(text, src_filename=md.name, css_path=css_path)
                dest = out / f"{stem}.pdf"
                dest.write_bytes(pdf_bytes)
                written_pdf.append(str(dest))
            except RuntimeError as e:  # noqa: BLE001
                pdf_errors.append(f"{md.name}: {e}")
    return {
        "source": str(source),
        "out": str(out),
        "notebooks_written": written_nb,
        "pdfs_written": written_pdf,
        "pdf_errors": pdf_errors,
    }


def _main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Build mdagent tutorial notebooks + PDFs from markdown.")
    p.add_argument("--source", required=True, help="Directory of .md tutorial files.")
    p.add_argument("--out", required=True, help="Directory to write notebooks (and PDFs) into.")
    p.add_argument("--notebooks", action="store_true", default=True)
    p.add_argument("--no-notebooks", dest="notebooks", action="store_false")
    p.add_argument("--pdf", action="store_true", default=False)
    p.add_argument("--css", help="Optional CSS file for PDF styling.")
    args = p.parse_args(argv)
    css_path = Path(args.css) if args.css else None
    if css_path is None:
        # Default: look for _shared/pdf.css alongside the source.
        candidate = Path(args.source) / "_shared" / "pdf.css"
        if candidate.is_file():
            css_path = candidate
    payload = build_all(
        source=Path(args.source),
        out=Path(args.out),
        notebooks=args.notebooks,
        pdf=args.pdf,
        css_path=css_path,
    )
    print(json.dumps(payload, indent=2))
    return 0 if not payload["pdf_errors"] else 1


if __name__ == "__main__":
    sys.exit(_main())
