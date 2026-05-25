"""mdagent pack-bundle — materialize a shipping-ready packed bundle.

The bundle (`mdagent-bundle/`) is a self-contained directory a teammate
can drop into a fresh repo, run `./setup.sh`, then `./run_simulation.sh`,
and have a working MD-simulation environment driven by the Claude skills.

What goes in:
  - README.md (one-screen quick start)
  - setup.sh, run_simulation.sh (executable; --help, no piped curl)
  - MANIFEST.json (bundle metadata + per-file sha256)
  - .claude/skills/<name>/SKILL.md (pre-templated for this bundle)
  - run_configs/*.json (offline + RCSB + PROPKA examples)
  - structures/1aki.pdb (CC0 from RCSB; offline-safe smoke)
  - runs/.gitkeep + .gitignore
  - vendor/wheels/* (only when --with-vendor was passed at pack time;
    full wheelhouse for this host's platform/Python)

Critique-loop pins:
  - "Packed" = folder + optional `<DIR>.tar.gz`.
  - Wheelhouse via `python -m pip download` (uv has no `pip download`).
  - Offline install: `uv tool install --python 3.11 --no-python-downloads
    --force --no-cache --no-index --offline --find-links=...`.
  - Platform/Python-specific bundles only (encoded in archive name).
  - PROPKA opt-in via `--with-propka` (implies `--with-vendor`).
  - Skills templated at pack time (install hint → `./setup.sh`).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from importlib.metadata import version as _pkg_version
from pathlib import Path
from typing import Any

from ._resources import _filesystem_path

# ---- platform detection ------------------------------------------------


def detect_platform() -> tuple[str, str]:
    """Return (human_name, pip_platform_tag).

    human_name is for display: 'macos-arm64' / 'macos-x86_64' /
    'linux-x86_64' / 'linux-arm64' / 'unknown'.

    pip_platform_tag is the value to pass to `pip download --platform`.
    """
    from packaging.tags import sys_tags
    # Pick the most-preferred tag matching cp311.
    preferred = None
    for t in sys_tags():
        if t.interpreter == "cp311" and t.abi == "cp311":
            preferred = t
            break
    if preferred is None:
        # Fall back to whatever the current Python advertises.
        preferred = next(iter(sys_tags()))
    pip_tag = preferred.platform

    # Map to a human-readable name.
    import platform
    sys_name = sys.platform
    machine = platform.machine().lower()
    if sys_name == "darwin":
        if machine in ("arm64", "aarch64"):
            human = "macos-arm64"
        elif machine in ("x86_64", "amd64"):
            human = "macos-x86_64"
        else:
            human = f"macos-{machine}"
    elif sys_name.startswith("linux"):
        if machine in ("x86_64", "amd64"):
            human = "linux-x86_64"
        elif machine in ("aarch64", "arm64"):
            human = "linux-arm64"
        else:
            human = f"linux-{machine}"
    else:
        human = f"{sys_name}-{machine}"
    return human, pip_tag


# ---- skill templating --------------------------------------------------


def _template_skill_for_bundle(skill_md_text: str) -> str:
    """Rewrite the skill's install hint to point at ./setup.sh.

    Idempotent: if the marker is missing, returns the text unchanged.
    """
    # Replace any `uv tool install --force git+...` install hint with the
    # bundle-aware version. The replacement is conservative — we look for
    # the canonical install snippet and swap in a "run ./setup.sh" line.
    replacements = [
        (
            "uv tool install --force git+https://github.com/FidhaNazreen/MDSimulationAgent@v0.1.0",
            "(packed bundle) run ./setup.sh from the bundle root",
        ),
        (
            'uv tool install --force "mdagent[propka] @ git+https://github.com/FidhaNazreen/MDSimulationAgent@v0.1.0"',
            "(packed bundle) run ./setup.sh from the bundle root",
        ),
        (
            'uv tool install --force "mdagent[tutorials] @ git+https://github.com/FidhaNazreen/MDSimulationAgent@v0.1.0"',
            "(packed bundle) run ./setup.sh from the bundle root",
        ),
    ]
    out = skill_md_text
    for old, new in replacements:
        out = out.replace(old, new)
    return out


# ---- wheelhouse build --------------------------------------------------


def _build_wheelhouse(
    *,
    target_dir: Path,
    pip_platform_tag: str,
    with_propka: bool,
    repo_root: Path,
) -> list[str]:
    """Materialize a full wheelhouse into target_dir.

    Builds the local mdagent wheel via `uv build`, then `pip download`s
    every transitive dep into target_dir.
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    # 1. Build mdagent locally.
    with tempfile.TemporaryDirectory() as td:
        local_wheel_dir = Path(td)
        r = subprocess.run(
            ["uv", "build", "--wheel", "--out-dir", str(local_wheel_dir)],
            cwd=str(repo_root), capture_output=True, text=True,
        )
        if r.returncode != 0:
            raise RuntimeError(f"`uv build` failed:\n{r.stderr}")
        wheels = list(local_wheel_dir.glob("mdagent-*.whl"))
        if not wheels:
            raise RuntimeError("uv build produced no mdagent wheel")
        local_wheel = wheels[0].resolve()
        # Copy the local wheel into the wheelhouse.
        shutil.copy(local_wheel, target_dir / local_wheel.name)

        # 2. pip download every dep (and optionally propka) for the target
        # platform / Python.
        spec = f"{local_wheel}"
        if with_propka:
            spec = f"{local_wheel}[propka]"
        r = subprocess.run(
            [
                sys.executable, "-m", "pip", "download",
                "--dest", str(target_dir),
                "--only-binary", ":all:",
                "--python-version", "3.11",
                "--platform", pip_platform_tag,
                "--implementation", "cp",
                "--abi", "cp311",
                spec,
            ],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            raise RuntimeError(
                f"`pip download` failed for spec={spec!r} platform={pip_platform_tag!r}:\n{r.stderr[-2000:]}"
            )

    return sorted(p.name for p in target_dir.glob("*.whl"))


# ---- manifest helpers --------------------------------------------------


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# ---- script + README content ------------------------------------------


def _setup_sh() -> str:
    return r"""#!/usr/bin/env bash
# setup.sh — install/verify the packed mdagent bundle.
#
# Default: detect-only for missing tools (uv, gmx). Fails cleanly with
# install hints. Pass --auto-install-uv to run the official uv installer.
# Use --check-only to verify the env without installing mdagent itself.

set -euo pipefail

BUNDLE_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$BUNDLE_ROOT"

CHECK_ONLY=0
AUTO_INSTALL_UV=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --check-only) CHECK_ONLY=1; shift ;;
    --auto-install-uv) AUTO_INSTALL_UV=1; shift ;;
    --help|-h) cat <<EOF
setup.sh — install/verify the packed mdagent bundle.
  --check-only         Only verify env; do not install mdagent.
  --auto-install-uv    If uv is missing, run the official curl-based installer.
                       Default: fail cleanly with the install hint.
EOF
      exit 0 ;;
    *) echo "unknown flag: $1" >&2; exit 2 ;;
  esac
done

# Detect host platform
detect_platform() {
  local sys_name="$(uname -s)"
  local machine="$(uname -m)"
  case "$sys_name-$machine" in
    Darwin-arm64|Darwin-aarch64)   echo "macos-arm64" ;;
    Darwin-x86_64|Darwin-amd64)    echo "macos-x86_64" ;;
    Linux-x86_64|Linux-amd64)      echo "linux-x86_64" ;;
    Linux-aarch64|Linux-arm64)     echo "linux-arm64" ;;
    *) echo "${sys_name,,}-${machine}" ;;
  esac
}

# 1. uv on PATH?
if ! command -v uv >/dev/null 2>&1; then
  if [[ $AUTO_INSTALL_UV -eq 1 ]]; then
    echo "==> Installing uv via the official installer (--auto-install-uv)…"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.cargo/bin:$HOME/.local/bin:$PATH"
  else
    cat >&2 <<EOF
✗ uv is not on PATH. Install it via one of:
    macOS:        brew install uv
    Linux:        pipx install uv
    or official:  curl -LsSf https://astral.sh/uv/install.sh | sh
Re-run setup.sh after installing, or pass --auto-install-uv.
EOF
    exit 1
  fi
fi
echo "  ✓ $(uv --version)"

# 2. gmx on PATH? (never auto-installed)
if ! command -v gmx >/dev/null 2>&1; then
  cat >&2 <<EOF
✗ GROMACS not on PATH. Install (one-time, per machine):
    macOS:     brew install gromacs
    Debian:    sudo apt-get install gromacs
    Fedora:    sudo dnf install gromacs
Then re-run setup.sh.
EOF
  exit 1
fi
echo "  ✓ $(gmx --version 2>&1 | grep -E '^GROMACS version' | head -1)"

if [[ $CHECK_ONLY -eq 1 ]]; then
  echo "✓ environment OK (--check-only; no install performed)"
  exit 0
fi

# 3. Install mdagent — offline if vendor/ exists, otherwise online.
INCLUDES_PROPKA="$(python3 -c "import json; print(json.load(open('MANIFEST.json'))['includes_propka'])")"
INCLUDES_VENDOR="$(python3 -c "import json; print(json.load(open('MANIFEST.json'))['includes_vendor'])")"

if [[ "$INCLUDES_VENDOR" == "True" ]]; then
  # Platform + Python guards
  PYTHON_OK="$(python3 -c "import sys; print(1 if sys.version_info[:2] == (3, 11) else 0)")"
  if [[ "$PYTHON_OK" != "1" ]]; then
    echo "✗ Vendored bundle requires Python 3.11. Got $(python3 --version)." >&2
    exit 1
  fi
  BUNDLE_PLATFORM="$(python3 -c "import json; print(json.load(open('MANIFEST.json'))['platform'])")"
  HOST_PLATFORM="$(detect_platform)"
  if [[ "$BUNDLE_PLATFORM" != "$HOST_PLATFORM" ]]; then
    echo "✗ Bundle platform ($BUNDLE_PLATFORM) does not match host ($HOST_PLATFORM)." >&2
    echo "  Repack on this host, or use the no-vendor (network) bundle." >&2
    exit 1
  fi
  SPEC="mdagent"
  [[ "$INCLUDES_PROPKA" == "True" ]] && SPEC="mdagent[propka]"
  echo "==> Installing $SPEC offline from $BUNDLE_ROOT/vendor/wheels …"
  uv tool install --python 3.11 --no-python-downloads \
    --force --no-cache --no-index --offline \
    --find-links="$BUNDLE_ROOT/vendor/wheels" \
    "$SPEC"
else
  if [[ "$INCLUDES_PROPKA" == "True" ]]; then
    ONLINE_SPEC="mdagent[propka] @ git+https://github.com/FidhaNazreen/MDSimulationAgent@v0.1.0"
  else
    ONLINE_SPEC="mdagent @ git+https://github.com/FidhaNazreen/MDSimulationAgent@v0.1.0"
  fi
  echo "==> Installing online: $ONLINE_SPEC"
  uv tool install --force "$ONLINE_SPEC"
fi
echo "  ✓ $(mdagent --version)"

# 4. Doctor preflight
mdagent doctor --gmx-required >/dev/null
echo "  ✓ doctor passed"

echo
echo "✓ setup complete. Try:"
echo "    ./run_simulation.sh"
"""


def _run_simulation_sh() -> str:
    return r"""#!/usr/bin/env bash
# run_simulation.sh — run an MD simulation via the bundled Claude skills.

set -euo pipefail

BUNDLE_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$BUNDLE_ROOT"

CONFIG="run_configs/lysozyme_offline.json"
RUN_ID="demo-$(date +%Y%m%d-%H%M%S)"
RUNS_ROOT="./runs"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --config)    CONFIG="$2"; shift 2 ;;
    --run-id)    RUN_ID="$2"; shift 2 ;;
    --runs-root) RUNS_ROOT="$2"; shift 2 ;;
    --help|-h) cat <<EOF
run_simulation.sh — run an MD simulation via the bundled Claude skills.
  --config PATH      Path to a run_config.json (default: $CONFIG)
  --run-id ID        Run identifier under --runs-root (default: demo-<timestamp>)
  --runs-root DIR    Output dir (default: $RUNS_ROOT)
EOF
      exit 0 ;;
    *) echo "unknown flag: $1" >&2; exit 2 ;;
  esac
done

command -v mdagent >/dev/null 2>&1 || { echo "Run ./setup.sh first." >&2; exit 1; }

echo "==> Running MD simulation"
echo "    config:    $CONFIG"
echo "    run-id:    $RUN_ID"
echo "    runs-root: $RUNS_ROOT"
echo

mdagent run-workflow --runs-root "$RUNS_ROOT" --config "$CONFIG" --run-id "$RUN_ID"
echo
mdagent inspect --run-root "$RUNS_ROOT/$RUN_ID"
"""


def _readme_md() -> str:
    return """# mdagent — packed bundle

A self-contained MD-simulation environment driven by Claude skills.

## What's here

```
./
├── setup.sh             # one-time install (uv + gmx detection)
├── run_simulation.sh    # run an MD simulation
├── .claude/skills/      # 3 Claude skills, pre-installed
├── run_configs/         # example configs
├── structures/1aki.pdb  # bundled CC0 lysozyme (offline-safe smoke)
├── runs/                # output dir
├── MANIFEST.json        # bundle metadata + sha256 per file
└── vendor/wheels/       # OPTIONAL — full offline wheelhouse
```

## First run

```bash
./setup.sh                # detects uv + gmx; installs mdagent
./run_simulation.sh       # runs a 2-min MD on the bundled lysozyme
```

When it finishes, look at:

- `runs/demo-<timestamp>/REPORT.md` — headline `readiness: **ready**`
- `runs/demo-<timestamp>/step_10_analysis/analysis.json` — Rg / RMSD / etc.

## Use with Claude Code

Open a Claude Code session in this directory and ask:

> *"Set up lysozyme in water and minimize it."*

Claude reads `.claude/skills/md-run-workflow/SKILL.md` and drives the
pipeline. The full skill bodies are in `.claude/skills/<name>/SKILL.md`.

## Configs you can run

| Config | What | Network |
|---|---|---|
| `run_configs/lysozyme_offline.json` | bundled 1AKI + EM + 2 ps NVT + 2 ps NPT + 4 ps production + analysis | none |
| `run_configs/lysozyme_rcsb.json` | fetch 1AKI from RCSB; full 1 ns tutorial | yes |
| `run_configs/propka_pH7.json` | PROPKA-driven protonation at pH 7 | none (if vendor includes propka) |
| `run_configs/propka_pH5.json` | same at pH 5; HIS-15 flips to HIP | none (if vendor includes propka) |

Use a non-default config with:

```bash
./run_simulation.sh --config run_configs/propka_pH7.json --run-id pka7
```

## What's NOT here

- GROMACS itself — install via `brew install gromacs` /
  `apt-get install gromacs` / equivalent.
- Tutorials — ship separately via `mdagent tutorials extract DIR`.
- Source code for mdagent — installed as a console script by `./setup.sh`.

## Re-pack

To rebuild this bundle from a newer mdagent source:

```bash
mdagent pack-bundle ./mdagent-bundle --with-vendor --with-propka --archive --force
```
"""


def _gitignore() -> str:
    return "runs/*\n!runs/.gitkeep\n.DS_Store\n.venv/\n"


# ---- top-level driver --------------------------------------------------


def materialize_bundle(
    *,
    dest: Path,
    with_vendor: bool,
    with_propka: bool,
    force: bool,
    archive: bool,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Materialize the packed bundle into `dest`.

    Returns a payload dict with the materialized file list + manifest.
    """
    if with_propka and not with_vendor:
        with_vendor = True  # --with-propka implies --with-vendor

    dest = Path(dest).resolve()
    if dest.exists() and any(dest.iterdir()) and not force:
        raise FileExistsError(
            f"refusing to pack into non-empty directory: {dest} (use --force to overwrite)"
        )
    dest.mkdir(parents=True, exist_ok=True)

    if repo_root is None:
        # mdagent.pack is at src/mdagent/pack.py → repo_root = src/mdagent/.. /..
        repo_root = Path(__file__).resolve().parent.parent.parent

    # 1. The static parts (scripts, README, structures, configs, skills, runs).
    materialized: list[dict[str, Any]] = []

    def _write_file(rel_path: str, content: str | bytes, *, executable: bool = False) -> None:
        out = dest / rel_path
        out.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            out.write_bytes(content)
        else:
            out.write_text(content)
        if executable:
            os.chmod(out, 0o755)
        materialized.append({
            "path": rel_path,
            "sha256": _sha256_file(out),
            "executable": executable,
        })

    _write_file("README.md", _readme_md())
    _write_file("setup.sh", _setup_sh(), executable=True)
    _write_file("run_simulation.sh", _run_simulation_sh(), executable=True)
    _write_file(".gitignore", _gitignore())
    _write_file("runs/.gitkeep", "")

    # 2. Structures (from the starter kit's bundled 1AKI).
    starter = _filesystem_path("mdagent._resources.starter_kit")
    for rel in ("structures/1aki.pdb", "structures/README.md"):
        src_path = starter / rel
        _write_file(rel, src_path.read_bytes() if rel.endswith(".pdb") else src_path.read_text())

    # 3. Run configs — reuse the starter kit's offline + general configs,
    # plus add PROPKA pH7/pH5 examples.
    for rel in ("run_configs/lysozyme_short.json", "run_configs/lysozyme_rcsb_tutorial.json"):
        src_path = starter / rel
        # Rename: lysozyme_short.json → lysozyme_offline.json for clarity in this bundle.
        dest_name = {
            "run_configs/lysozyme_short.json": "run_configs/lysozyme_offline.json",
            "run_configs/lysozyme_rcsb_tutorial.json": "run_configs/lysozyme_rcsb.json",
        }[rel]
        _write_file(dest_name, src_path.read_text())

    # PROPKA examples (only meaningful if vendor includes propka, but the
    # config files themselves are useful documentation regardless).
    propka_base = json.loads((starter / "run_configs" / "general_md_prep_example.json").read_text())
    for ph in (7.0, 5.0):
        cfg = json.loads(json.dumps(propka_base))  # deep copy
        cfg["pipeline_mode"] = "general_md_prep"
        cfg["protonation_policy"] = "propka"
        cfg["ph"] = ph
        # Point at the bundle's local 1AKI; setup.sh runs from BUNDLE_ROOT so
        # ./structures/1aki.pdb is the right relative path.
        cfg["input"] = {"structure_path": "./structures/1aki.pdb", "format_preference": "pdb"}
        _write_file(f"run_configs/propka_pH{int(ph)}.json",
                    json.dumps(cfg, indent=2, sort_keys=True))

    # 4. Skills — copy + template install hint.
    skills_src = _filesystem_path("mdagent._resources.skills")
    for skill_dir in sorted(skills_src.iterdir()):
        if not skill_dir.is_dir() or not (skill_dir / "SKILL.md").is_file():
            continue
        skill_text = (skill_dir / "SKILL.md").read_text()
        templated = _template_skill_for_bundle(skill_text)
        _write_file(f".claude/skills/{skill_dir.name}/SKILL.md", templated)

    # 5. Wheelhouse (optional).
    pip_platform_tag = ""
    platform_name, pip_platform_tag = detect_platform()
    wheelhouse_files: list[str] = []
    if with_vendor:
        wh_dir = dest / "vendor" / "wheels"
        wheelhouse_files = _build_wheelhouse(
            target_dir=wh_dir,
            pip_platform_tag=pip_platform_tag,
            with_propka=with_propka,
            repo_root=repo_root,
        )
        for wheel_name in wheelhouse_files:
            wp = wh_dir / wheel_name
            materialized.append({
                "path": f"vendor/wheels/{wheel_name}",
                "sha256": _sha256_file(wp),
                "executable": False,
            })

    # 6. MANIFEST.json (written last; not included in its own files list).
    manifest = {
        "manifest_schema_version": "1.0.0",
        "bundle_kind": "packed-mdagent-bundle",
        "mdagent_version": _pkg_version("mdagent"),
        "generated_at": _utc_now_iso(),
        "platform": platform_name,
        "pip_platform_tag": pip_platform_tag,
        "python": "3.11",
        "includes_vendor": bool(with_vendor),
        "includes_propka": bool(with_propka),
        "files": sorted(materialized, key=lambda x: x["path"]),
    }
    (dest / "MANIFEST.json").write_text(json.dumps(manifest, indent=2, sort_keys=False))

    # 7. Archive (optional).
    archive_path: str | None = None
    if archive:
        archive_name = f"{dest.name}-{platform_name}-py311.tar.gz"
        archive_path = str(dest.parent / archive_name)
        with tarfile.open(archive_path, "w:gz") as tf:
            tf.add(dest, arcname=dest.name)

    return {
        "destination": str(dest),
        "manifest": manifest,
        "wheelhouse_files": wheelhouse_files,
        "archive_path": archive_path,
    }
