1. **Blocking: doctor incorrectly requires GROMACS for `prep-structure`.**  
WHAT is wrong: Section 2.4 says `gmx on PATH` is triggered “always (any pipeline run needs gmx).” That is false for `prep-structure`, which stops before topology. You also route `prep-structure` through `run_workflow()`, whose startup calls `check_for_run(cfg)`, so prep-only runs will fail on machines without GROMACS.

WHY it matters: this breaks one of the three transferable skills. `md-prep-structure` should be usable for fetch/classify/clean without local MD execution.

WHAT to do: derive doctor requirements from the planned step range, not from “pipeline run” globally. `gmx_required = planned_steps intersects {topology, solvation, em, nvt, npt, production, analysis}`. For `prep-structure` / `--stop-after prep`, skip GROMACS entirely.

2. **Blocking unless specified: `install-skills --project DIR` has ambiguous target semantics.**  
WHAT is wrong: CLI surface says `mdagent install-skills [--user | --project DIR]`, but Section 1 says repo skills are generated via `mdagent install-skills --project .claude/skills/`. That treats `--project` as a skills directory, not a project root.

WHY it matters: users will install into the wrong place, e.g. `.claude/skills/.claude/skills` or directly into a root depending on implementation.

WHAT to do: define one contract. Recommended: `--project DIR` means project root and copies to `DIR/.claude/skills/<skill>/SKILL.md`. Add `--skills-dir DIR` only if you need a raw destination override.

3. **Blocking-ish: the “exact” skill preflight fails poorly when `mdagent` is absent.**  
WHAT is wrong: the preflight starts with `mdagent doctor ... > /tmp/mdagent_doctor.json`. If `mdagent` is not installed, no JSON file exists, then `cat /tmp/mdagent_doctor.json` emits noise before the real install hint.

WHY it matters: first-time install is a primary v0 path. The failure message should be deterministic and clean.

WHAT to do: put `command -v mdagent >/dev/null || { echo "Install or upgrade: ..."; echo "PATH: ..."; exit 1; }` before `mdagent doctor`.

4. **Nit: fixed `/tmp/mdagent_doctor.json` is sloppy.**  
WHAT is wrong: concurrent Claude sessions can overwrite each other, and stale files can be surfaced.

WHY it matters: confusing diagnostics.

WHAT to do: use `tmp="$(mktemp "${TMPDIR:-/tmp}/mdagent_doctor.XXXXXX.json")"` and clean it up, or just let doctor print JSON to stdout and surface that directly.

5. **Nit: resource package dirs should have `__init__.py`.**  
WHAT is wrong: the layout shows `src/mdagent/_resources/schemas/...` and `skills/...`, but not package marker files.

WHY it matters: `importlib.resources.files("mdagent._resources.schemas")` is cleaner and more predictable with real packages than namespace-package behavior.

WHAT to do: add empty `__init__.py` files under `_resources`, `_resources/schemas`, and `_resources/skills`.

VERDICT: ISSUES_REMAIN