# mdagent tutorials

A self-contained walkthrough for using the `mdagent` CLI + Claude
skills to run molecular-dynamics simulations from natural-language
prompts.

Each tutorial below ships in three formats:

- `.md` — the canonical source (what you're reading).
- `.ipynb` — the same content as a runnable Jupyter notebook
  (generated from the markdown; cells ship without output).
- `.pdf` — optional offline-readable copy (generated on demand with
  `mdagent tutorials build --pdf`; requires the `tutorials` extra).

## Quick install

```bash
brew install uv     # macOS — or: curl -LsSf https://astral.sh/uv/install.sh | sh
uv tool install --force "mdagent[tutorials] @ git+https://github.com/FidhaNazreen/MDSimulationAgent@v0.1.0"
brew install gromacs    # for any tutorial that exercises the pipeline
mdagent install-skills --user
```

## Tutorial index

| # | Tutorial | Requires | What you'll learn |
|---|---|---|---|
| 1 | `01_getting_started` | mdagent only | Install → first run → reading the report |
| 2 | `02_claude_code_workflow` | mdagent only | How Claude Code discovers + invokes the skills |
| 3 | `03_configs_and_modes` | mdagent + GROMACS | `tutorial_reproduction` vs `general_md_prep`; the config knob table |
| 4 | `04_reading_outputs` | mdagent only | Run-directory anatomy; consuming `analysis.json`; downstream tools |
| 5 | `05_advanced_propka` | mdagent + GROMACS + PROPKA | pKa-aware protonation; HIS-15 at pH 7 vs pH 5 |
| 6 | `06_visualization` | mdagent + GROMACS + (VMD or PyMOL) | Rendering snapshots; script-vs-render mode |
| 7 | `07_resume_and_invalidation` | mdagent + GROMACS | Resume after crash; fingerprint-driven invalidation |
| 8 | `08_failure_triage` | mdagent only | Reading failure codes; common remedies |

## Recommended path

Read them in order. Tutorial 1 takes ~3 minutes; tutorials 3, 5, 6, 7
include a real MD run each (~2 min on an M-series laptop with the
short config).

## Move this bundle to a fresh repository

```bash
# 1. Materialize the tutorials into an empty directory:
mdagent tutorials extract ./my-tutorials-repo --with-pdf

# 2. (Optional) also scaffold a fully-runnable project alongside them:
mdagent init-project ./my-tutorials-repo

# 3. Initialize git and push:
cd my-tutorials-repo
git init && git add . && git commit -m "scaffold: tutorials + project"
```
