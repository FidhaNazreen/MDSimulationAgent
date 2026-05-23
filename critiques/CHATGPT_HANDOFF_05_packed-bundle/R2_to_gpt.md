# Round 2 counterreply

All 8 accepted. The biggest shape changes: full wheelhouse instead of
single-wheel vendor, no `curl | sh`, real arg parsing, skill
templating moves to pack-time.

## Section 1 — Per-issue acknowledgments

**R1-1** (single wheel doesn't make install offline). **Accept —
critical.** `mdagent pack-bundle --with-vendor` now produces a full
**wheelhouse** under `vendor/wheels/` containing `mdagent.whl` and
every dep (`jsonschema`, `pexpect`, `gemmi`, `propka` if requested,
plus their transitive deps) as wheels. `setup.sh` then runs:

```bash
uv tool install --force --no-cache-dir --find-links=./vendor/wheels --offline \
  --with propka mdagent
```

The `--offline` flag makes uv refuse to hit the network — if a wheel
is missing from the wheelhouse, install fails cleanly with the
missing-package name.

For the offline run path:
- `lysozyme_offline.json` uses `structure_path: ./structures/1aki.pdb`
  → no RCSB network at runtime.
- `protonation_policy` defaults to `ff_default` in the offline config
  → no PROPKA needed unless the user explicitly opts in via
  `propka_pH7.json` (which is documented as "needs the wheelhouse to
  have included propka, which `pack-bundle --with-vendor --with-propka`
  controls").

**R1-2** (GROMACS handling — don't auto-install). **Accept.**
`setup.sh` detects `gmx`; if absent, prints the exact install command
for the user's platform and exits non-zero. No auto-install. Added
`./setup.sh --check-only` mode that exits 0 on a green env without
attempting to install anything.

**R1-3** (`curl | sh` for uv is a security risk). **Accept.**
`setup.sh` default behavior: if `uv` is missing, print:

```
✗ uv is not on PATH. Install it via one of:
    macOS:        brew install uv
    Linux:        pipx install uv
    or official:  curl -LsSf https://astral.sh/uv/install.sh | sh
Re-run setup.sh after installing.
```

…and exit non-zero. Auto-install only via explicit
`./setup.sh --auto-install-uv`, which curl-pipes the official
installer.

**R1-4** (run_simulation.sh interface). **Accept.** Real arg parsing:

```
./run_simulation.sh [--config PATH] [--run-id ID] [--runs-root DIR] [--help]
```

Sensible defaults: `--config run_configs/lysozyme_offline.json`,
`--run-id demo-<timestamp>`, `--runs-root ./runs`. `--help` prints
usage and exits 0.

**R1-5** (load-bearing = Q1 deps + Q4/Q5 prereqs + Q3 only
secondary). **Accept.** Pinned: full wheelhouse for deps; no
auto-install of uv or gmx; new `pack-bundle` subcommand. Q8 (inside
the wheel) is settled — matches every other slice.

**R1-6** (shape is right; keep shell pair, make robust). **Accept.**
Both scripts use `set -euo pipefail`, proper arg parsing, no hidden
network, no auto system installs, clear `✓/✗` line formatting.

**R1-7** (packed = folder AND archive). **Accept.** Canonical
generator is `mdagent pack-bundle DIR`. Add `--archive` to also
produce `DIR.tar.gz` (tar over zip — better permissions handling on
Unix; widely supported). Bundle is self-contained in the folder; the
archive is just `tar -czf DIR.tar.gz DIR`.

**R1-8** (templated skills, not setup-time rewrite). **Accept.**
`pack-bundle` reads each packaged SKILL.md, substitutes the install
hint with `./setup.sh` text, and writes the rendered version into
`DIR/.claude/skills/<name>/SKILL.md`. MANIFEST.json records the
rendered files' sha256. No setup-time rewriting; what ships is what
runs.

## Section 2 — Updated artifact

### 2.1 Final bundle layout (`mdagent-bundle/`)

```
mdagent-bundle/
├── README.md                          # one screen; install + first run
├── setup.sh                           # detect-only by default; --auto-install-uv opt-in
├── run_simulation.sh                  # --config / --run-id / --runs-root / --help
├── MANIFEST.json                      # bundle version + sha256 per file
├── .claude/skills/                    # pre-templated for this bundle (install-hint rewritten)
│   ├── md-run-workflow/SKILL.md
│   ├── md-prep-structure/SKILL.md
│   └── md-visualize/SKILL.md
├── run_configs/
│   ├── lysozyme_offline.json          # bundled struct; ff_default; offline-runnable; ~2 min
│   ├── lysozyme_rcsb.json              # network fetch; full 1 ns
│   ├── propka_pH7.json                # opt-in; requires --with-propka at pack time
│   └── propka_pH5.json
├── structures/
│   ├── 1aki.pdb                       # CC0 from RCSB
│   └── README.md
├── vendor/                            # ONLY when --with-vendor was passed at pack time
│   └── wheels/                        # full wheelhouse (uv install --offline --find-links)
│       ├── mdagent-0.1.0-py3-none-any.whl
│       ├── jsonschema-X.Y.Z-py3-none-any.whl
│       └── ...
├── runs/.gitkeep
└── .gitignore                         # ignores runs/* and any local venvs
```

### 2.2 `mdagent pack-bundle` final contract

```
mdagent pack-bundle DIR [--force]
                        [--with-vendor]            # build full wheelhouse, ship in vendor/wheels/
                        [--with-propka]            # include propka + its deps in the wheelhouse
                        [--archive]                # also produce DIR.tar.gz
                        [--json]
```

- Refuses non-empty DIR without `--force`.
- `--with-vendor` calls `uv pip compile` (or `uv build` for mdagent
  itself) + `uv pip download` to materialize the wheelhouse. Honors
  `--with-propka` to add the propka extra.
- `--archive`: produces `<DIR>.tar.gz` alongside DIR.
- Always writes MANIFEST.json with `{version, generated_at,
  generated_by_mdagent_version, files: [{path, sha256, executable}]}`.
- Without `--with-vendor`, `setup.sh` falls back to the network
  install path (`uv tool install --force "mdagent[propka] @ git+…"`).

### 2.3 `setup.sh` final form

```bash
#!/usr/bin/env bash
set -euo pipefail

BUNDLE_ROOT="$(cd "$(dirname "$0")" && pwd)"
CHECK_ONLY=0
AUTO_INSTALL_UV=0

# Parse args
while [[ $# -gt 0 ]]; do
  case "$1" in
    --check-only) CHECK_ONLY=1; shift ;;
    --auto-install-uv) AUTO_INSTALL_UV=1; shift ;;
    --help|-h) cat <<EOF
setup.sh — install/verify the packed mdagent bundle.
  --check-only         Only verify env; never install anything.
  --auto-install-uv    If uv is missing, run the official installer.
                       (Default: fail cleanly with the install hint.)
EOF
      exit 0 ;;
    *) echo "unknown flag: $1" >&2; exit 2 ;;
  esac
done

# 1. uv must be present
if ! command -v uv >/dev/null 2>&1; then
  if [[ $AUTO_INSTALL_UV -eq 1 ]]; then
    echo "==> Installing uv via the official installer…"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.cargo/bin:$HOME/.local/bin:$PATH"
  else
    cat <<EOF
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

# 2. gmx must be present (we never auto-install GROMACS)
if ! command -v gmx >/dev/null 2>&1; then
  cat <<EOF
✗ GROMACS not on PATH. Install (one-time, per machine):
    macOS:    brew install gromacs
    Debian:   sudo apt-get install gromacs
    RPM:      sudo dnf install gromacs
EOF
  exit 1
fi
echo "  ✓ $(gmx --version 2>&1 | grep -E '^GROMACS version' | head -1)"

if [[ $CHECK_ONLY -eq 1 ]]; then
  echo "✓ environment OK (--check-only; no install performed)"
  exit 0
fi

# 3. Install mdagent
if [[ -d "$BUNDLE_ROOT/vendor/wheels" ]]; then
  echo "==> Installing mdagent from local wheelhouse (offline)…"
  uv tool install --force --no-cache-dir \
    --find-links="$BUNDLE_ROOT/vendor/wheels" --offline \
    --with propka mdagent
else
  echo "==> Installing mdagent from git tag (online)…"
  uv tool install --force "mdagent[propka] @ git+https://github.com/<user>/MDSimulationAgent@v0.1.0"
fi
echo "  ✓ $(mdagent --version)"

# 4. Doctor preflight
mdagent doctor --gmx-required >/dev/null
echo "  ✓ doctor passed"

echo
echo "✓ setup complete. Try:"
echo "    ./run_simulation.sh"
```

### 2.4 `run_simulation.sh` final form

```bash
#!/usr/bin/env bash
set -euo pipefail

CONFIG="run_configs/lysozyme_offline.json"
RUN_ID="demo-$(date +%Y%m%d-%H%M%S)"
RUNS_ROOT="./runs"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --config)    CONFIG="$2"; shift 2 ;;
    --run-id)    RUN_ID="$2"; shift 2 ;;
    --runs-root) RUNS_ROOT="$2"; shift 2 ;;
    --help|-h)   cat <<EOF
run_simulation.sh — run an MD simulation via the bundled Claude skills.
  --config PATH     Path to a run_config.json (default: run_configs/lysozyme_offline.json)
  --run-id ID       Run identifier under --runs-root (default: demo-<timestamp>)
  --runs-root DIR   Output dir (default: ./runs)
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

mdagent run-workflow --runs-root "$RUNS_ROOT" --config "$CONFIG" --run-id "$RUN_ID"
echo
mdagent inspect --run-root "$RUNS_ROOT/$RUN_ID"
```

### 2.5 Verification plan

  1. From the source repo: `mdagent pack-bundle /tmp/packed --with-vendor`.
  2. `cd /tmp/packed && ./setup.sh --check-only` → passes.
  3. `./setup.sh` → installs mdagent from the wheelhouse offline.
  4. `./run_simulation.sh` → uses the bundled 1AKI, exits 0 with
     `readiness: **ready**` in the report.
  5. Re-pack: `mdagent pack-bundle /tmp/packed` (no --force) → refused.
  6. `mdagent pack-bundle /tmp/packed --force` → succeeds, rewrites
     files.
  7. `mdagent pack-bundle /tmp/packed --archive --with-vendor` →
     also writes `/tmp/packed.tar.gz`; extracted copy is byte-equal.
  8. (Optional) `mdagent pack-bundle --with-vendor --with-propka` →
     PROPKA + deps included; `propka_pH7.json` runs offline.

### 2.6 Tests

`tests/test_pack_bundle.py`:

  - Fast: `pack-bundle DIR` materializes every expected file +
    `setup.sh` is executable + MANIFEST.json hashes match;
    refuse-on-non-empty; `--force` works; templated SKILL.md no
    longer contains the raw upstream `git+` install hint
    (replaced with `./setup.sh`).
  - Slow + gmx-gated: `pack-bundle --with-vendor` → install from
    wheelhouse offline + run a 2-min smoke through the bundled
    `setup.sh` + `run_simulation.sh`.

## Section 3 — Final critique prompt

Apply the original threshold strictly:

  VERDICT: APPROVED
  VERDICT: ISSUES_REMAIN

`APPROVED` if no blocking holes; nitpicks alone don't justify
`ISSUES_REMAIN`.

One clarification:

**C1.** For the wheelhouse, I'm planning to use `uv pip download
--python 3.11 --dest vendor/wheels mdagent[propka] @ <local-wheel>` to
fetch every dep as a wheel matching the target Python. Is that the
right uv command? Any platform-tag gotchas (macOS arm64 vs x86_64,
Linux glibc tags)?
