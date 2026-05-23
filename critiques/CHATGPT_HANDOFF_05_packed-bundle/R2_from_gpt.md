1. **WHAT:** The proposed wheelhouse build command is not valid in this uv version.  
   **WHY:** I checked locally: `uv 0.11.15` has no `uv pip download` subcommand. So `uv pip download --python 3.11 --dest ...` cannot be the v0 implementation path.  
   **WHAT TO DO:** Use `uv build` for the local `mdagent` wheel, `uv pip compile` for resolution, then either use `python -m pip download` to populate `vendor/wheels/`, or pick another tested wheel-fetch mechanism. Do not ship the contract with `uv pip download`.

2. **WHAT:** `setup.sh` always installs `propka`, even when the bundle was packed without `--with-propka`.  
   **WHY:** This line breaks plain `--with-vendor` bundles if `propka` wheels are absent:

   ```bash
   uv tool install ... --with propka mdagent
   ```

   **WHAT TO DO:** Make install conditional from bundle metadata. Either always include PROPKA in vendored bundles, or write `MANIFEST.json`/`bundle.json` with `includes_propka: true|false` and install `mdagent` vs `mdagent[propka]` accordingly.

3. **WHAT:** `--no-cache-dir` is not a valid `uv tool install` option here.  
   **WHY:** The local help exposes `--no-cache`, not `--no-cache-dir`. The current `setup.sh` install command will fail before it reaches dependency resolution.  
   **WHAT TO DO:** Use:

   ```bash
   uv tool install --force --no-cache --no-index \
     --find-links="$BUNDLE_ROOT/vendor/wheels" --offline \
     "mdagent"
   ```

   Or `"mdagent[propka]"` when the wheelhouse includes PROPKA.

4. **WHAT:** Platform tags are the remaining load-bearing design issue.  
   **WHY:** `gemmi` is not pure Python. A wheelhouse built on macOS arm64 is not generally valid for Linux x86_64, macOS x86_64, or other Python minor versions. One “universal” archive may either fail or grow beyond the size goal.  
   **WHAT TO DO:** For v0, make vendored bundles platform-specific unless you explicitly build a wheel matrix. Name it clearly in metadata/archive names, e.g. `mdagent-bundle-macos-arm64-py311.tar.gz`. If you want one archive, include wheels for every supported platform/Python combo and test each.

5. **WHAT:** Python version policy needs to be explicit.  
   **WHY:** The project requires `>=3.11`, but a wheelhouse resolved for Python 3.11 may not satisfy a target using 3.12/3.13, especially for compiled deps.  
   **WHAT TO DO:** Either pin setup to `--python 3.11` and fail cleanly if unavailable, or build wheelhouses per Python version. Add `--no-python-downloads` if hidden network access during setup is unacceptable.

6. **WHAT:** The overall bundle shape is approved.  
   **WHY:** Folder plus optional tarball, pre-rendered skills, offline structure, robust scripts, manifest hashes, and gmx/uv detection all match the user’s “packed bundle that runs MD” requirement. The remaining problems are in the wheelhouse/install mechanics, not the artifact model.  
   **WHAT TO DO:** Keep the structure. Fix the install/build contract and add tests that run `setup.sh` against an empty uv cache with `--offline --no-index`.

VERDICT: ISSUES_REMAIN. The design is close, but the current uv command contract and platform-specific wheelhouse story are blocking for v0.