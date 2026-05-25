Docs checked: uv tools docs (https://docs.astral.sh/uv/guides/tools/) and Claude Code skills docs (https://code.claude.com/docs/en/skills).

1. **The proposed uv install command is wrong.**  
`uv tool install --from git+https://... mdagent` is `uvx` syntax, not `uv tool install` syntax. Current `uv tool install --help` takes one `<PACKAGE>` and no `--from`.  
Why it matters: the first install command in the skill fails.  
What to do: use `uv tool install git+https://github.com/mjayadharan/MDSimulationAgent` or a pinned ref: `uv tool install git+https://github.com/mjayadharan/MDSimulationAgent@v0.1.0`.

2. **P1 load-bearing questions are Q1/Q4, Q2, and Q5.**  
Install/discovery, resource bundling, and GROMACS compatibility decide whether transferability works at all. Version sentinels, PyPI naming, tutorial style, and schema-directory aesthetics are secondary for v0.

3. **`skills/` is not a valid Claude Code project skill location by itself.**  
Claude Code discovers project skills from `.claude/skills/<skill>/SKILL.md` and personal skills from `~/.claude/skills/<skill>/SKILL.md`. Your repo has `skills/md-run-workflow/SKILL.md`.  
Why it matters: a teammate can clone the repo and Claude Code may not discover the skills.  
What to do: either move/copy to `.claude/skills/`, document an install command that copies them there, or package them as plugin skills.

4. **`uv tool install` is realistic, but only if you make uv itself the bootstrap dependency.**  
Do not add `pipx install mdagent` as a peer fallback unless you actually test and support it. The project has chosen uv; the safer fallback is “install uv via brew/curl/pipx, then use uv tool install.”  
Why it matters: multiple install paths double the support matrix.  
What to do: document `brew install uv` / official uv installer / `pipx install uv`, then one mdagent install path.

5. **Git install from an unpinned branch is not reproducible.**  
`git+https://github.com/mjayadharan/MDSimulationAgent` means “whatever main is today.”  
Why it matters: skill text and CLI can drift silently across teammates.  
What to do: recommend tags: `git+https://github.com/mjayadharan/MDSimulationAgent@v0.1.0`; use `uv tool upgrade mdagent --reinstall` or reinstall with a new tag.

6. **Resource bundling proposal is incomplete.**  
`importlib.resources.files("mdagent") / "_resources" / ...` returns a Traversable, not guaranteed to be a concrete `Path`. Your code passes `schemas_dir()` into `sha256_dir()`, which immediately wraps it in `Path()` and uses `rglob`.  
Why it matters: this may break under non-filesystem loaders, and it is not tested against built wheels.  
What to do: either keep resources as real package files and test wheel installs, or make hashing/loading Traversable-aware. Add a test that builds a wheel, installs it into a clean venv/tool env, and runs schema loading plus `run-workflow --help`.

7. **`[project.scripts]` is necessary but not sufficient.**  
The proposed script target is fine, but the parser still says `prog="python -m mdagent"`, and there is no installed-command smoke test.  
Why it matters: docs, help text, and skill examples stay inconsistent.  
What to do: add `mdagent = "mdagent.cli:main"`, change `prog="mdagent"`, and test invoking the console script from an installed wheel.

8. **`mdagent --version` does not exist.**  
`__version__` exists, but argparse has no `--version`.  
Why it matters: the skill preflight cannot do the proposed minimum-version check.  
What to do: add `p.add_argument("--version", action="version", version=f"mdagent {__version__}")`, preferably reading installed metadata via `importlib.metadata.version("mdagent")`.

9. **The skill-version sentinel is weak.**  
A `minimum_mdagent_version` line buried in Markdown is not a reliable interface, and shell semver comparison is easy to get wrong. It also only catches old CLI with new skill, not old skill with new CLI.  
Why it matters: stale skills can still issue obsolete flags or omit required checks.  
What to do: put `minimum_mdagent_version` and `skill_version` in YAML frontmatter, and expose `mdagent doctor --min-version X --skill-name Y --skill-version Z --json`.

10. **`doctor` is the right place, but it must be enforced inside `run-workflow`, not only by the skill.**  
Skills are advisory; users can run the binary directly.  
Why it matters: unsupported GROMACS versions can still hit `DialogueRunner` and fail late.  
What to do: add `mdagent doctor` and also run the critical checks inside `run-workflow` before topology unless `--no-doctor` or equivalent is explicitly set.

11. **The current CLI lies about GROMACS version.**  
`--gmx-version` defaults to `2026.2` and gets written into config, regardless of the actual `gmx --version`.  
Why it matters: provenance/config can claim compatibility when the system is running something else.  
What to do: resolve actual GROMACS version at runtime; make config-requested version a constraint, not a default fact.

12. **Claude-Code-specific shell risks are real.**  
Claude Code skill execution inherits the session environment, which may not match an interactive terminal. PATH, Homebrew paths, GROMACS env vars, display variables for VMD/PyMOL, and output truncation can all bite.  
Why it matters: `command -v gmx` can fail in Claude Code while working in the user’s shell, and long GROMACS logs can be clipped.  
What to do: keep skill shell commands tiny; make `mdagent doctor --json` concise; write verbose logs to files; print only artifact paths and structured summaries.

13. **`md-prep-structure` is not transferable because it has no CLI surface.**  
The skill currently shells into a Python one-liner and imports internal APIs.  
Why it matters: installed tools should expose stable commands, not private call graphs.  
What to do: add `mdagent prep-structure` or `mdagent run-workflow --stop-after prep`, then rewrite the skill around that.

14. **`md-visualize` references a CLI subcommand that does not exist.**  
`src/mdagent/cli.py` only has `run-workflow` and `inspect`.  
Why it matters: the rewritten skill will still fail after installation.  
What to do: add `mdagent visualize` or remove the skill until the CLI exists.

15. **Tutorial portability should use the installed CLI for users and repo-relative commands only for contributors.**  
A notebook with `uv run python -m mdagent` teaches the old coupling.  
Why it matters: it contradicts the transferable-skill model.  
What to do: split “user tutorial” from “developer tutorial,” or gate developer cells behind an explicit editable-checkout section.

16. **Top-level schema removal will hurt developer usability.**  
Moving schemas into `src/mdagent/_resources/schemas` is technically right for wheels, but hiding them without a pointer is hostile.  
Why it matters: schemas are part of the public contract, not an implementation detail.  
What to do: keep a top-level `schemas/README.md` pointer, or keep top-level schemas as source and copy them into package resources during build with a tested mechanism.

17. **Future PyPI naming does not require changing the binary.**  
Distribution name, import package, and console script can differ.  
Why it matters: renaming the binary later would break every skill.  
What to do: if PyPI `mdagent` is unavailable, publish as something like `claude-md-agent` but keep `mdagent` as the console script.

VERDICT: ISSUES_REMAIN