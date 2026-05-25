# MDSimulationAgent — Claude Code Skills

Three Claude Code skills that give Claude end-to-end control of a GROMACS
molecular-dynamics pipeline from a single natural-language prompt.

| Skill | What it does |
|---|---|
| `md-run-workflow` | Full pipeline: ingest → topology → solvation → EM → NVT → NPT → production → analysis → report |
| `md-prep-structure` | Prep only (no GROMACS needed): fetch + classify + clean a PDB |
| `md-visualize` | Render VMD/PyMOL checkpoint snapshots of a finished run |

## Quick install (one-time per machine)

```bash
# 1. Install the mdagent CLI
brew install uv                          # macOS — or: curl -LsSf https://astral.sh/uv/install.sh | sh
uv tool install --force git+https://github.com/FidhaNazreen/MDSimulationAgent@v0.1.0

# 2. Install GROMACS (required for topology onwards)
brew install gromacs                     # macOS

# 3. Install these skills into Claude Code
#    Option A — user-wide (available in every project):
mdagent install-skills --user

#    Option B — project-local (copy this folder into your project):
cp -r skills/ /path/to/your/project/.claude/skills/
```

Verify:
```bash
mdagent --version          # → mdagent 0.1.0
mdagent doctor --gmx-required
```

## Manual install (no mdagent CLI yet)

If you want the skills before installing mdagent, copy the three
subdirectories into your Claude skills directory:

```bash
# macOS / Linux (user-wide)
cp -r md-run-workflow md-prep-structure md-visualize ~/.claude/skills/

# project-local
cp -r md-run-workflow md-prep-structure md-visualize /your/project/.claude/skills/
```

Then install mdagent separately (step 1 above).

## Usage

Open a Claude Code session in any directory and ask naturally:

> *"Set up lysozyme in water and minimize it."*
> *"Run a 10 ns production MD of 1AKI."*
> *"Clean this PDB and tell me if it's usable for MD."*
> *"Visualize the solvated box from my last run."*

Claude picks the right skill automatically.

## Requirements

| Requirement | Needed by |
|---|---|
| `mdagent >= 0.1.0` | all three skills |
| GROMACS on PATH | `md-run-workflow` (topology step onwards) |
| VMD or PyMOL | `md-visualize` (Tcl/PML scripts written regardless; PNG rendering is best-effort) |

## Source

Full source, tutorials, and tests:
<https://github.com/FidhaNazreen/MDSimulationAgent>
