# Round 4 counterreply

Both answers to P1/P2 land — `DialogueRunner` and `StepFingerprint` are now first-class v0 design artifacts (Section 2). Most of the 35 issues are accepted, with three defended on scope grounds. A reminder of the blocking threshold at the end of this round, because we're at round 4 of 5 and many of the remaining issues are genuine refinements but not run-blocking.

## Section 1 — Acknowledgments (per R3 issue)

**R3-1** (`-inter` covers ASP/GLU/LYS/ARG/CYS, not only HIS): **Accept.** Prompt catalog expands to cover all interactive residue families exposed by `-inter` for each supported FF. Default v0 invocation: `pdb2gmx -ff X -water Y -ter -inter -ignh` so all titratable residues are answered explicitly from the protonation plan. Per-FF availability of `-inter` choices is encoded in `schemas/v0.1.0/pdb2gmx_prompts.json`.

**R3-2** (static stdin is fragile; need PTY/dialogue runner): **Accept — this becomes `DialogueRunner`.** Section 2.1 below.

**R3-3** (exact-string matching too brittle; need semantic): **Accept.** `DialogueRunner` uses `LC_ALL=C` + pinned GROMACS version + *semantic prompt classes* (regex/keyword recognition into `PromptKind = {select_ff, select_water, his_choice, ter_choice_n, ter_choice_c, ss_yn, inter_residue_choice, chain_merge, ...}`). Raw prompt text is logged for audit but not used as matching key.

**R3-4** (don't rely on prompts for FF/water; use `-ff` / `-water`): **Accept.** `pdb2gmx -ff <name> -water <name>` is always passed explicitly. `select_ff`/`select_water` prompts in the catalog exist only to detect unexpected fallback (binary asked something we said we'd answered via flag — hard fail with `unexpected_fallback_prompt`).

**R3-5** (chain handling missing — `-chainsep`, `-merge`): **Accept.** New section `chain_policy` in `topology_plan.json`:
```
chain_policy:
  chainsep: "id_or_ter" | "id" | "ter" | "interactive"
  merge: list of merge groups (chain letters merged into one moleculetype)
  cross_chain_disulfides: list of (cys_a, cys_b) — automatically forces merge of those chains
  termini_per_chain: dict<chain, {n_term, c_term}>
```
`chainsep`/`merge` flags driven from this plan; no interactive prompts allowed in non-`interactive` mode.

**R3-6** (no successful multichain acceptance test): **Accept.** Adding fixture: soluble homodimer (proposing PDB 1HHO — hemoglobin tetramer is too big for v0; will pick a small soluble homodimer such as 1L2Y… actually 1L2Y is monomer; using **PDB 2OOB** or similar small soluble homodimer to be selected at implementation). Test asserts: 2 chains merge or stay separate per policy, exactly N copies in `[ molecules ]`, no cross-chain disulfide drift, EM converges.

**R3-7** (missing-atom decisions should not be in transcript): **Accept.** Hard-fail before `pdb2gmx` ever runs (already R2-29 policy); the transcript catalog has no entry for missing-atom prompts. If `pdb2gmx` somehow emits one we treat it as `unexpected_pdb2gmx_interaction` → hard fail.

**R3-8** (altloc resolution before `pdb2gmx`, not via transcript): **Accept.** Altloc resolution runs in `StructurePrep` and emits a single-conformer coordinate set. `pdb2gmx` never sees alt-letters. Transcript catalog has no altloc entries.

**R3-9** (pre-rename fallback is dangerous): **Accept.** Pre-renames restricted to a validated, FF-specific `residue_rename_table` (`schemas/v0.1.0/residue_renames/<ff>.json`) maintained per supported FF. After `pdb2gmx` runs, the topology parser verifies the resulting `[ moleculetype ]` and per-residue template names match what the decision intended. Mismatch → hard fail with `template_mismatch_after_prerename`.

**R3-10** (`StructurePrep` says "analyzes only" but emits mutations): **Accept — language was inconsistent.** Splitting in concept (not necessarily as separate skills/agents): `StructureAnalyze` produces `observations.json` (read-only inspection); `StructureTransform` produces `mutations.json` and the working coordinate set with mutations applied. Both run inside the `md:prep-structure` skill but emit distinct artifacts so audit is clear.

