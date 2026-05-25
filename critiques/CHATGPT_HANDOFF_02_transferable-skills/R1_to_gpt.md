# Round 1 handoff: design transferable Claude skills for the mdagent MD pipeline

---

## Section 1 — Context bundle

### What the project is

`mdagent` is a multi-agent pipeline that drives GROMACS molecular-dynamics
prep + equilibration + production + analysis end-to-end from a single
natural-language instruction. Shipped as:

  - A Python package `mdagent` (src layout) with a CLI:
    `python -m mdagent run-workflow|inspect ...`
  - Three Claude skills (`skills/md-run-workflow/SKILL.md`,
    `skills/md-prep-structure/SKILL.md`, `skills/md-visualize/SKILL.md`)
    that document how Claude should map user prompts to CLI invocations.
  - JSON schemas + step modules + tests, all under one git repo.

Right now the repo lives at `/Users/manu_jay/git_repos/MDSimulationAgent/`
and **the skill files literally hard-code that path** in their invocation
blocks. Example (md-run-workflow):

```bash
cd /Users/manu_jay/git_repos/MDSimulationAgent
uv run python -m mdagent run-workflow ...
```

### The problem

The user wants these skills to be reusable across projects and teammates.
Concretely:

  1. A teammate clones the repo into a different path → the skill body
     references a directory that doesn't exist on their machine.
  2. The user wants to run an MD prep workflow from inside an unrelated
     project (different working directory, no mdagent checkout) and have
     the skill still work.
  3. We want minimum-friction install — ideally one command — and we
     want the skill itself to verify that install before it tries to
     invoke the CLI.

### What the skills currently rely on

  - The full mdagent repo (src tree + schemas + skills) present on disk.
  - `uv` (the package manager) installed.
  - `gmx` (GROMACS) on PATH.
  - `uv sync` already done inside the repo so the `.venv` exists.

### What's already in place

  - Python project is structured: `pyproject.toml` declares
    `[project.scripts] mdagent = "mdagent:main"` is **not** declared yet —
    we'd need to add it. There IS `__main__.py` so `python -m mdagent` works.
  - All Python deps are pure-Python and bottle-installable on Mac/Linux:
    `jsonschema`, `pexpect`, `gemmi`. No compile step.
  - The package version is pinned in `pyproject.toml` at `0.1.0`.
  - The `Pdb2GmxPromptRecognizer` is pinned to gmx 2026.2 by regex —
    other gmx versions may need a catalog refresh (separate concern).

### Confirmed constraints (these are pinned; don't relitigate)

  - The MD engine is **GROMACS**, on the user's local machine. Network
    fetches to RCSB are OK; remote MD execution is past v0.
  - Python ≥ 3.11.
  - macOS is the primary developer platform; Linux must also work.
  - We're using **uv** as the package manager — not pip/poetry/conda.
  - Skills live in a Claude-readable `skills/<name>/SKILL.md` format with
    YAML frontmatter (`name:` + `description:`).
  - The user invokes skills inside a Claude Code session; the Skill body
    is what tells Claude how to run the CLI.

---

## Section 2 — Artifact under review

The plan I'm proposing for transferable skills. I want you to pressure-test
it before I implement.

### 2.1 Approach: install mdagent as a tool, address it by name

Convert `mdagent` into a standalone installable CLI tool that any project
can use without checking out the source.

**Install path the skill recommends to first-time users:**

```bash
# Option A (preferred): uv tool install — puts an isolated `mdagent`
# binary on PATH, like pipx but uv-native.
uv tool install --from git+https://github.com/mjayadharan/MDSimulationAgent mdagent

# Option B (fallback): direct uv tool install from a local checkout.
uv tool install /path/to/MDSimulationAgent
```

After install, the skill body simply runs `mdagent ...` without any
`cd` or `uv run` indirection:

```bash
mdagent run-workflow --runs-root ./runs --pdb-id 1AKI --run-id demo
```

