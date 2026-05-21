---
name: md-prep-structure
description: Standalone "clean a PDB for MD" skill — fetches a structure (PDB or local file), classifies it (protein-only soluble vs. unsupported), strips crystallographic waters / HETATMs in tutorial mode, and produces a working PDB ready for topology generation. Stops short of running gmx pdb2gmx so the user can inspect the cleaned structure before committing to topology. Trigger when the user says "clean PDB X", "prep structure X for MD", "fetch and validate 1AKI", "is structure X usable for tutorial-mode MD?", or wants the prep artifacts without running the full pipeline. The full pipeline lives at `md-run-workflow`.
---

# md:prep-structure

Runs the first three steps of the v0 pipeline (StructureIngest + SystemClassifier + StructurePrep) and stops. Useful when the user wants to look at the cleaned structure / classification verdict before running topology.

## When to use this vs. `md-run-workflow`

- `md-prep-structure`: user wants to *just* inspect the prep stage. Quick (<5 s). No GROMACS needed beyond a PATH check.
- `md-run-workflow`: user wants the full ingest → EM pipeline.

## Invocation

There's no dedicated CLI subcommand for "stop after prep" yet — instead, run `md-run-workflow` with a `step_cap` that effectively short-circuits, OR (preferred) call the Python API directly:

```bash
cd /Users/manu_jay/git_repos/MDSimulationAgent
uv run python -c "
from mdagent import RunConfig
from mdagent.steps import StepContext, ingest, classifier, prep
from pathlib import Path
import json

cfg = RunConfig.from_dict({
    'schema_version': '0.1.0',
    'pipeline_mode': 'tutorial_reproduction',
    'interaction_mode': 'noninteractive_defaults',
    'input': {'pdb_id': '1AKI'},
})
run_root = Path('runs/prep-only')
run_root.mkdir(parents=True, exist_ok=True)

# Ingest
ctx = StepContext(step_id='step_01_structure_ingest', run_root=run_root,
                  step_dir=run_root / 'step_01_structure_ingest', run_config=cfg)
ctx.step_dir.mkdir(parents=True, exist_ok=True)
out1 = ingest.run(ctx)
print('ingest ok:', out1.ok, [(o['role'], o['content_hash'][:12]) for o in out1.outputs])

# Classify
ctx2 = StepContext(step_id='step_02_classifier', run_root=run_root,
                   step_dir=run_root / 'step_02_classifier', run_config=cfg,
                   inputs=out1.outputs)
ctx2.step_dir.mkdir(parents=True, exist_ok=True)
out2 = classifier.run(ctx2)
print('classify ok:', out2.ok, out2.extra)

# Prep
ctx3 = StepContext(step_id='step_03_structure_prep', run_root=run_root,
                   step_dir=run_root / 'step_03_structure_prep', run_config=cfg,
                   inputs=out1.outputs)
ctx3.step_dir.mkdir(parents=True, exist_ok=True)
out3 = prep.run(ctx3)
print('prep ok:', out3.ok, out3.extra)
"
```

The outputs are in `runs/prep-only/step_*/`. The key artifacts to surface to the user:
- `step_01_structure_ingest/working.pdb` — the cleaned PDB.
- `step_02_classifier/classification.json` — chemistry / assembly / environment / unsupported_features.
- `step_03_structure_prep/observations.json` — chains, HIS / CYS residue lists, residue counts.

## Handling classification failures

If `classify ok: False`, the structure isn't supported in v0:

- `chemistry` includes `ligand` → there are HETATM records besides waters. User must hand-process or wait for general_md_prep mode.
- `chemistry` includes `nucleic_acid` → not a protein structure.
- `unsupported_features` non-empty even when chemistry is `{protein}` → unknown residues in ATOM records (modified amino acids, glycosylated residues, etc.).

In each case, print the classification reason verbatim so the user understands the gate.
