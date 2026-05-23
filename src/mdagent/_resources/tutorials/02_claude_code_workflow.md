<!-- mdagent:requires mdagent -->
<!-- mdagent:title Claude Code workflow -->

# 02 — Using mdagent from Claude Code

**Requirements:** mdagent only.

This tutorial explains *what Claude actually does* when you ask it to
run an MD simulation, so you can predict its behavior, debug it, and
extend it.

## The three skills

`mdagent install-skills` (called automatically by `init-project`)
places three `SKILL.md` files under `.claude/skills/`:

| Skill | Trigger phrasings | Underlying CLI |
|---|---|---|
| `md-run-workflow` | *"run an MD simulation on…"*, *"set up X in water"*, *"equilibrate at 300 K"* | `mdagent run-workflow ...` |
| `md-prep-structure` | *"clean PDB X"*, *"prep but don't run dynamics"*, *"fetch and validate"* | `mdagent prep-structure ...` (no GROMACS needed) |
| `md-visualize` | *"render the solvated box"*, *"VMD picture"*, *"visualize this run"* | `mdagent visualize ...` |

Each `SKILL.md` has YAML frontmatter that lists trigger keywords
(`description:`) and a `metadata.skill_version`. Claude Code's
matcher reads the frontmatter to decide which skill to invoke.

## Skill preflight

Every skill's body starts with a verbatim preflight block that:

1. Checks `mdagent` is on PATH; if not, prints the exact install command.
2. Calls `mdagent doctor --json --min-version 0.1.0 --skill-name <name> --skill-version 1.0.0`.
3. Exits non-zero on doctor failure (with the structured JSON visible).

That guarantees a failed first-run produces a deterministic,
copy-pasteable install hint rather than a cryptic Python traceback.

## Examples — phrasings → CLI

| User prompt | Skill chosen | CLI Claude runs |
|---|---|---|
| *"Do the lysozyme tutorial."* | `md-run-workflow` | `mdagent run-workflow --runs-root ./runs --pdb-id 1AKI --run-id demo` |
| *"Set up 6LU7 in water at pH 6.5 using PROPKA-driven protonation."* | `md-run-workflow` | builds a config with `pipeline_mode: general_md_prep`, `protonation_policy: propka`, `ph: 6.5` |
| *"Prep PDB 1AKI but don't run dynamics."* | `md-prep-structure` | `mdagent prep-structure --runs-root ./runs --pdb-id 1AKI` |
| *"Show me the EM-minimized lysozyme structure."* | `md-visualize` | `mdagent visualize --run-root ./runs/demo --viewer auto --checkpoints em --render both` |
| *"Why did topology fail in this run?"* | (no skill — Claude reads run-dir directly) | inspects `step_04_topology/step_report.json:failure_reason` |

## Test it yourself

Open a Claude Code session in a freshly-scaffolded project:

```bash
mdagent init-project ./tutorial_demo
cd ./tutorial_demo
claude     # opens Claude Code with this dir as cwd
```

Then ask:

> *"Run the lysozyme tutorial in tutorial_reproduction mode and stop after solvation."*

Claude will:

1. Notice `md-run-workflow` matches the request.
2. Run the preflight (`command -v mdagent` + `mdagent doctor ...`).
3. Build the right `mdagent run-workflow` invocation with
   `--stop-after solvation`.
4. Surface the per-step statuses and the REPORT.md.
5. If anything fails, surface the structured `failure_reason` from
   the offending step's `step_report.json`.

## Why this design

- **Skills are documentation, not code** — they tell Claude how to
  call the CLI. The CLI is the only execution surface. That makes the
  whole system auditable: every action Claude takes is a `mdagent ...`
  command you can run yourself.
- **No magic** — Claude doesn't "know" MD; it knows how to drive a
  well-documented CLI. If the CLI exits non-zero with a structured
  failure, Claude surfaces the failure verbatim.
- **Transferable** — the same skills work in any directory that has
  `.claude/skills/` populated, with no source checkout.

## Next

- **03 — Configs and modes** — how to ask Claude for non-default
  parameters via natural language.
- **08 — Failure triage** — what each failure code means and how to
  prompt your way to a fix.