**Required code changes:**

  - Add a real `[project.scripts]` entry to `pyproject.toml`:
    `mdagent = "mdagent.cli:main"`. (We have `cli.main` already — just
    not exposed as a script.)
  - Ensure no part of `mdagent.*` relies on `__file__` to find schemas /
    fixtures. (Currently `schemas.py` resolves
    `Path(__file__).resolve().parent.parent.parent / "schemas"` — that's
    fine in editable install but BREAKS when installed as a built wheel
    because `schemas/` lives outside `src/mdagent/`.)
  - Bundle `schemas/v0.1.0/*.json` and `tutorial/*.ipynb` as
    package_data under `src/mdagent/_resources/` (or use `importlib.resources`
    against an in-package `schemas/` subdir).
  - Decide on a versioning story: `mdagent --version` prints
    `pyproject.toml:project.version`. Skills can require a minimum
    version at runtime.

**Skill rewrite:**

The skill body becomes path-free. Each skill starts with a small
verification block:

```bash
# Skill verifies its prerequisites once per invocation:
command -v mdagent >/dev/null || { echo "Install: uv tool install --from git+https://..." ; exit 1; }
command -v gmx >/dev/null || { echo "GROMACS not found. Install: brew install gromacs"; exit 1; }
```

Then the actual invocation is just `mdagent run-workflow ...`.

### 2.2 Resource bundling (the load-bearing detail)

The mdagent code currently lives in `src/mdagent/`. The schemas live in
`schemas/v0.1.0/` at the repo root — NOT inside the Python package.
For an installed wheel, `Path(__file__).parent.parent.parent / "schemas"`
either:

  - In editable install (`uv pip install -e .`): resolves correctly back
    to the repo root. ← works today.
  - In wheel install (`uv tool install`): resolves into site-packages
    where there is no `schemas/` dir. ← breaks today.

**Fix proposal:** move schemas physically into the package:

```
src/mdagent/
  _resources/
    schemas/v0.1.0/   # all .json schemas + step_definitions.json
    mdp/              # the .mdp templates (already in src/mdagent/mdp/)
```

And switch `mdagent.schemas.schemas_dir()` to use `importlib.resources`:

```python
import importlib.resources
def schemas_dir() -> Path:
    return importlib.resources.files("mdagent") / "_resources" / "schemas" / f"v{SCHEMA_VERSION}"
```

This keeps schemas inside the installed wheel and makes the package
self-contained.

### 2.3 Versioning + skill/package coupling

The skill body and the underlying CLI need to evolve together — if a
new pipeline phase is added (say "free energy" in slice 12), the skill
body needs to know about it, and an old version of the skill paired
with a new package (or vice versa) could mislead Claude.

**Proposal:** every SKILL.md ends with a `minimum_mdagent_version`
sentinel in its body. The skill body's verification block reads it via
`mdagent --version` and refuses to invoke if the installed version is
older. The user gets one line telling them to `uv tool upgrade mdagent`.

If you don't have the skill, you can't have the CLI work for you. If you
have the skill but an older CLI, you get a clear error.

### 2.4 Multi-machine reproducibility

A second concern: different teammates may install on machines with
different `gmx` versions. The Pdb2GmxPromptRecognizer was probed against
2026.2. A 2024.x install might emit slightly different prompts and
`DialogueRunner` would time out.

**Proposal:** keep the existing `gmx_version_stdout()` capture; have
the CLI's `mdagent doctor` (new subcommand) verify:

  - gmx is on PATH and its version matches the supported range
  - mdagent's `Pdb2GmxPromptRecognizer` has a catalog snapshot for that
    version (today: only 2026.2)
  - Internet works (for RCSB fetches)
  - Optional viewers (VMD/PyMOL) detected

The skill calls `mdagent doctor` as part of its pre-flight; failure is
a structured error with one-line remediation.

### 2.5 Discoverability — how does a new user find this?

A teammate handed `skills/` doesn't know where to put it. Two flavors:

  - **Per-project**: drop the `skills/` directory next to the user's
    project. Claude Code reads it from there.
  - **User-global**: `~/.claude/skills/` (or wherever Claude's
    skill-search path is). Always available regardless of cwd.

The repo's `README.md` (or this tutorial notebook) should document both
patterns. The skill bodies themselves should not assume one or the other.

### 2.6 What I am NOT proposing

  - **PyPI publication.** That's a separate decision (project name +
    maintenance). For now `uv tool install --from git+...` is fine.
  - **Self-contained conda packages.** Overkill for a project that depends
    on system GROMACS + nothing exotic.
  - **A web service / SaaS frontend.** Out of scope.

