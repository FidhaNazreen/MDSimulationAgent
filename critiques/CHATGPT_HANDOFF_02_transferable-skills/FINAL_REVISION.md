# Final revision — transferable Claude skills

**Critique loop:** 4 rounds, gpt-5.5 via Codex, reasoning effort high.
**Final verdict:** `VERDICT: APPROVED` (R4).
**~37 issues raised; all addressed.**

## Headline architecture changes from critique

1. **Resources canonical inside the package**: `src/mdagent/_resources/schemas/v0.1.0/` and `src/mdagent/_resources/skills/`. Top-level `schemas/` becomes a one-line pointer; top-level `skills/` is removed (now generated under `.claude/skills/` via the install helper).
2. **`uv tool install git+...@<tag>`** is the install path (corrected from R1's `--from` syntax). Pinned tag for reproducibility.
3. **Skills live at `.claude/skills/`** — both repo-level (auto-discovered by Claude Code when working in the repo) and user-level via `mdagent install-skills --user`.
4. **Config-aware doctor**: `check_for_run(cfg, planned_step_ids)` derives requirements from what will actually run. `prep-structure` works without GROMACS.
5. **CLI surface expanded**: `doctor`, `prep-structure`, `visualize`, `install-skills`, `self-test resources`, plus `--version`, `--stop-after`, `--skip-network-check`, `--skip-viewer-check`, `--skip-gmx-version-check`.
6. **`--gmx-version` removed from `run-workflow`** (it was a lie — defaulted regardless of the actual install). Real gmx version captured at runtime in provenance.
7. **Wheel smoke test** that builds + installs + runs `mdagent self-test resources --json` against a clean venv.
8. **Skills are path-free**: skill bodies invoke `mdagent` directly. Preflight first checks `command -v mdagent`, then `mdagent doctor --json --min-version --skill-name --skill-version` for compatibility.

## Top 3 issues that nearly missed (worth surfacing)

- **`uv tool install --from git+url` is wrong syntax** (R1-1). Real form is `uv tool install git+url@tag`. Would have made the first sentence of the install instructions fail.
- **`Path(traversable)` silently breaks under archive-installed wheels** (R1-6 / R2-1). Resources need to be filesystem-backed and tested via a real wheel build.
- **`gmx` requirement was being asserted globally for all skills** (R3-1) — would have broken `md-prep-structure` on machines without GROMACS. Doctor must be config/step-aware.

## Implementation order

1. Move resources into `src/mdagent/_resources/`; update loader; add `__init__.py` files.
2. Update `pyproject.toml` (console script, package_data).
3. Add `mdagent.doctor` module + CLI subcommand.
4. Add `--version`, `prep-structure`, `visualize`, `install-skills`, `self-test resources` to CLI.
5. Wire doctor into the orchestrator (`check_for_run` before run).
6. Remove `--gmx-version` from `run-workflow`.
7. Rewrite the three SKILL.md bodies (path-free, with the preflight).
8. Add wheel smoke test + no-gmx prep test.
9. Update tutorial notebook to use the installed CLI.

## R4 nits incorporated during implementation

- Prefer `isinstance(res, Path)` over `_path` check.
- `--user` / `--project` mutually exclusive in argparse.
- `provenance.json:doctor_skipped` is structured: `{network, viewer, gmx_version}`.
- One test that asserts prep doesn't need GROMACS (PATH-stripped).
