# Round 4 counterreply

All 5 accepted. Final install/build contract:

## Section 1 — Per-issue acknowledgments

**R3-1** (uv must be pinned to Python 3.11 for vendored install).
**Accept.** Final offline install:

```bash
uv tool install --python 3.11 --no-python-downloads \
  --force --no-cache --no-index --offline \
  --find-links="$BUNDLE_ROOT/vendor/wheels" \
  "$SPEC"
```

`--no-python-downloads` prevents uv from silently downloading a
managed interpreter — keeping the offline guarantee strict.

**R3-2** (pip download must resolve against the direct wheel path).
**Accept.** Wheelhouse builder:

```python
# After `uv build --wheel -o <local_wheel_dir>` produces
# mdagent-0.1.0-py3-none-any.whl, build the spec from the file path:
local_wheel = next(local_wheel_dir.glob("mdagent-*.whl"))
extras = "[propka]" if with_propka else ""
spec = f"{local_wheel}{extras}"   # direct-URL spec; pip resolves to *this* file
subprocess.run([
    sys.executable, "-m", "pip", "download",
    "--dest", str(target_dir),
    "--only-binary", ":all:",
    "--python-version", "3.11",
    "--platform", pip_platform_tag,    # see R3-5
    "--implementation", "cp",
    "--abi", "cp311",
    spec,
], check=True)
shutil.copy(local_wheel, target_dir)   # also keep the mdagent wheel in the wheelhouse
```

**R3-3** (online install spec malformed). **Accept.** Online path
uses proper PEP 508 form with explicit space before `@`:

```bash
if [[ "$INCLUDES_PROPKA" == "True" ]]; then
  ONLINE_SPEC="mdagent[propka] @ git+https://github.com/<user>/MDSimulationAgent@v0.1.0"
else
  ONLINE_SPEC="mdagent @ git+https://github.com/<user>/MDSimulationAgent@v0.1.0"
fi
uv tool install --force "$ONLINE_SPEC"
```

**R3-4** (manifest reads must use $BUNDLE_ROOT). **Accept.** setup.sh
runs `cd "$BUNDLE_ROOT"` once near the top, after computing it.
Every relative path is then unambiguous. Belt-and-suspenders: every
Python one-liner explicitly uses
`open('$BUNDLE_ROOT/MANIFEST.json')`.

**R3-5** (platform tag mapping). **Accept.** MANIFEST.json stores
BOTH:

```json
{
  "platform": "macos-arm64",          // human-readable
  "pip_platform_tag": "macosx_11_0_arm64"  // pip --platform argument
}
```

`pack-bundle` computes the pip tag via `packaging.tags`:

```python
from packaging.tags import sys_tags
preferred = next(t for t in sys_tags() if t.abi == "cp311" and t.interpreter == "cp311")
pip_platform_tag = preferred.platform   # e.g. "macosx_11_0_arm64"
```

setup.sh uses only the human-readable `platform` for host matching;
the pip tag is build-side metadata that lets the user inspect what
the wheelhouse targets without re-deriving it.

## Section 2 — Updated artifact (delta)

### 2.1 Final MANIFEST.json schema

```json
{
  "manifest_schema_version": "1.0.0",
  "bundle_kind": "packed-mdagent-bundle",
  "mdagent_version": "0.1.0",
  "generated_at": "2026-05-23T…Z",
  "platform": "macos-arm64",
  "pip_platform_tag": "macosx_11_0_arm64",
  "python": "3.11",
  "includes_vendor": true,
  "includes_propka": false,
  "files": [
    {"path": "README.md", "sha256": "…", "executable": false},
    {"path": "setup.sh", "sha256": "…", "executable": true},
    ...
  ]
}
```

### 2.2 Final setup.sh install block

```bash
cd "$BUNDLE_ROOT"

PYTHON_OK="$(python3 -c "import sys; print(1 if sys.version_info[:2] == (3, 11) else 0)")"

if [[ -d "$BUNDLE_ROOT/vendor/wheels" ]]; then
  # Vendored install path
  if [[ "$PYTHON_OK" != "1" ]]; then
    echo "✗ Vendored bundle requires Python 3.11. Got $(python3 --version)." >&2
    exit 1
  fi
  BUNDLE_PLATFORM="$(python3 -c "import json; print(json.load(open('MANIFEST.json'))['platform'])")"
  HOST_PLATFORM="$(detect_platform)"
  if [[ "$BUNDLE_PLATFORM" != "$HOST_PLATFORM" ]]; then
    echo "✗ Bundle platform $BUNDLE_PLATFORM ≠ host $HOST_PLATFORM." >&2
    exit 1
  fi
  INCLUDES_PROPKA="$(python3 -c "import json; print(json.load(open('MANIFEST.json'))['includes_propka'])")"
  SPEC="mdagent"
  [[ "$INCLUDES_PROPKA" == "True" ]] && SPEC="mdagent[propka]"
  uv tool install --python 3.11 --no-python-downloads \
    --force --no-cache --no-index --offline \
    --find-links="$BUNDLE_ROOT/vendor/wheels" \
    "$SPEC"
else
  # Online install path
  INCLUDES_PROPKA="$(python3 -c "import json; print(json.load(open('MANIFEST.json'))['includes_propka'])")"
  if [[ "$INCLUDES_PROPKA" == "True" ]]; then
    ONLINE_SPEC="mdagent[propka] @ git+https://github.com/<user>/MDSimulationAgent@v0.1.0"
  else
    ONLINE_SPEC="mdagent @ git+https://github.com/<user>/MDSimulationAgent@v0.1.0"
  fi
  uv tool install --force "$ONLINE_SPEC"
fi
```

## Section 3 — Final critique prompt

Apply the original threshold strictly:

  VERDICT: APPROVED
  VERDICT: ISSUES_REMAIN

`APPROVED` if no blocking holes; nitpicks alone don't justify
`ISSUES_REMAIN`.
