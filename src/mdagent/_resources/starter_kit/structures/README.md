# Bundled structures

This directory ships with one PDB file for offline smoke-testing the
starter kit:

## `1aki.pdb`

- **PDB ID:** 1AKI (Hen egg-white lysozyme, orthorhombic form at 1.5 Å)
- **Source URL:** https://files.rcsb.org/download/1AKI.pdb
- **DOI:** https://doi.org/10.2210/pdb1AKI/pdb
- **Citation:** Diamond, R. (1974). Real-space refinement of the structure of hen egg-white lysozyme. *J Mol Biol* 82(3):371-391.
- **License:** RCSB PDB archive coordinate files are released under
  CC0 1.0 (https://www.rcsb.org/pages/policies). No warranty.
- **What we changed:** crystallographic HETATM records (waters, ions)
  were stripped to match the canonical GROMACS lysozyme tutorial
  starting structure.

For the network-backed flow (live fetch from RCSB), use
`run_configs/lysozyme_rcsb_tutorial.json` which sets
`input.pdb_id: 1AKI`.
