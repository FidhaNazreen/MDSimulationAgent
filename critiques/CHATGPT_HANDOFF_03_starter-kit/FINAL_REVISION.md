# Final revision — starter-kit

**Critique loop:** 3 rounds, gpt-5.5 via Codex.
**Final verdict:** `VERDICT: APPROVED` (R3).
**~25 issues raised; all addressed.**

## Key architecture decisions

- **Starter kit bundled inside the wheel** at `src/mdagent/_resources/starter_kit/`.
- **`mdagent init-project DIR`** materializes it (refuse-on-nonempty; `--force` to overwrite).
- **Bundled 1aki.pdb** (CC0 from RCSB) makes the smoke run offline-safe; an RCSB-fetching config preserves the network path.
- **`verify.sh` default = structural/config-schema checks** (no gmx, no network). `--run-smoke` adds gmx-required + a real MD run.
- **`tutorial/getting_started.md`** is the primary tutorial format (no Jupyter dep).
- **YAML frontmatter not perturbed** — generation metadata lives *inside* the existing `metadata:` block of each SKILL.md.
- **`RunConfig.from_file`** resolves relative `structure_path` against the config file's directory (so `mdagent run-workflow --config /any/path/lysozyme_short.json` works from any cwd).
- **`MANIFEST.json`** lists payload files (excluding itself); manifest itself has `manifest_schema_version`.
- **`install-skills --force`** removes mdagent-managed skill dirs before recopying (per R3 nit), preserving user-owned skills.

## Implementation order

1. Create `src/mdagent/_resources/starter_kit/` with all bundled files.
2. Add `mdagent init-project` subcommand.
3. Update `pyproject.toml` source-include to ship the kit.
4. Update `RunConfig.from_file` to resolve relative structure_path.
5. Add `install-skills --force` (manifest-driven).
6. Add `tests/test_starter_kit.py` (wheel + slow markers).
7. Run end-to-end verification: materialize the kit to /tmp/, run smoke.
