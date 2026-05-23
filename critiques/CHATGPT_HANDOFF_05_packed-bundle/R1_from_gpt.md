1. **WHAT:** Vendored `mdagent-0.1.0-py3-none-any.whl` does not make install offline by itself.  
   **WHY:** Python wheels do not include dependencies. `uv tool install ./vendor/mdagent.whl[propka]` may still hit the network for `mdagent` dependencies and `propka`. That directly conflicts with the “packed/offline-safe” expectation.  
   **WHAT TO DO:** For v0, either vendor a full wheelhouse/lockfile and install from it, or explicitly scope “offline” to runtime only after setup. If PROPKA is optional, make `lysozyme_offline.json` require no PROPKA extras.

2. **WHAT:** GROMACS handling is more load-bearing than the current open-question ranking suggests.  
   **WHY:** The bundle can contain skills, configs, and code, but it still cannot run MD without `gmx`. A teammate’s first experience will fail here if this is vague.  
   **WHAT TO DO:** Do not auto-install GROMACS in v0. `setup.sh` should detect it, print exact install commands for macOS/Linux, and stop cleanly. Optionally support `./setup.sh --check-only`.

3. **WHAT:** `setup.sh` auto-installing `uv` via `curl | sh` is a security and trust problem.  
   **WHY:** A “drop this into a repo” bundle should avoid silently executing remote shell code. This is especially risky for teams and enterprise environments.  
   **WHAT TO DO:** Default to failing with instructions if `uv` is missing. Add `./setup.sh --auto-install-uv` only as an explicit opt-in.

4. **WHAT:** The proposed `run_simulation.sh` interface does not match the stated UX.  
   **WHY:** You say it “takes optional `--config` flag,” but the script only accepts positional args. `./run_simulation.sh --config run_configs/foo.json` would treat `--config` as the config path and fail.  
   **WHAT TO DO:** Add minimal flag parsing: `--config`, `--run-id`, `--help`. Keep positional fallback if desired.

5. **WHAT:** The three truly load-bearing v0 questions are Q1, Q4/Q5, and Q3 only secondarily.  
   **WHY:** Vendoring/install reproducibility decides whether the bundle is actually packed. `uv`/GROMACS prerequisite behavior decides whether setup is acceptable and predictable. The CLI shape matters, but `pack-bundle` vs `init-project --packed` is less important than the artifact actually installing and running.  
   **WHAT TO DO:** Prioritize: complete dependency strategy, explicit prerequisite policy, then stable bundle-generation command. Q8 is internal packaging mechanics, not v0-critical unless it blocks release automation.

6. **WHAT:** The bundle structure is basically right.  
   **WHY:** `setup.sh`, `run_simulation.sh`, `.claude/skills`, configs, bundled structure, `runs/`, and optional vendor artifacts map well to “easily run MD via Claude skills.” A Python entrypoint would reduce shell portability issues, but shell is fine for v0 because it is transparent and teammate-friendly.  
   **WHAT TO DO:** Keep the shell pair, but make them boring and robust: strict arg parsing, clear errors, no hidden network behavior, no auto system installs.

7. **WHAT:** “Packed” should produce both a folder and an archive.  
   **WHY:** The folder is easier to inspect, commit, and customize. The `.zip`/`.tar.gz` is what users intuitively expect when they say “packed bundle.”  
   **WHAT TO DO:** Build `mdagent pack-bundle DIR` as the canonical folder generator, plus `--zip` or `--archive` for distribution.

8. **WHAT:** Do not maintain separate skill copies for packed vs installed modes.  
   **WHY:** Divergent skill markdown will drift. Rewriting skill content during setup is also surprising.  
   **WHAT TO DO:** Template at pack time, not setup time. Generate bundle-specific install hints while materializing the bundle, and include the rendered files in `MANIFEST.json`.

VERDICT: ISSUES_REMAIN. The shape is right, but v0 needs a precise dependency/offline story, safer setup behavior, and a fixed run script interface before this is shipping-ready.