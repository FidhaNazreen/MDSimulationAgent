---
name: md-visualize
description: Generate molecular-graphics renderings (VMD primary, PyMOL or NGLview fallback) of a system at one or more pipeline checkpoints (prep, topology, solvated, em). Probes for installed viewers, writes Tcl/PML scripts unconditionally, attempts headless PNG rendering as best-effort. Trigger when the user asks "show me lysozyme", "render the solvated box", "visualize the EM-minimized system", "make a VMD picture of this run", or wants visual sanity-checking of a completed prep run. The skill asks the user up-front whether visualization is wanted and which viewer to use — never runs silently. Headless / unattended runs must respect `visualization.mode = disabled` in the run_config and refuse to prompt.
---

# md:visualize

Renders MD systems at checkpoint snapshots using traditional viewers. Per the R3 / R4 architecture: ask up-front, write scripts unconditionally, render best-effort.

## When to use this

Trigger phrases include: "render this run", "show me the solvated box for run X", "make a VMD picture of the EM result", "visualize the system". Run *after* a successful `md-run-workflow` invocation, against a run root that has at least the checkpoints the user wants to see.

If `gmx` isn't installed but VMD/PyMOL is, this skill can still produce snapshots from existing artifacts. Don't require GROMACS for this skill alone.

## Required up-front user choices (per R3-23, R4-22)

**In interactive mode** (default when the user is in a conversation), ask once before invoking:

1. **Viewer**: VMD (best), PyMOL, NGLview (notebook-only), or "auto" (let the system probe and pick).
2. **Checkpoints to render**: any subset of `prep`, `topology`, `solvated`, `em`, or `all`.
3. **Output**: `png` (rendered images), `state_only` (just write the Tcl/PML scripts), or `both`.

Skip the asks if any of these is already specified in `run_config.visualization`.

**In non-interactive modes** (the run_config has `visualization.mode = disabled` or the orchestrator's interaction_mode is `noninteractive_defaults` / `strict_config_required` with no `visualization` block), **do not prompt** — refuse the request with a one-line explanation that the run is configured for unattended execution.

## Invocation

```bash
cd /Users/manu_jay/git_repos/MDSimulationAgent
uv run python -m mdagent visualize \
  --run-root runs/<run_id> \
  --viewer vmd \
  --checkpoints solvated em \
  --render png
```

(The `visualize` CLI subcommand is added by the visualization slice; if not yet present, fall back to invoking `mdagent.steps.visualization.run()` via a one-liner.)

## Best-effort renderer probing

The skill detects viewers in this order: VMD → PyMOL → NGLview. For each, it runs a tiny test render to confirm the binary + display backend works (R3-24). When a viewer is present but rendering doesn't work (no X11 / Tachyon / Quartz), the skill **still writes the Tcl/PML scripts** to the visualization/ subdir and marks images as `skipped: renderer_unavailable` with the failure reason. The user can re-run the scripts manually after fixing their viewer install.

## Output

For each checkpoint requested:

```
<run_root>/step_07_visualization/<checkpoint>/
├── visualize.vmd        # Tcl script (always written when VMD selected)
├── visualize.pml        # PML script (when PyMOL selected)
├── snapshot.png         # rendered image (best-effort)
└── render_probe.json    # records what was tried and what succeeded
```

Embed image links in the final `REPORT.md` when the user re-runs the report step after visualization completes.

## Failure modes to surface clearly

- **No viewer detected**: tell the user which viewer would be easiest to install (VMD is the recommended primary). Offer `brew install --cask vmd` on macOS.
- **Viewer installed, render failed**: usually a display backend / Tachyon issue. The Tcl/PML scripts are still written — point the user at them and explain they can be rendered later.
- **User asked for a checkpoint that doesn't exist**: e.g. they asked for `em` but the run failed at solvation. List the checkpoints actually available in `<run_root>/index.json`.

## What this skill does NOT do

- Trajectory visualization (animation) — v0 only renders static checkpoints.
- Movie generation — past v0.
- Annotated figure layouts — past v0.
- Auto-selecting interesting residues — the Tcl/PML scripts use sensible defaults (NewCartoon protein, Lines/transparent water, VDW ions colored by type), but the user can edit the script for custom views.
