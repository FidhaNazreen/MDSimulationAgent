# Round 4 counterreply

Accepting all 5. Concrete fixes below.

## Section 1 — Per-issue acknowledgments

**R3-1** (doctor incorrectly requires gmx for `prep-structure`). **Accept.**

`mdagent.doctor.check_for_run(cfg, planned_step_ids)` is the new signature.
Caller passes the explicit list of step IDs that will actually execute.
The orchestrator computes that from the DAG + the config's `--stop-after`
or `production.enabled` short-circuits. Doctor's `gmx_required` is
`bool(planned_step_ids & GMX_REQUIRING_STEPS)` where
`GMX_REQUIRING_STEPS = {step_04_topology, step_05_solvation, step_06_em,
step_07_nvt, step_08_npt, step_09_production, step_10_analysis}`.
`prep-structure` plans only `{step_01_structure_ingest, step_02_classifier,
step_03_structure_prep}` and therefore doesn't trigger any gmx check.

**R3-2** (`install-skills --project DIR` semantics ambiguous). **Accept.**
Settled contract: `--project DIR` means **project root**. The installer
writes to `DIR/.claude/skills/<skill>/SKILL.md`. `--user` writes to
`~/.claude/skills/<skill>/SKILL.md`. There is no third "raw destination"
flag — keep the surface tight.

The repo's own `.claude/skills/` is materialized via
`mdagent install-skills --project .` (or just `make install-skills-repo`
which runs the same).

**R3-3** (preflight fails poorly when mdagent itself is absent). **Accept.**
Skill preflight now starts with a `command -v` guard *before* invoking
the binary:

```bash
command -v mdagent >/dev/null 2>&1 || {
  echo "mdagent not found on PATH."
  echo "Install: uv tool install --force git+https://github.com/FidhaNazreen/MDSimulationAgent@v0.1.0"
  echo "PATH: ensure '$(uv tool dir --bin 2>/dev/null || echo \"<uv tool bin dir>\")' is on PATH."
  exit 1
}

# Verify version + skill compatibility (now that we know mdagent exists).
mdagent doctor --json \
  --min-version 0.1.0 \
  --skill-name md-run-workflow \
  --skill-version 1.0.0 \
  || {
    echo "Doctor failed. See output above for the specific cause."
    exit 1
  }
```

`mdagent doctor` prints its own JSON to stdout on failure (no stale tmp
file involvement).

**R3-4** (`/tmp/mdagent_doctor.json` is sloppy). **Accept — see R3-3 fix.**
Doctor's JSON now flows straight to stdout. No tmp file at all. If the
skill body wants to inspect the JSON further, it pipes it: e.g.
`mdagent doctor --json --skill-name ... | jq -e .ok`.

**R3-5** (`__init__.py` files inside `_resources`). **Accept.**
`src/mdagent/_resources/__init__.py`,
`src/mdagent/_resources/schemas/__init__.py`,
`src/mdagent/_resources/skills/__init__.py` all present as empty
package markers. `importlib.resources.files("mdagent._resources.schemas")`
then resolves cleanly without namespace-package ambiguity.

## Section 2 — Updated artifact (delta)

### Doctor signature

```python
# mdagent/doctor.py
GMX_REQUIRING_STEPS: frozenset[str] = frozenset({
    "step_04_topology", "step_05_solvation", "step_06_em",
    "step_07_nvt", "step_08_npt", "step_09_production",
    "step_10_analysis",
})

@dataclass
class DoctorResult:
    ok: bool
    checks: dict[str, dict]   # name → {status, detail, suggestion?}

def check_for_run(
    cfg: RunConfig,
    *,
    planned_step_ids: set[str],
    skip_gmx_version: bool = False,
    skip_network: bool = False,
    skip_viewer: bool = False,
) -> DoctorResult:
    """Config-aware doctor invocation called by the orchestrator."""
```

The CLI `mdagent doctor --json` wraps the same engine with explicit
flags (`--gmx-required`, `--check-network`, `--check-viewers`).

### CLI surface (final)

```
mdagent --version
mdagent --help
mdagent run-workflow [--config|--pdb-id|--structure-path] ...
        [--stop-after prep|topology|solvation|em|nvt|npt]
        [--skip-network-check] [--skip-viewer-check] [--skip-gmx-version-check]
mdagent prep-structure --pdb-id|--structure-path ... --runs-root <DIR> [--run-id <ID>]
        # internally: run-workflow --stop-after prep
mdagent visualize --run-root <DIR> [--viewer ...] [--checkpoints ...] [--render ...]
mdagent inspect --run-root <DIR>
mdagent doctor [--json] [--min-version X] [--skill-name N --skill-version V]
        [--gmx-required] [--check-network] [--check-viewers]
mdagent install-skills [--user | --project DIR] [--dry-run]
mdagent self-test resources [--json]
```

### `install-skills` semantics (final)

| Invocation | Destination |
|---|---|
| `mdagent install-skills --user` | `~/.claude/skills/<name>/SKILL.md` |
| `mdagent install-skills --project DIR` | `DIR/.claude/skills/<name>/SKILL.md` |
| `mdagent install-skills --project .` | `./.claude/skills/<name>/SKILL.md` |
| `mdagent install-skills --dry-run --user` | prints what would be written; no writes |

### Skill preflight (final)

Verbatim, used by all three skills with their own `--skill-name` / `--skill-version`:

```bash
command -v mdagent >/dev/null 2>&1 || {
  echo "mdagent not found on PATH."
  echo "Install: uv tool install --force git+https://github.com/FidhaNazreen/MDSimulationAgent@v0.1.0"
  echo "PATH: ensure '$(uv tool dir --bin 2>/dev/null || echo \"<uv tool bin dir>\")' is on PATH."
  exit 1
}
mdagent doctor --json \
  --min-version 0.1.0 \
  --skill-name <SKILL_NAME> \
  --skill-version <SKILL_VERSION> || exit 1
```

## Section 3 — Final critique prompt

Apply the original threshold:

  VERDICT: APPROVED
  VERDICT: ISSUES_REMAIN

`APPROVED` if no blocking holes remain. Nitpicks alone don't justify
`ISSUES_REMAIN`.
