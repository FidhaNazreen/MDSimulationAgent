#!/usr/bin/env bash
# verify.sh — sanity check that the starter kit + mdagent install are wired up.
#
# Default mode (no args): structural + config-schema checks only.
#   - No GROMACS required.
#   - No network required.
#
# With --run-smoke: also runs a short end-to-end MD pipeline on the
# bundled 1AKI structure. Requires GROMACS on PATH. ~2 min on M-series.

set -e

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"

# 1. mdagent installed?
command -v mdagent >/dev/null 2>&1 || {
  echo "✗ mdagent not found on PATH."
  echo "  Install: uv tool install --force git+https://github.com/FidhaNazreen/MDSimulationAgent@v0.1.0"
  exit 1
}
echo "  $(mdagent --version)"

# 2. Structural — every file in the kit exists.
expected_files=(
  README.md
  .gitignore
  MANIFEST.json
  structures/1aki.pdb
  structures/README.md
  run_configs/lysozyme_short.json
  run_configs/lysozyme_rcsb_tutorial.json
  run_configs/general_md_prep_example.json
  tutorial/getting_started.md
  runs/.gitkeep
  .claude/skills/md-run-workflow/SKILL.md
  .claude/skills/md-prep-structure/SKILL.md
  .claude/skills/md-visualize/SKILL.md
)
for f in "${expected_files[@]}"; do
  [[ -f "$REPO_ROOT/$f" ]] || { echo "✗ missing: $f"; exit 1; }
done
echo "  ✓ all kit files present (${#expected_files[@]} files)"

# 3. Config-schema validity.
for c in "$REPO_ROOT"/run_configs/*.json; do
  python3 -c "
import sys
from mdagent import RunConfig
RunConfig.from_file(sys.argv[1])
" "$c" || { echo "✗ config invalid: $c"; exit 1; }
  echo "  ✓ config valid: $(basename "$c")"
done

# 4. Smoke run (opt-in; requires GROMACS).
if [[ "${1:-}" == "--run-smoke" ]]; then
  echo
  echo "Running smoke test (requires GROMACS; ~2 min)..."
  mdagent doctor --gmx-required >/dev/null
  cd "$REPO_ROOT"
  rm -rf runs/smoke
  mdagent run-workflow --runs-root ./runs --config ./run_configs/lysozyme_short.json --run-id smoke
  if ! grep -q 'readiness: \*\*ready\*\*' runs/smoke/REPORT.md; then
    echo "✗ smoke run did not report 'ready'"
    exit 1
  fi
  echo "  ✓ smoke run produced 'ready' REPORT.md at runs/smoke/REPORT.md"
fi

echo
echo "✓ starter kit verified"
echo
echo "Next: mdagent run-workflow --runs-root ./runs --config ./run_configs/lysozyme_short.json --run-id demo"
