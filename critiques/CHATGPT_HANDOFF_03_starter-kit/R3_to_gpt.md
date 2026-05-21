# Round 3 counterreply

All 7 accepted with concrete fixes. The biggest are R2-1 (verify default
must be offline + no-gmx-required) and R2-4 (resolve relative
`structure_path` against the config file dir).

## Section 1 — Per-issue acknowledgments

**R2-1** (`verify.sh` default still requires network + gmx). **Accept.**
Final `verify.sh` default = structural + config-schema checks only. No
network, no gmx. The smoke run that needs gmx + (optionally) network
sits under `--run-smoke`:

```bash
# Default — offline, no gmx required:
./verify.sh
# Smoke run — requires gmx (and the rcsb config requires network):
./verify.sh --run-smoke
```

Inside `--run-smoke`, network is only checked when the config has
`input.pdb_id` set (the bundled `lysozyme_short.json` uses
`structure_path` so no network is needed).

**R2-2** (comment before YAML frontmatter breaks skill parsing). **Accept
— critical fix.** Generation metadata goes *inside* the existing
`metadata:` block in the frontmatter. So a freshly-materialized
SKILL.md ends up like:

```yaml
---
name: md-run-workflow
description: ...
metadata:
  minimum_mdagent_version: "0.1.0"
  skill_version: "1.0.0"
  generated_by: "mdagent 0.1.0"
  generated_at: "2026-05-21T01:00:00Z"
---
```

No bytes before the opening `---`.

**R2-3** (`MANIFEST.json` self-reference). **Accept.** Defining the
manifest as the list of materialized **payload** files (everything
except `MANIFEST.json`). The manifest itself just has
`manifest_schema_version: "1.0.0"` recorded. The kit's `verify.sh`
asserts `MANIFEST.json` exists and parses; for each entry in the
`files` array it asserts the file exists.

**R2-4** (relative `structure_path` is cwd-dependent). **Accept.**
Updating `RunConfig.from_file(path)` to:

  - Resolve `input.structure_path` relative to the config file's parent
    directory (not the cwd of the invoker).
  - Resolve absolute paths as-is.
  - Document the behavior in the schema's `description` for that field.

This makes `mdagent run-workflow --config /any/where/lysozyme_short.json`
work regardless of cwd. The change is small and back-compat for
absolute paths.

**R2-5** (inline comment field would break the schema). **Accept.**
Dropping the inline comment idea. `general_md_prep_example.json` is
just a valid config; the user-facing explanation of its trade-offs
lives in `tutorial/getting_started.md` (a dedicated section).

**R2-6** (`install-skills --force` doesn't exist). **Accept.** Adding
`--force` to `install-skills`. Default still overwrites existing files
(matching the current behavior), but `--force` is an explicit opt-in
for users who want a "just blow away whatever's there" knob. The
README's upgrade snippet uses `--force` so users have a no-ambiguity
command to copy-paste.

Actually — re-reading the current implementation: `install-skills`
already overwrites whatever exists at the destination (`shutil.copy2`
+ `copytree(..., dirs_exist_ok=True)`). So `--force` is purely
semantic — for users who want to assert their intent. Adding it as a
no-op (records the flag in JSON output but doesn't change behavior),
documented as "explicit clear-and-rewrite".

**R2-7** (1aki.pdb bundling is fine, with attribution). **Accept.**
Including `structures/README.md` in the kit with:
  - Source URL: `https://files.rcsb.org/download/1AKI.pdb`.
  - Download date.
  - DOI: `https://doi.org/10.2210/pdb1AKI/pdb`.
  - License note: PDB archive coordinate files are CC0 1.0; cite
    Diamond, R. (1974). J Mol Biol 82(3):371-391 for the structure.

## Section 2 — Updated artifact (delta)

### 2.1 Final `verify.sh`

```bash
#!/usr/bin/env bash
set -e

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"

# 1. mdagent installed (always required).
command -v mdagent >/dev/null 2>&1 || { echo "mdagent not found on PATH."; exit 1; }
mdagent --version

# 2. Structural: every file in the kit exists.
for f in \
  README.md \
  .gitignore \
  MANIFEST.json \
  structures/1aki.pdb structures/README.md \
  run_configs/lysozyme_short.json \
  run_configs/lysozyme_rcsb_tutorial.json \
  run_configs/general_md_prep_example.json \
  tutorial/getting_started.md \
  runs/.gitkeep \
  .claude/skills/md-run-workflow/SKILL.md \
  .claude/skills/md-prep-structure/SKILL.md \
  .claude/skills/md-visualize/SKILL.md
do
  [[ -f "$REPO_ROOT/$f" ]] || { echo "missing: $f"; exit 1; }
done

# 3. Config-schema validity for every shipped config.
for c in "$REPO_ROOT"/run_configs/*.json; do
  python3 -c "
import sys
from mdagent import RunConfig
RunConfig.from_file(sys.argv[1])
" "$c" || { echo "config invalid: $c"; exit 1; }
done

if [[ "${1:-}" == "--run-smoke" ]]; then
  cd "$REPO_ROOT"
  # Needs gmx; the config uses structure_path so no network.
  mdagent doctor --gmx-required
  rm -rf runs/smoke
  mdagent run-workflow --runs-root ./runs --config ./run_configs/lysozyme_short.json --run-id smoke
  grep -q "readiness: \*\*ready\*\*" runs/smoke/REPORT.md || { echo "smoke run did not report ready"; exit 1; }
  echo "✓ smoke run produced a 'ready' REPORT"
fi
echo "✓ starter kit verified"
```

### 2.2 RunConfig change

```python
class RunConfig:
    @classmethod
    def from_file(cls, path: str | Path) -> "RunConfig":
        path = Path(path).resolve()
        with open(path) as f:
            data = json.load(f)
        # Resolve relative input.structure_path against the config file's dir.
        structure_path = (data.get("input") or {}).get("structure_path")
        if structure_path and not Path(structure_path).is_absolute():
            data["input"]["structure_path"] = str((path.parent / structure_path).resolve())
        return cls(data)
```

Schema's `description` for `input.structure_path` gets:
"Path to a local PDB or mmCIF file. Relative paths are resolved
against the directory containing the run_config.json file. Absolute
paths are taken as-is."

### 2.3 `install-skills --force`

```
mdagent install-skills (--user | --project DIR) [--force] [--dry-run]
```

`--force` is recorded in the JSON output as `force: true`; no behavior
change vs. default (already overwrites). Documented as "explicit
overwrite confirmation".

## Section 3 — Final critique prompt

Apply the original threshold:

  VERDICT: APPROVED
  VERDICT: ISSUES_REMAIN

`APPROVED` if there are no blocking holes; nitpicks alone don't justify
`ISSUES_REMAIN`.

One targeted question:

**C1.** Is making `--force` a no-op on `install-skills` (purely
semantic) acceptable, or should it actually *change* behavior — e.g.
delete the destination dir before re-copying, so deleted skills don't
linger? I lean toward making it actually delete + recopy (so removing
a skill from a new mdagent version + running --force gives a clean
state). Counter-argument welcome.