**R3-11** (MSE→MET not reversible): **Accept.** Marked `reversible: false`. Original coordinates archived (`step_02_structure_prep/original.pdb` immutable). Mutation recorded with explicit irreversibility.

**R3-12** (MSE→MET default too aggressive for general mode): **Accept.** Mode-conditional defaults:
- `tutorial_reproduction`: convert MSE→MET silently (matches typical tutorial behavior).
- `interactive` general mode: prompt with `mse_policy` choice spec.
- `noninteractive-defaults` general mode: convert only if `mse_policy: convert` is set in config; otherwise classify as unsupported.
- `strict-config-required`: `mse_policy` must be explicitly set; no implicit conversion.

**R3-13** (structural waters vs `genion` solvent group conflict): **Accept.** Retained crystallographic waters are renamed to `XWA` (or a configurable residue name distinct from the bulk-solvent name) before `gmx solvate` runs. `genion`'s solvent replacement group is constructed from only `SOL`/bulk-water residues. Topology `[ molecules ]` lists `XWA` and `SOL` as separate entries.

**R3-14** (water residue normalization underspecified): **Accept.** `StructurePrep` normalizes water residue names: crystal waters → `XWA` (when retained) or stripped; `gmx solvate`-added waters → FF-expected name (`SOL`/`WAT`/`HOH` per model). Mapping is recorded in `topology_plan.json:water_naming`.

**R3-15** (`mdout.mdp` is not topology include graph): **Accept.** Provenance parses the resolved `.top` include graph directly: walk `#include "file.itp"` statements, resolve each against `cwd` then `GMXLIB`, recursively. Hash every resolved file. Archive `mdout.mdp` separately for run-parameter provenance (different artifact, different purpose).

**R3-16** (parameter-hash invalidation missing → `StepFingerprint`): **Accept — this becomes `StepFingerprint`.** Section 2.2 below.

**R3-17** (step-specific sensitivity declarations): **Accept.** Each step schema declares `depends_on_parameters: list[str]` from a controlled enum (`ff`, `water`, `box_geometry`, `padding`, `ion_strategy`, `random_seed`, `protonation_policy`, `mse_policy`, `altloc_policy`, `chain_policy`, `visualization_mode`, `tool_version`, ...). Resume / invalidation walks only declared dependencies; e.g. changing `visualization_mode` invalidates nothing upstream.

**R3-18** (tool/version hash must participate in invalidation): **Accept.** `StepFingerprint.tool_hash` includes: GROMACS executable absolute path, `gmx -version` stdout, FF directory recursive hash, transcript catalog version (per pinned GROMACS version), `DialogueRunner` code-fingerprint hash.

**R3-19** ("current stable as of writing" claim is wrong as of 2026-05-21): **Accept.** Removed the "current stable" framing. Plan text: "v0 pins GROMACS 2024.3 for tutorial reproducibility (chosen for documented tutorial parity, not recency)."

**R3-20** (`needs_longer_em → ready_with_warnings` too lenient): **Accept.** Remapping: `needs_longer_em → not_validated` (not `ready_with_warnings`). Only `converged → ready`; `needs_longer_em → not_validated`; `diverged | stuck → blocked`. The user can re-run with a higher step cap to escape `not_validated`.

**R3-21** (warning class alone insufficient; need severity): **Accept.** Each warning carries `(class, severity ∈ {info, warning, blocking})`. Readiness mapping: any `blocking` severity → `blocked`; any `chemistry`/`physics` warning of severity `warning` → `ready_with_warnings`; `info`-only → `ready`. Validators stamp severity at emission time using validator-specific rules (no free-form judgment in the orchestrator).

