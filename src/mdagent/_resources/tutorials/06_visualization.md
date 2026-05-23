<!-- mdagent:requires mdagent,gromacs -->
<!-- mdagent:title Visualization -->

# 06 — Visualization

**Requirements:** mdagent + GROMACS + optional VMD/PyMOL.

The visualization step is opt-in (it asks up front via the
`md-visualize` skill). It can run in two modes:

- **Script-only:** writes Tcl (VMD) + PML (PyMOL) scripts you can
  render later.
- **Render:** also produces PNG snapshots in-process.

If no viewer is installed, the skill still writes the scripts so you
can `brew install --cask vmd` later and render them.

## Configure visualization in your run

```python
import json
cfg = json.loads(open("./run_configs/lysozyme_short.json").read())
cfg["visualization"] = {
    "mode": "requested",
    "viewer": "auto",                                 # vmd | pymol | nglview | auto
    "checkpoints": ["prep", "solvated", "em"],
    "render": "both"                                  # png | state_only | both
}
open("./run_configs/with_viz.json", "w").write(json.dumps(cfg, indent=2))
```

```bash
mdagent run-workflow --runs-root ./runs --config ./run_configs/with_viz.json --run-id viz_demo
```

## Or render against a completed run

```bash
mdagent visualize --run-root ./runs/smoke \
  --viewer auto --checkpoints solvated em --render both
```

This is the `md-visualize` skill's entry point — natural-language
phrasings like *"render the EM-minimized structure"* route here.

## Reading the output

```
runs/<run_id>/step_11_visualization/
├── render_probe.json              # which viewer was selected; per-checkpoint render status
├── prep/
│   ├── visualize.vmd              # Tcl script (always written when VMD selected)
│   ├── visualize.pml              # PML script (when PyMOL selected)
│   └── snapshot.png               # rendered image (best-effort)
├── solvated/...
└── em/...
```

```python
import json
probe = json.loads(open("./runs/viz_demo/step_11_visualization/render_probe.json").read())
print("selected viewer:", probe["viewer_status"]["selected_viewer"])
for r in probe["rendered"]:
    print(f"  {r['checkpoint']:10s} rendered={r['rendered']}  reason={r.get('reason')}")
```

## Render later

If a checkpoint shows `rendered: false` with
`reason: no_viewer_available`, you can still get the image by
installing the viewer and running the shipped script:

```bash
brew install --cask vmd   # macOS
vmd -dispdev text -e ./runs/viz_demo/step_11_visualization/em/visualize.vmd
# → ./runs/viz_demo/step_11_visualization/em/snapshot.png
```

## The Tcl script's defaults

The shipped Tcl uses sensible defaults for protein systems:

```tcl
mol new <structure>
mol modstyle 0 0 NewCartoon          ; # protein backbone
mol modstyle 1 0 Lines               ; # water (hideable)
mol modstyle 2 0 VDW                 ; # ions, colored by type
display projection Orthographic
display rendermode GLSL
axes location LowerLeft
color Display Background white
render TachyonInternal <snapshot.png>
```

Edit the script to change camera angle / selections / coloring —
your edits survive re-running the pipeline (visualization is a
side-effect, not a fingerprinted step).

## Asking Claude

> *"Show me the solvated box for run viz_demo."*

Routes to `md-visualize` with `--checkpoints solvated --render both`.

## Trajectories vs. static checkpoints

The visualization step renders **static frames** (one per checkpoint).
For trajectory animation, hand the production XTC to VMD/PyMOL
directly:

```bash
vmd -gro ./runs/viz_demo/step_09_production/production.gro \
    -xtc ./runs/viz_demo/step_09_production/production.xtc
```

## Next

- **07 — Resume** for re-running visualization without re-running the
  expensive pipeline steps.
