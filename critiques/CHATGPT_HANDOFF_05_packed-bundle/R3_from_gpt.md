1. **WHAT:** Offline install still does not force uv to use Python 3.11.  
   **WHY:** `setup.sh` checks `python3`, but `uv tool install` may choose a different compatible interpreter unless told otherwise. A py311 wheelhouse can fail if uv selects 3.12/3.13.  
   **WHAT TO DO:** For vendored bundles, install with:

   ```bash
   uv tool install --python 3.11 --no-python-downloads \
     --force --no-cache --no-index --offline \
     --find-links="$BUNDLE_ROOT/vendor/wheels" \
     "$SPEC"
   ```

2. **WHAT:** `pip download` should resolve against the exact local `mdagent` wheel, not the name `mdagent`.  
   **WHY:** With `specs = ["mdagent"]` and `--find-links`, pip can still consider indexes. If a package named `mdagent` exists remotely, or version precedence changes, the wheelhouse could be built from the wrong artifact.  
   **WHAT TO DO:** Pass the local wheel path as the requirement, ideally with extras when needed, e.g. direct wheel path / PEP 508 file URL. Keep `--find-links` only as supporting input, not as the identity of the package.

3. **WHAT:** The non-vendored git install spec is probably malformed.  
   **WHY:** This:

   ```bash
   "${SPEC}@ git+https://..."
   ```

   is not the same as the PEP 508 form:

   ```bash
   "mdagent[propka] @ git+https://..."
   ```

   **WHAT TO DO:** Build the online spec separately:

   ```bash
   ONLINE_SPEC="mdagent @ git+https://github.com/mjayadharan/MDSimulationAgent@v0.1.0"
   [[ "$INCLUDES_PROPKA" == "True" ]] && ONLINE_SPEC="mdagent[propka] @ git+https://..."
   ```

4. **WHAT:** Manifest reads should use `$BUNDLE_ROOT`.  
   **WHY:** `open('MANIFEST.json')` fails if someone runs `/path/to/setup.sh` from another working directory.  
   **WHAT TO DO:** Use `"$BUNDLE_ROOT/MANIFEST.json"` in every Python one-liner, or `cd "$BUNDLE_ROOT"` once after computing it.

5. **WHAT:** Platform naming needs a strict mapping layer.  
   **WHY:** User-facing names like `linux-x86_64` are not pip platform tags. pip wants tags like `manylinux2014_x86_64` / `macosx_11_0_arm64` / similar.  
   **WHAT TO DO:** Store both names if helpful: `platform: "macos-arm64"` for humans and `pip_platform_tag: "macosx_11_0_arm64"` for wheelhouse generation.

VERDICT: ISSUES_REMAIN. The bundle design is approved, but the exact install/build command contract still has blocking correctness issues around Python selection, local wheel identity, and the online install spec.