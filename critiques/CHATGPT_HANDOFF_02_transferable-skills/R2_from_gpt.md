1. **C1: passing `files()` straight to `sha256_dir` is wrong.**  
`sha256_dir` requires a real filesystem tree. A Traversable is not that contract. Do not rely on `Path(traversable)`.  
What to do: for v0, explicitly support normal wheel/editable installs only. Return a concrete `Path` when the resource object is filesystem-backed; otherwise raise `UnsupportedResourceInstall` with “zipapp/import-from-archive is unsupported.” Do not add process-lifetime extraction unless you actually need zipapp support.

2. **C1: `as_file()` around a directory is not clean under your Python floor.**  
You require Python 3.11. Directory support in `importlib.resources.as_file()` is version-sensitive enough that making it the core path is a bad bet.  
What to do: avoid archive-resource support for v0, or add the `importlib_resources` backport and test directory extraction explicitly. The pragmatic v0 answer is “resources must be unpacked on disk,” which uv-installed wheels are.

3. **C2: “copy at build time” is still a weak plan.**  
You are introducing a second source of truth plus a build hook you have not proven `uv_build` supports in the way you want.  
Why it matters: stale copied schemas are worse than missing schemas because tests may read one copy while wheels ship another.  
What to do: make `src/mdagent/_resources/schemas/` the canonical source. Keep top-level `schemas/README.md` as a pointer, or add a dev-only script that mirrors resources outward for readability. Do not make top-level schemas canonical unless CI verifies the package copy is byte-identical.

4. **C2: do not use symlinks.**  
You already named the reason: Windows/CI friction. Symlinks add no value here.  
What to do: canonical in-package resources, README pointer at top level.

5. **`install-skills` cannot copy `.claude/skills/*` from an installed tool unless those skills are packaged.**  
Moving repo skills to `.claude/skills/` helps project discovery in this repo, but a uv-installed console script does not have access to the repo checkout.  
What to do: ship skills as package resources too, e.g. `src/mdagent/_resources/skills/<name>/SKILL.md`. `install-skills` copies from that packaged resource tree. The repo may also have `.claude/skills/`, but that cannot be the installer’s source.

6. **Hidden `.claude/skills` may be excluded from sdists/wheels.**  
Dot directories are easy to accidentally omit depending on backend include rules.  
What to do: do not rely on packaging root `.claude/skills`. Package from `src/mdagent/_resources/skills`, and test the installed wheel can run `mdagent install-skills --dry-run` and find every skill.

7. **C3: yes, conditionally enable network/viewer checks, but your timing is wrong.**  
Network is needed at ingest, not before topology. If `input.pdb_id` is set, checking network “before topology” is too late.  
What to do: after config resolution and before orchestrator execution, run config-derived doctor checks: network for `input.pdb_id`, GROMACS for any step at/after topology, viewers only if visualization is requested.

8. **C3: viewer checks should not block script generation.**  
Your visualization architecture says scripts are written unconditionally and rendering is best-effort. A failed VMD/PyMOL probe must not block `visualization.mode=requested` if `--render state_only` or equivalent is acceptable.  
What to do: split viewer checks into `viewer_binary_available`, `renderer_available`, and `required_for_requested_output`.

9. **`doctor --json` contract is internally inconsistent.**  
You say default-JSON output, then say human text to stderr suppressed under `--json`. Pick one.  
What to do: make default human, `--json` machine-readable. Under `--json`, stdout is only JSON. Suggestions belong inside `errors[].suggestion`, not stderr.

10. **`doctor --suggest-install` conflicts with the skill preflight unless it is JSON-compatible.**  
If the skill calls `mdagent doctor --json --suggest-install`, it should not scrape stderr.  
What to do: include install hints in the JSON object. Let `--suggest-install` control whether hints are populated, not where they are printed.

11. **R1-12 defense is too optimistic about PATH.**  
“Same as any other PATH binary” is not good enough. Claude Code may be launched from an environment that does not include uv’s tool bin directory.  
What to do: README must include `uv tool dir --bin` / shell PATH setup guidance. The skill’s failure message should say both “mdagent not found” and “uv tool bin may not be on Claude Code’s PATH.”

12. **Pinned git tags make `uv tool upgrade mdagent` ambiguous as upgrade guidance.**  
If the install source is `@v0.1.0`, upgrade may just reinstall the pinned tag.  
What to do: document upgrades as reinstalling a newer tag: `uv tool install --force git+https://...@v0.2.0` or the exact tested uv command. Do not imply a pinned install magically tracks newer tags.

13. **`prep-structure` as both a real subcommand and “proxy to run-workflow --stop-after prep” needs one public contract.**  
If you add `prep-structure`, users should not need to know `--stop-after`.  
What to do: implement `--stop-after` internally if useful, but document `mdagent prep-structure` as the stable skill interface.

14. **`--no-doctor` is a footgun unless scoped.**  
A global escape hatch can bypass exactly the checks that make skills transferable.  
What to do: require `--no-doctor` to print a warning unless `--quiet`, and still record `doctor_skipped: true` in provenance/report. Better: offer narrower skips like `--skip-network-check`.

15. **Wheel smoke test is still too shallow for the resource bug.**  
`mdagent run-workflow --help` does not prove schemas load from the wheel.  
What to do: add an installed-env command that actually imports `mdagent.schemas`, loads every schema, hashes the schemas dir, and runs `doctor --json`. Ideally add `mdagent self-test resources --json`.

VERDICT: ISSUES_REMAIN