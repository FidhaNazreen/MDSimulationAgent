# Round 2 counterreply

Most of these I accept and they materially change the design. A few I want
to defend / refine. Section 2 has the revised plan; Section 3 asks targeted
follow-ups.

## Section 1 — Per-issue acknowledgments

**R1-1** (`uv tool install --from git+...` is wrong syntax). **Accept.**
Correct form is `uv tool install git+https://github.com/mjayadharan/MDSimulationAgent@v0.1.0`.
README + skill body will use the tagged form.

**R1-2** (P1 load-bearing = Q1+Q4 install/discovery, Q2 resource bundling,
Q5 GROMACS compatibility). **Accept.** Other open questions are nitpicks.
Anchoring the rest of this plan on those three.

**R1-3** (skills must live at `.claude/skills/` or `~/.claude/skills/`,
not bare `skills/`). **Accept — critical fix.** I'll:
  - Move `skills/` → `.claude/skills/` in the repo (project skills auto-loaded
    when Claude Code runs in this repo).
  - Add an `install-skills` helper (`mdagent install-skills [--user|--project DIR]`)
    that copies the skill files to the right place for an arbitrary project.
  - Document both placement options.

**R1-4** (don't add pipx as a peer; bootstrap uv if missing). **Accept.**
Skill body and README recommend: install uv first (`brew install uv` /
official curl-installer), then `uv tool install git+...@v0.1.0`. No pipx
fallback in the supported matrix.

**R1-5** (unpinned git URL is non-reproducible). **Accept.** Skill body
and README pin to `@v0.1.0`. Upgrade path: `uv tool upgrade mdagent --reinstall`
or reinstall with a newer tag.

**R1-6** (importlib.resources returns Traversable, not Path; wheel-install
not tested). **Accept — blocking.** Two parts to the fix:
  - Move schemas + mdp templates physically into `src/mdagent/_resources/`
    (or `src/mdagent/schemas/`, `src/mdagent/mdp/` — already there for mdp).
  - Use `importlib.resources.as_file()` context manager OR keep `Path` only
    on the editable-install dev path. Best: write a small `_resources.py`
    helper that always returns a real on-disk Path via `as_file()`. The
    `sha256_dir`/`rglob` code keeps working.
  - Add a wheel-install smoke test: `uv build`, install into a clean
    virtualenv, run `mdagent --help` and `mdagent run-workflow --help`.

**R1-7** (`[project.scripts]` + prog rename + installed-command test).
**Accept.** Add `[project.scripts] mdagent = "mdagent.cli:main"`. Change
`prog="python -m mdagent"` to `prog="mdagent"` in argparse. Smoke-test
the installed binary (see R1-6).

**R1-8** (no `mdagent --version`). **Accept.** Add
`-V/--version` at the top-level parser, reading
`importlib.metadata.version("mdagent")` so it reflects the actual
installed wheel, not the source `__version__`.

**R1-9** (skill-version sentinel weak; needs YAML + JSON-doctor handshake).
**Accept with refinement.** Adding `metadata.minimum_mdagent_version` and
`metadata.skill_version` to each SKILL.md's YAML frontmatter. The skill
body's preflight calls `mdagent doctor --min-version <X> --skill-name <Y>
--skill-version <Z> --json`. `doctor` exits non-zero with a structured
JSON error if either version constraint is violated; the skill surfaces
that to the user with a one-line install/upgrade hint.

**R1-10** (doctor must be enforced inside `run-workflow`, not just by the
skill). **Accept — critical.** Adding `mdagent doctor` AND running its
critical checks inside `run-workflow` before topology, unless
`--no-doctor` is set. The check sequence:
  1. gmx on PATH + version within supported range
  2. Prompt-catalog snapshot exists for the detected gmx version
  3. (For the `visualize` skill) viewer probe
  4. (Optional) RCSB reachability when `--pdb-id` is used

**R1-11** (`--gmx-version` default lies). **Accept.** Removing the `--gmx-version`
flag entirely from `run-workflow`. The actual gmx version is captured at
runtime via `gmx_version_stdout()` and written into `provenance.json`.
`run_config.tool_versions.gromacs` becomes a *constraint* field (a string
indicating the minimum or pinned version the config was built against),
not a fact about the install. `doctor` enforces the constraint.

**R1-12** (Claude Code shell risks: PATH/env, output truncation). **Accept
with concrete mitigations:**
  - `mdagent doctor --json` is concise — single JSON object summarizing
    `{ok, gmx_version, gmx_path, mdagent_version, viewer_available, errors[]}`.
  - All verbose mdrun/grompp output already goes to per-step log files,
    not stdout.
  - Skill body invokes `mdagent` directly (no `cd`, no `uv run`); the
    binary is on PATH after `uv tool install`, so PATH inheritance in
    Claude Code shells is the same as for any other PATH binary.
  - Add `mdagent doctor --suggest-install` which prints a one-line fix
    for any missing dep ("Install gmx: `brew install gromacs`"). Skill
    body shells this out and surfaces the suggestion verbatim.

**R1-13** (md-prep-structure has no CLI; calls private APIs). **Accept.**
Adding `mdagent prep-structure --pdb-id <ID> --runs-root <DIR> [--run-id <ID>]`
(or `mdagent run-workflow --stop-after prep` — leaning toward the latter
since it composes cleanly with the existing pipeline). Skill body
rewritten to use it.

**R1-14** (md-visualize references a non-existent subcommand). **Accept.**
Adding `mdagent visualize --run-root <DIR> [--viewer ...] [--checkpoints ...]
[--render ...]` as a thin wrapper around the existing visualization step.
Skill body rewritten accordingly.

**R1-15** (tutorial portability: split user vs. developer). **Accept.**
The notebook gets a "User Quick Start" section at the top using only
`mdagent ...` invocations (installed CLI). The repo-relative `uv run ...`
cells move to a "Developer Notes" section at the bottom.

**R1-16** (top-level schema removal hurts dev usability). **Accept with
refinement.** I'll keep `schemas/` at the repo root as the canonical
*development* source. `src/mdagent/_resources/schemas/` is generated at
build time via a small `build.py` hook (or simply by copy at uv build
time). For editable installs both paths exist; for wheels only the
package-internal one is shipped. A top-level `schemas/README.md` points
to where the schemas live in installed builds.

**R1-17** (PyPI naming doesn't require renaming the binary). **Accept.**
Distribution name can be `claude-md-agent` (if `mdagent` is taken when
we get to PyPI); console script stays `mdagent`; import name stays
`mdagent`. Skill body never references the distribution name.

## Section 2 — Revised plan (the artifact)

### 2.1 Code changes to ship

1. **Restructure resources.** Move `schemas/v0.1.0/*` into
   `src/mdagent/_resources/schemas/v0.1.0/` (and keep top-level
   `schemas/` as the development source; a build hook copies them in).
   Add a `mdagent._resources` helper that uses `importlib.resources.as_file()`
   to materialize the dir as a real `Path` regardless of install kind.
2. **`pyproject.toml`:**
   - Add `[project.scripts] mdagent = "mdagent.cli:main"`.
   - Include `_resources/**/*` as package data.
   - Pin version to `0.1.0` (no bump until the rename ships).
3. **`mdagent.cli`:**
   - Change argparse `prog` to `"mdagent"`.
   - Add `-V/--version` reading `importlib.metadata.version("mdagent")`.
   - Add new subcommands:
     - `doctor` (default-JSON output; supports `--min-version`, `--skill-name`,
       `--skill-version`, `--suggest-install`).
     - `prep-structure` (proxies to `run-workflow --stop-after prep`).
     - `visualize` (thin wrapper around `mdagent.steps.visualization.run`).
     - `install-skills` (copies `.claude/skills/*` into a target directory).
   - Remove `--gmx-version` from `run-workflow`. Capture the real version
     at runtime.
   - Add `--no-doctor` to `run-workflow` for power users.
   - `run-workflow` calls `_doctor_critical_checks()` before the
     orchestrator unless `--no-doctor` is set.
4. **Schemas:** loader switches from
   `Path(__file__).parent.parent.parent / "schemas"`
   to `mdagent._resources.schemas_dir()` returning a real `Path`.
5. **Skills:** move `skills/` to `.claude/skills/`. Each SKILL.md:
   - YAML frontmatter gains `metadata.minimum_mdagent_version: "0.1.0"`
     and `metadata.skill_version: "1.0.0"`.
   - Body removes all `cd /Users/manu_jay/...` and `uv run python -m mdagent`
     usages. Replaces with `mdagent ...` invocations.
   - Preflight calls `mdagent doctor --json --min-version <X>
     --skill-name <NAME> --skill-version <V>`. Failure → surface the
     stderr verbatim.
6. **README.md** (new or refreshed): single-screen install + first-run.
   Documents both `.claude/skills/` (project) and `~/.claude/skills/`
   (user-global) placement.

### 2.2 Wheel-install smoke test (NEW)

Adding `tests/test_wheel_install.py`. The fast suite is left in place
(it runs in editable mode). The new test:

  - `uv build` (or `python -m build`) into a `dist/` dir.
  - Create a temp venv.
  - Install the wheel into it.
  - In the new venv: `mdagent --version` returns the expected string;
    `mdagent --help` lists `run-workflow|inspect|doctor|prep-structure|
    visualize|install-skills`; `mdagent run-workflow --help` mentions
    `--pdb-id`; schemas resolve from the package; `mdagent doctor
    --json` returns JSON.
  - Marked `slow` (build + venv create is ~10 s) and `wheel` so devs can
    selectively skip during inner-loop work.

### 2.3 Doctor contract

`mdagent doctor [--json] [--min-version X] [--skill-name N --skill-version V]
[--suggest-install]` checks (each emits a structured entry in the JSON):

  - `mdagent_version`: from `importlib.metadata.version("mdagent")`
  - `gmx`: { available: bool, version: str, path: str, supported: bool }
  - `gmx_prompt_catalog`: { version_pinned: "2026.2", current: "<live>",
    matches: bool }
  - `rcsb_reachable`: bool (only if `--check-network`)
  - `viewer`: { vmd: ok, pymol: ok, nglview: ok } (only if `--check-viewers`)
  - `skill_version`: (only if `--skill-name --skill-version` passed)
    { skill_name, skill_version, supported_by_cli: bool }
  - `min_version`: (only if `--min-version` passed)
    { required, current, satisfied: bool }

Exit code 0 if all hard checks pass, 1 otherwise. JSON to stdout, human
text to stderr (suppressed under `--json`).

### 2.4 Tutorial split

  - `tutorial/MD_simulation_with_agents.ipynb` — primary user-facing.
    Uses `mdagent ...` directly. Assumes the user has done
    `uv tool install git+...@v0.1.0` once.
  - `tutorial/developer_notes.ipynb` — for contributors. Uses
    `uv run python -m mdagent` from a clone. Build & test the wheel,
    run the slow suite, regenerate the user notebook, etc.

### 2.5 What I'm explicitly leaving for a later slice

  - **PyPI publication.** This slice only makes the package installable
    from a git tag. PyPI is a separate decision when we have a stable
    schema_version and someone (likely you) wants to register the name.
  - **Multi-gmx-version prompt catalog discovery.** Today only 2026.2 is
    supported. `doctor` will refuse to run topology against other gmx
    versions until we add the catalog probe.
  - **Renamed distribution package.** `mdagent` stays the import name
    AND the console script for this slice. Distribution-name rename
    (if needed for PyPI) is a no-op for users.

## Section 3 — Continued critique prompt

Push back on responses where I defended poorly; name which point. Raise
new issues the revised plan creates. Same format / verdict line:

  VERDICT: APPROVED
  VERDICT: ISSUES_REMAIN

Three targeted questions:

**C1.** The `_resources` helper. I'm planning to use
`importlib.resources.files("mdagent._resources")` and pass the result
straight to `sha256_dir`. If `files()` returns a Traversable that isn't
a real Path (e.g. when imported from a zipapp), `Path(...)` on it will
silently lose data. Should I instead use `as_file()` context-managed
through every call site? That's awkward because the schemas dir is read
many times. Alternative: at startup, extract `_resources` into a
process-lifetime temp dir and cache its path. Which is right?

**C2.** Bundling schemas via "copy at build time" vs. "schemas live
inside `src/mdagent/_resources/` and the top-level dir is a symlink".
The copy approach needs a tested build hook. The symlink approach
breaks on Windows / CI systems without symlink permissions. What's the
pragmatic choice?

**C3.** Doctor's `--check-network` and `--check-viewers` are guarded by
flags so the default is fast. But `run-workflow` always calls doctor
before topology — should the embedded doctor call include network +
viewer checks when the run config requests features that need them
(e.g. `input.pdb_id` set → network needed; `visualization.mode != disabled`
→ viewer probe)? My current plan: yes, conditionally enable each check
based on what the config asks for.
