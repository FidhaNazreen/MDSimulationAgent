# Critique Session 04 — tutorial-bundle

- Started: 2026-05-23
- Round cap: 5
- Current round: 2 (final)
- Latest verdict: APPROVED (R2; 8 non-blocking nits)
- Round counts: R1=15, R2=APPROVED
- Codex session ID: 019e540e-3d15-7700-995a-988e478ddd6e
- Output dir: /Users/manu_jay/git_repos/MDSimulationAgent/critiques/CHATGPT_HANDOFF_04_tutorial-bundle
- Status: complete

## Pinned decisions from the loop

- Markdown is canonical; `.ipynb` and `.pdf` are derived.
- `build` operates on explicit `--source`/`--out` dirs; never writes inside the package.
- `extract` is a pure copy; `--with-pdf` runs build *after* extraction in the target.
- `markdown-it-py` + `weasyprint` are LAZY imports inside the PDF path only — base notebook extraction must work without the `tutorials` extra.
- Authoring contract: ` ```python ` → Python cell; ` ```bash ` → `%%bash` cell (auto-prepended); all other fences stay in markdown; `<!-- mdagent:directive -->` HTML comments carry cell tags / kernel / requires metadata, STRIPPED before rendering.
- Every generated notebook prepends a "shipped without output" preface cell.
- Old `tutorial/MD_simulation_with_agents.ipynb` + `build_tutorial.py` are DELETED after a repo-wide reference check.
- New CLI: `mdagent tutorials extract DIR [--with-pdf] [--force]` and `mdagent tutorials build --source DIR --out DIR [--pdf] [--notebooks]`.