### 2.7 Open questions I want your critique on

  1. **Is `uv tool install` the right primary install path?** Alternatives:
     `pipx install`, `pip install -e <git+url>`, plain `pip install`. The
     user is committed to `uv`, but the skill is supposed to be transferable
     to teammates — some of whom may not have `uv`. Should the skill
     document a `pipx` fallback?
  2. **Resource bundling via `importlib.resources` — any landmines I'm
     missing?** I've seen issues where editable installs of namespace
     packages misresolve resources. We're not using a namespace package
     (single top-level `mdagent`), but I want pushback.
  3. **`minimum_mdagent_version` in skill body** — is this enough, or do I
     also need a `supported_skill_version` field in the CLI so the CLI
     can also refuse to run with too-old skill metadata?
  4. **Skill placement** (per-project vs user-global) — is there a
     compelling reason to default to one or the other? Or to support
     both with a clear precedence?
  5. **Versioning the prompt catalog** — when the user upgrades their
     local GROMACS from 2026.2 → 2027.x, the recognizer regexes may
     break silently. What's the right defensive UX here? My current plan
     (`mdagent doctor` catches the version mismatch) is a runtime check
     only; should it be a *build-time* / *install-time* check too?
  6. **Tutorial notebook portability** — the notebook currently has cells
     like `cd /Users/manu_jay/...` baked in. Should the tutorial just use
     `mdagent ...` directly (relying on the installed CLI), or stay
     repo-relative for development?
  7. **Where does `gmx doctor`-style verification live** — inside `mdagent`
     itself as a subcommand, or as a separate `mdagent-check` script the
     skill calls? I lean toward the former (one binary, fewer moving parts).
  8. **Schema directory inside the package** — if I move `schemas/` into
     `src/mdagent/_resources/schemas/`, the repo's top-level `schemas/`
     directory disappears as a developer-readable thing. Should I keep a
     symlink, a README pointer, or just rely on people knowing to look
     in `src/`?
  9. **Tests today reference `runs/` and `tutorial/runs/` as repo-relative
     paths.** Are these tied to the working-directory assumption?
     (Looking at it now, they pass `tmp_path` via pytest fixtures, so
     they're fine.) But I want you to think about any other test that
     might silently assume repo-root cwd.
  10. **A path to PyPI later.** If we ever do publish, what should the
      package name be? `mdagent` is already taken on PyPI by something
      else; we'd need a different name. Does that affect the skill body
      (which references the binary name)? My plan: rename the package
      to `claude-md-agent` or similar at publish time, but the binary
      script stays `mdagent`. Sanity-check that.

---

## Section 3 — Critique prompt

You are an adversarial reviewer. Be critical. Be argumentative.
Find every hole: missing steps, wrong algebra, untested assumptions,
edge cases not addressed, implicit dependencies, claims without
evidence, off-by-one errors, sign errors, dimensional errors. Don't
be polite — if something is wrong, say so. Concision over hedging.

For each issue, state:
  - WHAT is wrong (specific, not vague — name the line or symbol)
  - WHY it matters (what breaks downstream if uncorrected)
  - WHAT to do (concrete fix, or what evidence would close the gap)

Number your issues. After all issues, end your response with exactly
one of these lines, no other text after it:

  VERDICT: APPROVED
  VERDICT: ISSUES_REMAIN

Use APPROVED only when there are no issues you would block on.
Minor nitpicks alone do not justify ISSUES_REMAIN — call them out
but still verdict APPROVED. Use ISSUES_REMAIN whenever any of your
issues are genuinely blocking.

Specifically:

**P1.** Of the 10 open questions in Section 2.7, which 2-3 do you think
are actually load-bearing for v0 transferability — i.e. if I get them
wrong, the design fails — vs. nitpicks?

**P2.** Is `uv tool install --from git+url` realistic as the primary
install path for a Claude-Code-using audience, or is `pipx` (or even
plain `pip install`) the safer choice given that many users won't have
`uv` yet?

**P3.** Are there any *Claude-Code-specific* issues with skill bodies
shelling out vs. doing things in-process I'm not anticipating? E.g.
working directory, env vars not inherited, output capture limits.
