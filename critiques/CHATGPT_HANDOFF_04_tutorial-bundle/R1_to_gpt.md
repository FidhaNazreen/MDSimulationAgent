# Round 1 handoff: shipping-ready tutorial bundle (notebooks + PDFs + markdown)

---

## Section 1 — Context bundle

### What already exists

  - `tutorial/MD_simulation_with_agents.ipynb` — a 24-cell developer
    notebook regenerated from `tutorial/build_tutorial.py` via
    `nbformat`. Lives in the repo root, references `mdagent ...`
    invocations. NOT inside the wheel.
  - `src/mdagent/_resources/starter_kit/tutorial/getting_started.md`
    — a markdown tutorial shipped inside the wheel + materialized by
    `mdagent init-project DIR`.
  - 3 Claude skills, 13 example configs, validation script, bundled
    1AKI structure — all in the starter kit, exposed via
    `mdagent init-project`.
  - `mdagent init-project DIR` already produces a clean new-repo
    scaffold with skills + configs + a verify script.

### What the user wants now

> "Make tutorials for how to use these skills and agents for doing MD
> simulations either using python notebooks and pdfs. Finally make
> them shipping ready so that I can move it to a different repository
> cleanly with just the required files."

Concretely:
  1. **Multiple tutorial formats** — notebook (interactive) + PDF
     (offline-readable) at minimum; markdown likely as the source of
     truth.
  2. **Shipping ready** — a folder you can `cp -r` (or
     `mdagent ...`-materialize) into a brand-new git repo and `git init`.
  3. **No drift** — the three formats should derive from one source,
     not be hand-maintained separately.

### Current PDF / notebook tooling

  - `nbformat` is already a dev dep — we use it to build the
    notebook.
  - `nbconvert`, `pandoc`, `weasyprint`, `wkhtmltopdf`, `chromium`,
    `Chrome` — none are currently installed. PDF generation requires
    adding one.
  - Notebook execution (running cells to produce output) requires
    `jupyter` / `ipykernel`.

### Constraints

  - `mdagent` is a `uv`-installable Python package. Shipping
    user-runnable artifacts is the norm; pre-generated PDFs would be
    optional convenience.
  - Tutorials should run against the same `mdagent` install — no
    forks of the example configs / structures / commands.
  - macOS is the primary platform; Linux must also work. Windows is
    out-of-scope (per slice 9 decision).
  - The user is comfortable with `uv` and the CLI. We don't need to
    teach them Python tooling.

---

## Section 2 — Artifact under review

### 2.1 Proposed source-of-truth model

A new directory in the wheel:

```
src/mdagent/_resources/tutorials/
├── _build/                       # Python script that builds notebooks + PDFs from .md
│   └── build.py                  # uses nbformat to make .ipynb; uses weasyprint to make PDF
├── 01_getting_started.md         # canonical
├── 02_claude_code_workflow.md
├── 03_configs_and_modes.md
├── 04_reading_outputs.md
├── 05_advanced_propka.md         # PROPKA + general_md_prep
├── 06_visualization.md
├── 07_resume_and_invalidation.md
├── 08_failure_triage.md
├── README.md                     # index linking everything
└── _shared/                      # CSS for HTML→PDF rendering, etc.
    └── pdf.css
```

Each `.md` is the **single source of truth**. The build script
`build.py` does two things:

  1. `markdown → ipynb`: walks the `.md`, splits on H2 headings or
     code fences, emits one cell per chunk. Markdown blocks become
     markdown cells; fenced ```python / ```bash blocks become code
     cells. The result is committed AND regeneratable.
  2. `markdown → HTML → PDF`: renders the `.md` via Python `markdown`
     (or `markdown-it-py`), wraps in `_shared/pdf.css`, hands to
     WeasyPrint. The PDFs are NOT committed; they're built on demand.

### 2.2 New CLI subcommand

```
mdagent tutorials build [--out DIR] [--pdf] [--notebooks]
mdagent tutorials extract DIR [--with-pdf]
```

  - `tutorials build`: regenerate the `.ipynb` files (and optionally
    PDFs) in-place inside the package (development hook).
  - `tutorials extract DIR`: copy the whole tutorial bundle into DIR.
    Markdown + notebooks always; PDFs only if `--with-pdf` (because
    PDFs require the `tutorials` extra to be installed).

### 2.3 What ships in the wheel

  - The eight `.md` files (canonical).
  - The eight regenerated `.ipynb` files (frozen versions, regenerated
    by `mdagent tutorials build` at release time).
  - `_build/build.py` (so users can regenerate locally if they edit).
  - `_shared/pdf.css`.
  - **PDFs do NOT ship in the wheel** — regenerated on demand by the
    user via `mdagent tutorials build --pdf` after they install the
    `tutorials` extra.

### 2.4 The `tutorials` optional extra

Pinned PDF dep stack:
  - `weasyprint>=60` (pure-Python; OS deps via wheels).
  - `markdown-it-py>=3` (md → HTML).

Installed via:
```
uv tool install --force --with tutorials git+https://...@v0.1.0
```

### 2.5 Tutorial content scope (the 8 files)

1. **01_getting_started.md** — install → first run → reading the
   report. ~3 min read; mirrors the current starter-kit content.
