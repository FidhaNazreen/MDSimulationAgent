1. **Short config and verification contradict each other.**  
WHAT: `lysozyme_short.json` disables production, but the verification plan expects `step_10_analysis/analysis.json` and Rg around 1.4 nm. Current pipeline skips analysis when production is disabled.  
WHY: Your proposed golden-path proof cannot pass as written.  
WHAT TO DO: Either make `lysozyme_short.json` include tiny production, e.g. `production.enabled=true`, `nsteps=2000`, `nstxout_compressed=200`, or change the verification assertions to EM/NPT artifacts only.

2. **`verify.sh` does not verify the starter kit.**  
WHAT: It checks installed `mdagent` resources, GROMACS, and network, but not the generated project files, project-local skills, config validity, executable workflow, or current-directory usability.  
WHY: A broken `init-project` could still pass.  
WHAT TO DO: Add checks for `.claude/skills/*/SKILL.md`, the three config files, `runs/.gitkeep`, and JSON schema validity. Keep the actual MD run as a separate smoke command or add `./verify.sh --run-smoke`.

3. **The starter-kit resources will not all ship unless packaging changes.**  
WHAT: Current package-data appears to include `_resources/**/*.json` and `_resources/**/*.md`, but not `.sh`, `.ipynb`, `.gitignore`, `.gitkeep`, or extensionless files.  
WHY: `init-project` may work from checkout and fail from an installed wheel.  
WHAT TO DO: Explicitly include `src/mdagent/_resources/starter_kit/**/*` in `pyproject.toml`, and add a wheel-install test that materializes the kit from the built wheel.

4. **`verify.sh` has an avoidable `jq` dependency.**  
WHAT: `jq -e .ok` makes the first-run check fail on many otherwise valid machines.  
WHY: The starter kit is supposed to reduce setup burden; this adds a second tool users did not ask for.  
WHAT TO DO: Use `python3 -c 'import json,sys; sys.exit(not json.load(sys.stdin)["ok"])'`, or better, make `mdagent doctor` and `self-test` return nonzero reliably and skip JSON parsing entirely.

5. **The offline story is not coherent.**  
WHAT: The kit bundles no sample structure, while `verify.sh --check-network` and configs rely on RCSB/1AKI.  
WHY: “Clone/copy this folder and reproduce the workflow” is fragile if the first run depends on live internet.  
WHAT TO DO: Bundle `structures/1aki.pdb` or a minimal validated sample, make `lysozyme_short.json` use `structure_path`, and keep a separate RCSB tutorial config for network-backed reproduction.

6. **`init-project --json` can be polluted by internal `install-skills` output.**  
WHAT: If you call the existing `install-skills` command internally, it prints its own JSON.  
WHY: `--json` stdout must be one parseable object.  
WHAT TO DO: Refactor skill installation into a shared function returning a payload. `cmd_install_skills` prints it; `cmd_init_project` embeds it.

7. **Overwrite semantics are underspecified and risky.**  
WHAT: `--force` says overwrite existing files, but does not say whether unrelated files survive, whether partial writes roll back, or whether existing `.claude/skills` are clobbered.  
WHY: This command targets repository roots; destructive surprises are expensive.  
WHAT TO DO: Default: refuse non-empty. `--force`: overwrite only files in a manifest, leave unrelated files alone, report collisions, and write atomically via temp dir where practical.

8. **Executable permissions may not survive materialization.**  
WHAT: `./verify.sh` assumes executable mode. Wheel/resource copying may not preserve it consistently.  
WHY: The advertised first command can fail with “permission denied.”  
WHAT TO DO: Always `chmod 0755` after writing `verify.sh`.

9. **The notebook duplicates config content and will drift.**  
WHAT: The notebook writes `lysozyme_short.json` even though that config is already shipped.  
WHY: Two canonical versions of the starter config will diverge.  
WHAT TO DO: The notebook should read/use the shipped config. If it demonstrates editing, write a derived `run_configs/tutorial_local.json`.

10. **Jupyter as the primary tutorial format is too heavy.**  
WHAT: `.ipynb` requires notebook tooling that is not part of the stated setup.  
WHY: New users may have a working CLI but no way to open the tutorial cleanly.  
WHAT TO DO: Ship `tutorial/getting_started.md` as primary and generate the notebook as an optional companion.

11. **The `general_md_prep_example.json` is not reproducible by one command.**  
WHAT: It uses interactive `pdb2gmx -inter` behavior.  
WHY: It can hang or prompt unexpectedly in automation.  
WHAT TO DO: Label it clearly as interactive-only, exclude it from `verify.sh`, and set `interaction_mode` intentionally.

12. **Load-bearing open questions for v0:**  
Questions 2, 3 if Windows is in scope, 5, 7, 9, and 10 affect reproducibility or upgrade behavior. Questions 1, 4, 6, and 8 are mostly product-shape decisions, not blockers. For question 3, a cross-platform `verify.py` is better than adding only `verify.ps1`.

13. **Verification plan is not sufficient yet.**  
WHAT: Copying to `/tmp`, running `verify.sh`, then running one short workflow is close, but it misses installed-wheel packaging, no-checkout execution, manifest completeness, executable bit, project skills, and rerun/force behavior.  
WHY: Those are exactly the transferability risks introduced by this feature.  
WHAT TO DO: Test from a built wheel in a fresh venv with no `PYTHONPATH`, run `mdagent init-project`, assert manifest, run `./verify.sh`, run short workflow, assert `REPORT.md`, assert either EM convergence or analysis depending on chosen short config, and test refusal on non-empty target.

14. **Bundling inside the wheel is the right call.**  
WHAT: A separate template repo adds version skew and network dependency.  
WHY: The starter kit must match the CLI/schema/skills version that materialized it.  
WHAT TO DO: Bundle it via `importlib.resources`, add a manifest/version file, and document `mdagent init-project --force` or `mdagent install-skills --project .` as the refresh path.

VERDICT: ISSUES_REMAIN