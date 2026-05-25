---
name: md-prep-structure
description: Standalone "clean a PDB for MD" skill — fetches a structure (PDB or local file), classifies it (protein-only soluble vs. unsupported), strips crystallographic waters / HETATMs in tutorial mode, and produces a working PDB ready for topology generation. Stops short of running `gmx pdb2gmx`, so the user can inspect the cleaned structure before committing to topology. Does NOT require GROMACS — runs on any machine with the mdagent tool installed. Trigger when the user says "clean PDB X", "prep structure X for MD", "fetch and validate 1AKI", "is structure X usable for tutorial-mode MD?", or wants the prep artifacts without running the full pipeline. The full pipeline lives at `md-run-workflow`.
metadata:
  minimum_mdagent_version: "0.1.0"
  skill_version: "1.0.0"
---

# md:prep-structure

Runs the first three pipeline phases (ingest + classify + prep) and stops.
Useful when the user wants to look at the cleaned structure / classification
verdict before running topology — or when they're on a machine without
GROMACS and just want the prep artifacts.

## Skill preflight

```bash
command -v mdagent >/dev/null 2>&1 || {
  echo "mdagent not found on PATH."
  echo "Install: uv tool install --force git+https://github.com/FidhaNazreen/MDSimulationAgent@v0.1.0"
  echo "PATH: ensure '$(uv tool dir --bin 2>/dev/null || echo "<uv tool bin dir>")' is on PATH."
  exit 1
}
mdagent doctor --json \
  --min-version 0.1.0 \
  --skill-name md-prep-structure \
  --skill-version 1.0.0 \
  || { echo "Doctor failed."; exit 1; }
```

(No `--gmx-required` here — prep doesn't need GROMACS.)

## Invocation

```bash
mdagent prep-structure --runs-root ./runs --pdb-id 1AKI --run-id prep-1aki
```

Or from a local file:

```bash
mdagent prep-structure --runs-root ./runs --structure-path /path/to/protein.pdb --run-id prep-local
```

## What the user gets

After the run, three step subdirectories under `./runs/<run_id>/`:

  - `step_01_structure_ingest/working.pdb` — the cleaned PDB.
  - `step_02_classifier/classification.json` — chemistry / assembly / environment / unsupported_features.
  - `step_03_structure_prep/observations.json` — chains, HIS / CYS residue lists, residue counts, titratable residues.

## Handling classification failures

If the run fails at the classifier:

  - `chemistry: [ligand]` → HETATM records besides waters. v0 doesn't
    support ligand parametrization.
  - `chemistry: [nucleic_acid]` → not a protein structure.
  - `unsupported_features` non-empty even when chemistry is `{protein}` →
    unknown residues in ATOM records (modified amino acids, glycosylated
    residues, etc.).

Surface the `classification.json` `unsupported_features` array to the user
verbatim — that's the structured reason.