**R3-22** (strict mode shouldn't require viz config when viz disabled): **Accept.** Strict-mode required-config tree is conditional: `visualization.mode` is required; sub-fields (`viewer`, `checkpoints`, `render`) required only when `visualization.mode != disabled`. Updated `strict-config-required` test #11 to reflect this.

**R3-23** (`Preflight` may need FF metadata when `target_profile` supplied): **Accept.** When `md:prep-structure` runs with `target_profile`, preflight verifies: FF directory exists and is readable, FF residue template database parseable (for downstream altloc/water/protonation compatibility checks). GROMACS executable itself is still not required by prep alone unless the profile demands prep-time `pdb2gmx -h` interrogation.

**R3-24** (membrane heuristic false positive/negative): **Accept.** Heuristic → `environment: unknown_or_membrane_likely` unless metadata confirms. In `interactive`: prompt with the evidence shown. In `noninteractive-defaults` and `strict-config-required`: classify as blocked (`requires_explicit_environment_classification`).

**R3-25** (mmCIF should be canonical ingest): **Accept.** `StructureIngest` ingests mmCIF as canonical from RCSB. Internally agents operate on a structured representation (BioPython `Bio.PDB.MMCIFParser` or equivalent) with full label/auth/seq/insertion-code fidelity. PDB-format files are derived only when handing to `pdb2gmx` (which doesn't accept mmCIF reliably across versions), with the derivation step recorded as `format_conversion` in `mutations.json`.

**R3-26** (residue identity needs insertion codes + auth IDs): **Accept.** Canonical residue identifier inside the architecture: `{model, auth_asym_id, label_asym_id, auth_seq_id, label_seq_id, insertion_code, residue_name}`. The shorthand `(chain, resid)` is allowed for human-facing report strings only; internal records use the canonical tuple.

**R3-27** (transcript catalog should be discovered, not hand-entered): **Accept.** Catalog generation pipeline: a `catalog_probe` script runs `pdb2gmx` against curated test structures (one HIS, one CYS pair, multi-chain, etc.) under each pinned GROMACS version, captures the prompt sequences via `DialogueRunner` in *discovery mode* (semantic recognition still applies, but unknown prompts are recorded for catalog extension), and writes the snapshot to `schemas/v0.1.0/pdb2gmx_prompts/<gromacs_version>.json`. Hand-curation only for new prompt-class names.

**R3-28** (transcript parser must capture stderr): **Accept.** `DialogueRunner` runs `pdb2gmx` under a PTY with stdout+stderr merged into one byte stream (preserves prompt ordering) **and** with separate raw streams archived. Prompt recognition operates on the merged stream; the raw streams are kept for forensic audit.

**R3-29** (no normalized `pdb2gmx` failure taxonomy): **Accept.** Error taxonomy:
```
PromptMismatchError
UnsupportedResidueError
MissingAtomError
ChainInconsistencyError
TemplateMismatchError
FFWaterUnavailableError
DisulfideMismatchError
UnexpectedPromptError
DialogueTimeoutError
NonZeroExitError       # catch-all with raw exit code
```
Each maps to a specific QC verdict and a specific `readiness_status` outcome. `pdb2gmx` stdout/stderr is parsed into these via the same semantic engine as the prompt catalog.

**R3-30** (acceptance test 14 only hashes `[ molecules ]`): **Accept.** Test 14 extended: hash `[ molecules ]` counts, FF include hashes, water include name+hash, ion include name+hash, and per-chain `moleculetype` names. All must match pinned reference for tutorial reproduction.

**R3-31** (visualization races on mutable upstream artifacts): **Accept.** Visualization consumes only artifacts referenced by content hash from the upstream `step_report.json`. If a downstream step rewrites the same logical artifact, the older hash is still resolvable via the immutable per-attempt files. Visualization receives `(artifact_uri, expected_hash)` and verifies before rendering.

**R3-32** (`system.top` filename collision across steps): **Accept.** Explicit naming:
- `step_03_topology/system_apo.top` (pre-solvent topology)
- `step_04_solvation/system_solvated.top` (post-solvate, pre-ion)
- `step_04_solvation/system_ions.top` (post-ion, final)
The final artifact under `<run_id>/output/system_final.top` is a symlink to whichever is the latest validated.

**R3-33** (profile versioning unspecified): **Accept.** Profile spec: `profile_id`, `semver`, `content_hash`, `changelog`, `applies_to_modes`, `parameter_overrides`. Profiles live in `profiles/<profile_id>-v<semver>.yaml` with content hash recorded. `StepFingerprint.profile_hash` references the profile's content hash, not just its name.

**R3-34** (transcript subsystem needs fixture matrix): **Accept.** Transcript fixture matrix (per pinned GROMACS version):
- F1: protein with **no** titratable interactive residues (no HIS, no CYS pairs) — bare termini only.
- F2: protein with one HIS in each tautomer state (3 structures: HID-only, HIE-only, HIP-only).
- F3: protein with multiple HIS, mixed states.
- F4: protein with one disulfide (y).
- F5: protein with one disulfide (n).
- F6: multichain (homodimer) with `merge=no`, `merge=yes`, and cross-chain disulfide.
- F7: protein triggering `-inter` ASP/GLU/LYS choices.
- F8: deliberate unexpected-prompt fixture (modified FF database) to verify `UnexpectedPromptError` fires.
Each fixture has a recorded expected `decision_trace` and exit `readiness_status`.

**R3-35** (load-bearing pieces need implementation-level spec): **Accept — see Sections 2.1 and 2.2.**

## Section 2 — Updated artifact (delta)

### 2.1 `DialogueRunner` — first-class v0 artifact

**Responsibility:** Drive interactive CLI processes (initially `pdb2gmx`) deterministically.

**Surface:**
```python
class PromptKind(Enum):
    SELECT_FF, SELECT_WATER, HIS_CHOICE, INTER_RESIDUE_CHOICE,
    TER_N_CHOICE, TER_C_CHOICE, SS_YN, CHAIN_MERGE, ...

@dataclass
class Prompt:
    kind: PromptKind
    raw_text: str                       # logged, not matched
    options: dict[str, str]             # numeric index → label
    context: dict                       # residue id, chain, etc. parsed from prompt

@dataclass
class Exchange:
    prompt: Prompt
    answer: str                         # the literal string sent
    answer_source: Literal["plan", "policy_default", "interactive_user", "discovery"]
    plan_field: str | None              # which topology_plan.json field drove the answer

class DialogueRunner:
    def __init__(self, executable: str, recognizer: PromptRecognizer, env_overrides: dict):
        ...  # env_overrides forces LC_ALL=C, etc.

    def run(self, argv: list[str], plan: TopologyPlan, mode: InteractionMode) -> DialogueResult:
        """
        Spawn process under PTY.
        Loop:
          read until prompt recognized (or process exits, or timeout)
          if unknown prompt and mode != discovery: raise UnexpectedPromptError
          answer = plan.resolve(prompt) or policy_default(prompt) or (prompt user if interactive)
          write answer
          log exchange
        Returns DialogueResult with full exchange log + raw stdout/stderr.
        """
```

**Failure modes (all in taxonomy R3-29):** `UnexpectedPromptError` (unknown semantic class), `PromptMismatchError` (recognized but unexpected at this point in the plan), `DialogueTimeoutError` (no prompt within timeout), `NonZeroExitError`.

**Modes:** `normal` (everything must be recognized + resolvable) and `discovery` (unknown prompts logged and returned but don't fail — used only by the catalog probe).

**v0 deliverables:** `DialogueRunner` implementation + `PromptRecognizer` for `pdb2gmx` per pinned GROMACS version + unit tests covering every fixture F1–F8 + a contract test that asserts the `pdb2gmx` binary actually emits prompts the recognizer can classify (against the catalog probe).

### 2.2 `StepFingerprint` — first-class v0 artifact

**Per-step record (`step_NN_<agent>/step_fingerprint.json`):**
```json
{
  "step_id": "step_04_solvation",
  "schema_version": "0.1.0",
  "inputs_hash":     "<sha256 of declared input artifacts, sorted by URI>",
  "parameters_hash": "<sha256 of the JSON-serialized depends_on_parameters subset>",
  "profile_hash":    "<sha256 of profile content if a profile was selected>",
  "mode_hash":       "<sha256 of (interaction_mode, pipeline_mode)>",
  "tool_hash":       "<sha256 of (gmx_version_stdout, ff_dir_hash, transcript_catalog_version, dialogue_runner_code_hash)>",
  "schema_hash":     "<sha256 of the JSON schemas the step writes against>",
  "code_hash":       "<sha256 of the agent's code module(s) — git commit if available>",
  "composite":       "<sha256 of all the above concatenated>",
  "depends_on_parameters": ["ff", "water", "ion_strategy", "random_seed"]
}
```

**Invalidation algorithm:**
```
on_resume(run_id):
  for step in dag_order:
    if step.status != succeeded: continue
    recomputed = compute_fingerprint(step)
    if recomputed.composite != recorded.composite:
      step.status = invalidated
      for downstream in dag_descendants(step):
        downstream.status = invalidated
      break
  restart_from(first_non_succeeded_step)
```

**Sensitivity declarations** live in each step's schema, e.g.:
```yaml
# schemas/v0.1.0/steps/solvation.schema.json
depends_on_parameters: [ff, water, box_geometry, padding, ion_strategy, random_seed]
```
Visualization config is not in any upstream step's `depends_on_parameters`, so toggling viz never invalidates topology.

**v0 deliverables:** `StepFingerprint` writer + reader + invalidation walker + tests (config change scenarios: same input, different FF, different seed, different profile version, different GROMACS, different agent code).

### 2.3 Other deltas from R3

- DAG unchanged structurally; chain handling added inside `Topology`.
- `StructurePrep` decomposed into `StructureAnalyze` + `StructureTransform` substages (one agent, two output bundles).
- `topology_plan.json` schema extended with `chain_policy`, `water_naming`, `disulfides`, `termini`, `protonation_decisions` (with abstract+template layers).
- Acceptance tests now 14 + transcript fixture matrix F1–F8 = effectively 22 tests.
- `system.top` filename collision resolved (R3-32).

### 2.4 Three points I am *defending*, not accepting

**Defend D1** — re. R3-25 (mmCIF canonical ingest). I accept the principle, but flagging that v0's `pdb2gmx` invocation receives a derived PDB file, not mmCIF, because `pdb2gmx` mmCIF support is unreliable across the supported version range. The mmCIF→PDB derivation step is the necessary lossy bridge; the architecture explicitly records the derivation as a `mutations.json` entry of class `format_conversion` with what was lost (typically insertion codes that don't round-trip cleanly). Push back if you think this bridge step itself needs more guarding.

**Defend D2** — re. R3-12 (MSE policy across modes). I accept the mode-conditional defaults *except* the `tutorial_reproduction` silent convert. The tutorial uses 1AKI which has no MSE residues, so the question doesn't arise. Setting "silent convert" as the tutorial-mode default is therefore harmless for 1AKI but bakes a contestable policy. Counter-proposal: in `tutorial_reproduction` mode, if a structure has MSE that requires conversion, raise a hard fail with `tutorial_mode_does_not_handle_mse` — force the user to switch to general mode. Push back if you think that's too purist.

**Defend D3** — re. R3-6 (homodimer fixture choice). I haven't pinned a specific PDB for the homodimer fixture (sketched 2OOB tentatively). Defending only that the fixture choice should be deferred to implementation time when we can pick something small + soluble + with a tractable EM convergence on a laptop. Counter-proposal acceptable: pin **PDB 1BTA** (Barnase, small soluble dimer in some crystal forms) or any similar candidate you'd prefer.

## Section 3 — Continued critique prompt

We are at round 4 of 5. Apply the original threshold strictly: **issues you would block on → `ISSUES_REMAIN`; nitpicks alone → call them out but verdict `APPROVED`.**

Specifically: if your remaining concerns are about implementation polish, naming conventions, additional fixtures beyond the 22 already specified, or further decomposition of existing well-specified subsystems, please verdict `APPROVED` and list them as nitpicks. If you find a *blocking* issue — something where the system as designed will produce wrong results, fail unrecoverably, or contradict its own contracts — then `ISSUES_REMAIN` and name it explicitly as blocking.

Same numbered format and same verdict line at the end:

  VERDICT: APPROVED
  VERDICT: ISSUES_REMAIN

Three things I'd particularly value you assessing:

**P3.** Are the three defenses in Section 2.4 (D1 PDB-bridge, D2 tutorial-mode MSE policy, D3 deferred fixture choice) defensible, or is one of them actually a blocking hole?

**P4.** Is `DialogueRunner` (Section 2.1) specified at a level where a competent engineer could implement it in a week, or is there still architectural ambiguity? Be specific about what would still be ambiguous.

**P5.** Is `StepFingerprint` (Section 2.2) sufficient for correct resume semantics across the full set of "what changed?" scenarios (input change, parameter change, profile bump, GROMACS upgrade, agent-code change, schema bump)? If you can name a scenario it would miss, that's a blocking issue.
