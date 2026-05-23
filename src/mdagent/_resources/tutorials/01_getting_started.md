<!-- mdagent:requires mdagent -->
<!-- mdagent:title Getting started with mdagent -->

# 01 — Getting started

**Requirements:** mdagent only (GROMACS optional for §3).
**Time:** ~3 minutes to read; ~2 minutes if you run the smoke test.

This tutorial walks you from a fresh machine to running an MD
preparation workflow on hen-egg-white lysozyme — driven by a
natural-language prompt to Claude Code, or equivalently by one CLI
invocation.

## 1. Install once per machine

```bash
brew install uv
uv tool install --force "mdagent[tutorials] @ git+https://github.com/<user>/MDSimulationAgent@v0.1.0"
brew install gromacs
```

Verify:

```bash
mdagent --version
gmx --version | head -3
mdagent self-test resources
```

## 2. Scaffold a project

`mdagent init-project DIR` creates a self-contained directory with:

- `.claude/skills/` — the three packaged skills (Claude Code finds them automatically when you open a session here)
- `run_configs/` — three example configs (offline short, RCSB tutorial, general-mode)
- `structures/1aki.pdb` — a bundled CC0 copy of lysozyme for offline runs
- `verify.sh` — a one-command sanity check
- `tutorial/getting_started.md` — a condensed copy of this very tutorial

```python
from pathlib import Path
import subprocess, shutil

project = Path("./tutorial_demo").resolve()
if project.exists():
    shutil.rmtree(project)
subprocess.run(["mdagent", "init-project", str(project)], check=True)
print("scaffold created at:", project)
print(sorted(p.name for p in project.iterdir()))
```

## 3. Run a short MD simulation

You can drive `mdagent run-workflow` directly:

```bash
cd ./tutorial_demo
./verify.sh                     # offline structural + config check (~5 s)
./verify.sh --run-smoke         # actually runs the pipeline (~2 min)
```

`--run-smoke` invokes the full 13-step DAG against the bundled 1AKI
structure. When it finishes, you should see:

```
✓ smoke run produced 'ready' REPORT.md at runs/smoke/REPORT.md
✓ starter kit verified
```

## 4. Read the report

```python
from pathlib import Path
print((Path("./tutorial_demo/runs/smoke/REPORT.md")).read_text())
```

Expected headline: `readiness: **ready**`. The report also lists each
step's status, the system composition (1 chain, 1 HIS, 8 CYS for
lysozyme), the ion counts (8 Cl⁻, 0 Na⁺), and EM convergence
(Fmax < 1000 kJ/mol/nm).

## 5. Or just ask Claude

Open a Claude Code session in `./tutorial_demo/` and say:

> *"Set up lysozyme in water and minimize it."*

Claude reads `.claude/skills/md-run-workflow/SKILL.md`, runs the
exact pipeline above, and surfaces the REPORT.md verbatim. You don't
need to know any of the CLI flags.

## Next

- **02 — Claude Code workflow** explains what Claude does behind the
  scenes and which natural-language phrasings route where.
- **03 — Configs and modes** covers the full config schema.
- **04 — Reading outputs** dives into `analysis.json` + the per-step
  JSONs.
