# Round 3 counterreply

All 6 accepted. Fixed uv command contract, made PROPKA opt-in via
bundle metadata, pinned platform/Python tags into archive names.

## Section 1 — Per-issue acknowledgments

**R2-1** (`uv pip download` doesn't exist). **Accept.** Wheelhouse
populated via `python -m pip download`:

```python
# In _materialize_wheelhouse(target_dir, with_propka):
import subprocess, sys
specs = ["mdagent"]
if with_propka:
    specs = ["mdagent[propka]"]
# The local wheel for mdagent is built via `uv build --wheel`; then
# pip-download fetches all transitive deps as wheels into target_dir,
# resolving against the local wheel.
subprocess.run([
    sys.executable, "-m", "pip", "download",
    "--dest", str(target_dir),
    "--only-binary", ":all:",
    "--python-version", "3.11",
    "--platform", platform_tag,             # e.g. macosx_14_0_arm64
    "--implementation", "cp",
    "--abi", "cp311",
    *specs,
    "--find-links", str(local_wheel_dir),
], check=True)
```

This is bog-standard pip and works against any uv-managed venv.

**R2-2** (setup.sh always installs propka). **Accept.** Bundle's
`MANIFEST.json` gains `includes_propka: bool`. setup.sh reads it and
picks the install spec:

```bash
INCLUDES_PROPKA=$(python3 -c "import json; print(json.load(open('MANIFEST.json'))['includes_propka'])")
if [[ "$INCLUDES_PROPKA" == "True" ]]; then
  SPEC="mdagent[propka]"
else
  SPEC="mdagent"
fi
uv tool install ... "$SPEC"
```

**R2-3** (`--no-cache-dir` is wrong; need `--no-cache --no-index`).
**Accept.** Final install command in setup.sh:

```bash
uv tool install --force --no-cache --no-index --offline \
  --find-links="$BUNDLE_ROOT/vendor/wheels" \
  "$SPEC"
```

`--no-index` is the critical addition — without it, uv could still
hit PyPI as a fallback when the wheelhouse is incomplete.

**R2-4** (platform tags — gemmi is compiled). **Accept — critical.**
For v0 the bundle archive name includes platform + Python tag:

```
mdagent-bundle-<platform>-<py>.tar.gz
```

Where `<platform>` is one of `macos-arm64`, `macos-x86_64`,
`linux-x86_64`, `linux-arm64`, and `<py>` is `py311`. The
`pack-bundle` CLI auto-detects the host's platform/Python and embeds
those in:

  - The archive filename: `mdagent-bundle-macos-arm64-py311.tar.gz`
  - The MANIFEST.json: `platform: "macos-arm64", python: "3.11"`

setup.sh reads MANIFEST and refuses to run if the host's
platform/Python don't match — with a clean error pointing at the
correct bundle filename.

Multi-platform bundles ("universal") are explicitly out of v0 scope.

**R2-5** (Python version policy explicit). **Accept.** v0 is
Python-3.11-only for vendored bundles. `pack-bundle --with-vendor`
fails if `sys.version_info[:2] != (3, 11)`. setup.sh asserts
`python3 --version | grep '3.11'` before running the offline
install, exiting cleanly if mismatched.

Non-vendored bundles (no `--with-vendor`) have no Python pin — they
use the network path which uv handles.

**R2-6** (bundle shape approved). **Accept.** Implementation
proceeds with the structural design from R2 + the install-command
fixes above + the platform-tag policy.

## Section 2 — Updated artifact

### 2.1 MANIFEST.json schema (final)

```json
{
  "manifest_schema_version": "1.0.0",
  "bundle_kind": "packed-mdagent-bundle",
  "mdagent_version": "0.1.0",
  "generated_at": "2026-05-23T…Z",
  "platform": "macos-arm64",
  "python": "3.11",
  "includes_vendor": true,
  "includes_propka": false,
  "files": [
    {"path": "README.md", "sha256": "…", "executable": false},
    {"path": "setup.sh", "sha256": "…", "executable": true},
    …
  ]
}
```

### 2.2 `pack-bundle` final CLI

```
mdagent pack-bundle DIR
        [--force]
        [--with-vendor]              # build wheelhouse for this host's platform/Python
        [--with-propka]              # include propka in the wheelhouse
        [--archive]                  # also produce DIR-<platform>-<py>.tar.gz
        [--json]
```

Notes:
- `--with-propka` implies `--with-vendor` (we don't ship a network
  install hint that auto-adds propka — too magic).
- `--with-vendor` without `--with-propka` ships a wheelhouse for
  `mdagent` only; the bundle's setup.sh installs without the propka
  extra; the bundle's PROPKA configs are documented as "needs
  --with-propka at pack time".
- `--archive` names the archive based on MANIFEST's platform + python.

### 2.3 setup.sh — final install command

```bash
PYTHON_OK="$(python3 -c "import sys; print('1' if sys.version_info[:2] == (3, 11) else '0')")"
if [[ "$PYTHON_OK" != "1" ]] && [[ -d "$BUNDLE_ROOT/vendor/wheels" ]]; then
  echo "✗ Bundle requires Python 3.11. Detected $(python3 --version)." >&2
  echo "  Install via uv or your OS package manager and re-run." >&2
  exit 1
fi

BUNDLE_PLATFORM="$(python3 -c "import json; print(json.load(open('MANIFEST.json'))['platform'])")"
HOST_PLATFORM="$(_detect_platform)"   # bash function: returns macos-arm64 | linux-x86_64 | …
if [[ -d "$BUNDLE_ROOT/vendor/wheels" ]] && [[ "$BUNDLE_PLATFORM" != "$HOST_PLATFORM" ]]; then
  echo "✗ Bundle platform $BUNDLE_PLATFORM doesn't match host $HOST_PLATFORM." >&2
  echo "  Either repack on this host, or use the no-vendor (network) bundle." >&2
  exit 1
fi

INCLUDES_PROPKA="$(python3 -c "import json; print(json.load(open('MANIFEST.json'))['includes_propka'])")"
SPEC="mdagent"
[[ "$INCLUDES_PROPKA" == "True" ]] && SPEC="mdagent[propka]"

if [[ -d "$BUNDLE_ROOT/vendor/wheels" ]]; then
  uv tool install --force --no-cache --no-index --offline \
    --find-links="$BUNDLE_ROOT/vendor/wheels" \
    "$SPEC"
else
  uv tool install --force "${SPEC}@ git+https://github.com/<user>/MDSimulationAgent@v0.1.0"
fi
```

## Section 3 — Final critique prompt

Apply the original threshold strictly:

  VERDICT: APPROVED
  VERDICT: ISSUES_REMAIN