2. **02_claude_code_workflow.md** — how Claude Code finds and uses
   the skills; example natural-language prompts; what the user vs.
   Claude does.
3. **03_configs_and_modes.md** — `tutorial_reproduction` vs.
   `general_md_prep`; the config knob table; how to write a config
   for an arbitrary PDB.
4. **04_reading_outputs.md** — anatomy of the run directory; how to
   consume `analysis.json`; what each `.xvg` / `.xtc` is for;
   downstream analysis with MDAnalysis.
5. **05_advanced_propka.md** — when to use PROPKA-driven protonation,
   how pKa vs. pH controls per-residue answers, walking through the
   HIS-15 example.
6. **06_visualization.md** — VMD / PyMOL / NGLview options; script
   vs. render mode; how to render later if no viewer is installed.
7. **07_resume_and_invalidation.md** — how to resume a crashed run;
   how config drift triggers fingerprint invalidation; how to read
   `step_fingerprint.json`.
8. **08_failure_triage.md** — failure code taxonomy; what each code
   means; where to look; common remedies.

Plus `README.md` (index linking everything in order).

### 2.6 How "shipping ready" is achieved

```bash
# In a fresh empty repo:
mdagent tutorials extract . --with-pdf
git init
git add .
git commit -m "scaffold tutorials from mdagent"
```

The resulting tree:
```
my-new-repo/
├── README.md                    # this is the bundle's index
├── 01_getting_started.md
├── 01_getting_started.ipynb
├── 01_getting_started.pdf       # if --with-pdf
├── 02_claude_code_workflow.md
├── ... (all 8)
├── _shared/pdf.css
└── _build/build.py              # so the user can regen if they edit
```

No `.claude/skills/` — that's `init-project`'s job. But the
`README.md` points at `mdagent install-skills --project .` and at
`mdagent init-project` if the user wants both tutorial + project
scaffolding.

### 2.7 Open questions

1. **PDF generator choice** — WeasyPrint (pure Python, no system
   deps once wheels install) vs. pandoc+LaTeX (better quality, heavy
   system deps) vs. nbconvert+chrome (requires playwright/chromium).
   I lean WeasyPrint for installability.
2. **Should we run the notebooks** to produce output cells before
   shipping? That requires `jupyter` / `ipykernel` AND
   `mdagent run-workflow` actually executing during build (which
   needs GROMACS). I lean: ship notebooks with empty output cells;
   user runs them locally.
3. **Should each tutorial's code cells actually be self-contained
   (no shared state)** so a reader can run any one cell in isolation?
   Or sequential (cell 5 depends on cell 3)? I lean: sequential
   within a tutorial; tutorials independent of each other.
4. **Do we need an executable orchestrator** (a single script that
   walks the whole tutorial in order, like
   `mdagent tutorials run 01_getting_started`)? Or is "open the
   notebook in Jupyter and click run" enough? I lean: the latter.
5. **Bundle in the wheel or separate "starter" branch?** I lean
   wheel (matches slices 9, 10 — single install source).
6. **PDF generation determinism** — WeasyPrint output isn't
   byte-identical across versions / OSes / font sets. Should PDFs be
   in `.gitignore` for extracted bundles? I lean yes (don't commit
   them; regenerate on demand).
7. **`build.py` location** — inside the package (so users can call
   the same build that `mdagent tutorials build` runs), or just in
   the repo's `tutorial/` dir? I lean: inside the package so
   `mdagent tutorials build --out DIR` always uses the same renderer.
8. **`mdagent init-project` and `mdagent tutorials extract`** — are
   these too similar? Should `init-project` get a `--with-tutorials`
   flag instead of a separate subcommand? I lean: separate
   subcommand because the use cases are different (project scaffold
   vs. tutorial deliverable).
9. **Notebook code cells calling `subprocess.run(["mdagent", ...])`
   vs. importing `mdagent.run_workflow`** — subprocess is closer to
   the user's actual experience; imports are faster + show
   intermediate state. I lean: subprocess for "user-facing" tutorials
   (01, 02, 03), imports for "developer/advanced" tutorials (04+).
10. **Conflict with the existing developer notebook** at
    `tutorial/MD_simulation_with_agents.ipynb` — should that be
    deleted, kept as "developer notes," or rewritten to point at the
    new tutorial bundle?

---

## Section 3 — Critique prompt

You are an adversarial reviewer. Be critical. Be argumentative.
Find every hole. For each issue: WHAT is wrong (specific) / WHY it
matters / WHAT to do.

Number your issues. End with exactly one of:

  VERDICT: APPROVED
  VERDICT: ISSUES_REMAIN

`APPROVED` if there are no blocking holes; nitpicks alone don't justify
`ISSUES_REMAIN`.

Specifically:

**P1.** Of the 10 open questions in Section 2.7, which 2-3 are actually
load-bearing for v0 — i.e. if I get them wrong, the bundle doesn't
ship cleanly — vs. nitpicks?

**P2.** WeasyPrint is the lightest-install PDF generator I know of.
Is there a better choice given the constraints (macOS + Linux, no
heavy system deps, deterministic-enough output)?

**P3.** Is the "markdown is canonical → build notebook + PDF" model
the right source-of-truth design? Or should the **notebook** be
canonical (since it's what users actually run) with markdown + PDF
derived?
