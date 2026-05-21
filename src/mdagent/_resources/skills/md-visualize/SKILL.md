---
name: md-visualize
description: Generate molecular-graphics renderings (VMD primary, PyMOL or NGLview fallback) of a system at one or more pipeline checkpoints (prep, topology, solvated, em). Probes for installed viewers, writes Tcl/PML scripts unconditionally, attempts headless PNG rendering as best-effort. Trigger when the user asks "show me lysozyme", "render the solvated box", "visualize the EM-minimized system", "make a VMD picture of this run", or wants visual sanity-checking of a completed prep run. The skill asks the user up-front whether visualization is wanted and which viewer to use — never runs silently. Headless / unattended runs must respect `visualization.mode = disabled` in the run_config and refuse to prompt.
metadata:
  minimum_mdagent_version: "0.1.0"
  skill_version: "1.0.0"
---

# md:visualize

Render checkpoint snapshots of a completed mdagent run.

## Skill preflight

```bash
command -v mdagent >/dev/null 2>&1 || {
  echo "mdagent not found on PATH."
  echo "Install: uv tool install --force git+https://github.com/<user>/MDSimulationAgent@v0.1.0"
  echo "PATH: ensure '$(uv tool dir --bin 2>/dev/null || echo "<uv tool bin dir>")' is on PATH."
  exit 1
}
mdagent doctor --json \
  --min-version 0.1.0 \
  --skill-name md-visualize \
  --skill-version 1.0.0 \
  --check-viewers \
  || { echo "Doctor failed (or no viewer detected)."; exit 1; }
```

`--check-viewers` produces a warning (not a hard fail) if no viewer is on
PATH — the visualize step still writes Tcl/PML scripts; it just skips PNG
rendering.

## Required up-front user choices

In an interactive session, ask once before invoking:

1. **Viewer**: VMD (preferred), PyMOL, NGLview (notebook-only), or `auto`.
2. **Checkpoints to render**: subset of `prep | topology | solvated | em | all`.
3. **Output**: `png` (renders PNGs) | `state_only` (Tcl/PML scripts only) | `both`.

If any are already pinned in the run's config, don't re-ask.

## Invocation

```bash
mdagent visualize --run-root ./runs/<run_id> \
  --viewer auto \
  --checkpoints solvated em \
  --render both
```

## Output

For each checkpoint:

```
<run_root>/step_10_visualization_cli/<checkpoint>/
├── visualize.vmd        # Tcl script (always written when VMD selected)
├── visualize.pml        # PML script (when PyMOL selected)
├── snapshot.png         # rendered image (best-effort)
```

Plus `render_probe.json` at the step dir root recording which viewer was
selected and whether each checkpoint actually rendered.

## Failure modes

- **No viewer detected**: Tcl/PML scripts still written; user can render
  later. Suggest `brew install --cask vmd` (macOS).
- **Viewer present but render failed**: usually a display-backend issue.
  Scripts are preserved; point the user at them.
- **Requested checkpoint missing**: e.g. `em` requested but the run failed
  at solvation. Surface `index.json` for the actual available checkpoints.

## What this skill does NOT do

- Trajectory visualization / animation (only static checkpoints).
- Movie generation.
