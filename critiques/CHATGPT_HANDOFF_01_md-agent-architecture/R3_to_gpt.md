# Round 3 counterreply

Your clarification answers (C1: mode+profile as separate concerns; C2: rename v0 deliverable to "prepared and EM-validated starting system"; C3: keep `md:validate-system`, make validation implicit elsewhere) are accepted as written and now part of the architecture. Below: per-issue acknowledgments, then the most significant new structural addition — the GROMACS interaction transcript model (your point 35), which several other issues (2, 4, 27, 28) collapse into. Plus the smaller refinements.

## Section 1 — Acknowledgments (per R2 issue)

**R2-1** (DAG impossible: classifier before ingest): **Accept.** Inserting `StructureIngest` as the first agent after `Preflight`. It owns fetching, model selection, biological-assembly selection, chain selection — produces the coordinate set that `SystemClassifier` then labels. Revised DAG in Section 2.

**R2-2** (`pdb2gmx --his` is not a real per-residue CLI; GROMACS exposes `-his` as interactive selector): **Accept.** This is the core of point 35. Driving `pdb2gmx` deterministically requires a generated stdin transcript, not made-up flags. See Section 2.3 (Transcript model).

**R2-3** (drop `-ignh` is probably the wrong default): **Accept and reverse.** Default *is* `-ignh` (let `pdb2gmx` regenerate hydrogens from FF templates) precisely because most PDB inputs lack/have-incompatible hydrogens. The protonation guarantee is then enforced via the *transcript* (explicit HIS/termini answers driven by the protonation decisions), not by preserving input hydrogens. Preserving input hydrogens (`-noignh`) only under a strict compatibility policy that asserts atom names match the FF template.

**R2-4** (`HID|HIE|HIP` not portable; FF-specific names HSD/HSE/HSP): **Accept.** Two-layer protonation record:
- `abstract_state: {delta_protonated | epsilon_protonated | doubly_protonated}` (FF-independent).
- `ff_template_name: "HSE" | "HIE" | "HISE" | ...` (resolved from a per-FF mapping table at topology time).
Same applies to CYS/CYX, ASP/ASH, GLU/GLH, LYS/LYN.

**R2-5** (FF/water allowlist contradicts tutorial profile): **Accept — clear error on my part.** OPLS-AA/L + SPC is required for `tutorial_reproduction` (the GROMACS tutorial uses SPC216). Allowlist entry corrected: `OPLS-AA/L ↔ {SPC, SPC/E, TIP3P, TIP4P}` with `SPC` flagged as tutorial-preferred. Allowlist matrix is now in `schemas/v0.1.0/ff_water_compat.json` and validated at planning time.

**R2-6** (`protein_only_soluble | multimer | mixed` not mutually exclusive): **Accept.** Classifier becomes multi-label across orthogonal axes:
- `chemistry: {protein, nucleic_acid, ligand, metal_ion, glycan, cofactor, ...}` (set)
- `assembly: {monomer, homomultimer, heteromultimer}` (single)
- `environment: {soluble, membrane_likely, unknown}` (single, with evidence)
- `unsupported_features: [...]` (set; non-empty → blocked in v0 unless `protein_with_structural_waters` exception)

v0 supports `chemistry={protein}` (optionally plus `{protein, water}` — see R2-26), any assembly, `environment=soluble`, empty `unsupported_features`. Everything else fails fast.

**R2-7** (membrane not detectable from coordinates alone): **Accept.** Membrane heuristic uses: OPM/PPM metadata lookup by PDB ID (if available), hydrophobic-span detection (≥ 20 contiguous nonpolar residues with cylindrical span ≥ 25 Å), and PDB header keywords. If any signal positive → `environment: membrane_likely → blocked` with the evidence. If ambiguous and `interactive`, prompt; otherwise classify `environment: unknown → blocked` rather than silently labeling soluble.

**R2-8** (assembly selection in wrong place): **Already accepted via R2-1** — moved into `StructureIngest`, runs before classification.

**R2-9** (altloc clash rule insufficient; networks are about correlated occupancy groups): **Accept.** Altloc resolution now: (1) parse altloc letters and occupancy values into conformer groups by alt-letter; (2) prefer the conformer set whose mean occupancy is highest *and* whose letter assignment is internally consistent across nearby residues (≤ 6 Å Cα-Cα); (3) clash check (< 2.0 Å heavy-atom) is only the sanity guard, not the decision rule.

**R2-10** (retained-water classifier too confident): **Accept.** Retained waters → `preserve_with_warning` in `general_md_prep`; in `tutorial_reproduction` strip all. Confidence score is recorded but never claims catalytic relevance — only `buried | bridging_contacts | low_B_factor` evidence flags.

**R2-11** (`ρ_protein ≈ 30 atoms/nm³` is bad): **Accept.** Replacing the formula with: post-`gmx solvate`, count `SOL` molecules added directly from the topology diff. The expected band becomes redundant — we no longer estimate, we measure. Sanity check only: `N_water > 0` and `box_volume - solute_volume_from_VDW_grid > 0`. Drop the percentage-tolerance band.

**R2-12** (zero-step `grompp` doesn't prove physical validity): **Accept.** Re-scoped: `grompp` gate proves *topology↔coordinate consistency only* — name renamed `consistency_gate` in the manifest. Physical validity is `ShortEM`'s job. Documenting this in the validator descriptions.

**R2-13** (grompp log scanning insufficient; `-maxwarn` abuse): **Accept.** Validation `grompp` calls forbid `-maxwarn > 0` by default. Warnings are parsed structurally (GROMACS prefixes them: `WARNING N [file ..., line ...]:`); each warning is matched against an allowlist (e.g. "atom velocities not present in starting configuration" is benign at consistency-gate time). Non-allowlisted warning → hard fail.

**R2-14** (EM convergence criterion too rigid): **Accept.** `ShortEM` now records: convergence curve (`fmax` per step), max-force atom indices, step count, whether EM converged within step limit. `EMValidator` outputs one of `converged | needs_longer_em | diverged | stuck`. `readiness_status` maps: `converged → ready`, `needs_longer_em → ready_with_warnings` (with `physics` class), `diverged | stuck → blocked`.

**R2-15** (v0 acceptance "match tutorial outputs exactly" too brittle): **Accept.** Pin the reference: exact GROMACS version (TBD per R2-33), tutorial revision (URL + git commit hash if the user mirrors it locally), seeds for `genion -seed` and any randomness, expected hash/count thresholds for: number of `SOL` molecules (±0, hash on topology counts), ion counts (±0), residue count (±0), final atom count (±0). Hashes pinned on `system.top` molecule table, not on `.gro` byte content (GROMACS version drift writes different headers).

**R2-16** (`genion` solvent group hard-coded `SOL`): **Accept.** Solvent residue name is discovered from `topology_plan.json` (per water model: SPC/SPC/E → `SOL`, TIP3P → `SOL` or `WAT` depending on FF, TIP4P → `SOL` or `HOH`). Index generation uses the discovered name; assertion: solvent group is non-empty + uniform.

**R2-17** (`genion` random seed for reproducibility): **Accept.** `random_seed` is a required field in `strict-config-required` mode and recorded in all modes. The effective seed (whether configured or auto-generated) is in `solvation_report.json`. Source noted: `gmx genion -seed`.

**R2-18** (provenance parsed from stdout unreliable): **Accept.** Provenance collection: (1) parse the final resolved `.top` include graph via the GROMACS preprocessor output `mdout.mdp` and resolved file list (`gmx grompp` archives this), (2) hash each resolved FF file (`*.rtp`, `*.itp`, `*.ff/*`), (3) archive `mdout.mdp`. No more "parse stdout for filenames."

**R2-19** (`Artifact` under-specified for command execution): **Accept.** `Task` gains:
```python
workdir: Artifact                      # the process's cwd
path_map: dict[Artifact, str]          # how to resolve URIs to local paths on the executor host
produces: list[ProducedArtifact]       # declared outputs with (relative path, expected type)
```
`Executor.run_sync` resolves `path_map` to absolute paths in the cwd, runs argv, then collects `produces` into the output `ExecutionResult.artifacts_out`.

**R2-20** (`index.json` race / stale `running` after crash): **Accept.** Run-lock file (`<run_id>/.lock` via `fcntl.flock` on POSIX) acquired by orchestrator at startup. Recovery rule: if `index.json` has a step in `running` and the lock is stale (no live PID), mark that step `failed` with `reason: crash_recovery_stale_running` and resume from there per the dependency-invalidation rules below.

**R2-21** (resume too simplistic; need content-hash dependency invalidation): **Accept.** Each step's `step_report.json` records its `inputs: [{artifact, content_hash}]`. On resume: walk steps in DAG order; for each `succeeded` step, recompute hashes of its declared inputs; if any input hash differs from what was recorded, mark this step and all downstream steps `invalidated`. Orchestrator restarts at the first `planned | invalidated | failed` step.

**R2-22** (`choice_specification.json` lacks machine-actionable normalized fields): **Accept.** Each choice now has both:
- `presentation: {prompt_text, alternatives_text, consequence_text}` — for the human.
- `policy: {enum_values, default, validation_rule, applicability_predicate, required_in_modes: [...]}` — machine-actionable.
The user's answer is stored as both `response_text` (verbatim) and `normalized_value` (parsed against enum).

**R2-23** (`general_md_prep` says FF always user-surfaced, but noninteractive forbids prompting): **Accept — contract conflict.** Rephrasing: in `general_md_prep` mode, FF/water is *required to be specified*. Source priority: (a) explicit run-time config, (b) profile selected via `--profile <name>`, (c) interactive prompt (only in `interactive` interaction mode), (d) fail. In `noninteractive-defaults` and `strict-config-required` modes, (c) is removed.

**R2-24** (preflight capability-scoped, not full pipeline): **Accept.** `Preflight` checks only the tools the requested skill chain needs, computed from the DAG. `md:prep-structure` standalone needs: PDB fetcher, structure parser, PROPKA (optional), VMD/PyMOL if `viz` configured. Not GROMACS. `md:build-topology` adds GROMACS. `md:solvate-system` adds ion tools. Preflight composes additively.

**R2-25** (visualization after EM only loses earlier observability): **Accept.** Visualization is checkpoint-triggered, not terminal. Config `checkpoints` (defaulting to `[]` when `mode=default`, configurable to any subset of `{prep, topology, solvated, em}`) determines when the orchestrator dispatches a visualization sub-task. Each checkpoint render writes to `visualization/<checkpoint>/`.

**R2-26** (retained waters fixture conflicts with "protein only" classifier): **Accept.** v0-supported chemistry is `{protein}` OR `{protein, water}` where water residues are exclusively `HOH`/`WAT`/`SOL` and pass through the structural-water classifier. Ligands/cofactors/glycans remain unsupported.

**R2-27** (disulfide policy missing): **Accept.** New section in `topology_plan.json`: `disulfides: [{cys1: (chain, resid), cys2: (chain, resid), source: detected|configured, accepted: bool}]`. Detection via Sγ-Sγ distance ≤ 2.5 Å. Driven through `pdb2gmx -ss` transcript (interactive y/n per detected pair) or explicit CYS→CYX residue renaming for FFs without `-ss` support.

**R2-28** (terminal-capping policy missing): **Accept.** New section in `topology_plan.json`: `termini: [{chain, n_term: {state: charged|neutral|ACE|...}, c_term: {state: charged|neutral|NME|NH2|...}, source}]`. Driven via `pdb2gmx -ter` interactive transcript. Decisions recorded with final template names.

**R2-29** (missing-residue handling not operational): **Accept.** v0 policy: hard-fail any internal missing residue or missing backbone atom (N/CA/C/O) in a standard residue. Missing terminal residues (N- or C-terminal tails) tolerated only if explicitly configured (`allow_terminal_truncation: true`) and the truncation is recorded in `mutations.json`.

**R2-30** (MSE→MET conversion blunt rejection too strict): **Accept.** Selenomethionine handling: detected as `non_standard_residue: MSE`. Default v0 behavior: convert MSE→MET (selenium→sulfur is a stereochemically valid reversible substitution for force-fields without Se parameters) as an explicit recorded mutation. Configurable via `mse_policy: convert|reject|preserve_if_supported`. Only blocked if FF lacks both MET and a Se-containing alternative.

**R2-31** (`readiness_status` conflates completeness and severity): **Accept.** Warnings now classed: `reproducibility | chemistry | physics | io | visualization`. `readiness_status` decision tree:
- Any `chemistry` or `physics` warning + `strict-config-required` → `blocked`.
- Any `chemistry` or `physics` warning + other modes → `ready_with_warnings` (warnings surfaced in title).
- `reproducibility | io | visualization` warnings alone → `ready_with_warnings`, less prominent in title.
- All validators passed, no warnings → `ready`.

**R2-32** (no test for missing-required-config in `strict-config-required`): **Accept.** Adding acceptance tests:
9. `strict-config-required` mode missing FF → fails at preflight with `config_missing: force_field`.
10. `strict-config-required` mode missing ion seed → fails at preflight with `config_missing: random_seed`.
11. `strict-config-required` mode missing visualization setting (when viz `enabled`) → fails at preflight.
12. `strict-config-required` mode with unresolved HIS (no policy + no per-residue overrides) → fails at topology planning with `unresolved_decisions: [HIS.A.15, ...]`.

**R2-33** (pin GROMACS version range): **Accept.** v0 pins:
- `tutorial_reproduction` mode: **exact** GROMACS version (proposing 2024.3 — current stable as of writing; final pin per user); FF: `oplsaa.ff` shipped with that version; tutorial revision: justinlemkul/gromacs-tutorials commit hash (TBD by user).
- `general_md_prep` mode: tested range `[2023.x, 2024.x]`; Preflight refuses to run on versions outside the tested range unless `--allow-untested-gromacs` is set.

**R2-34** (skill boundary leak): **Accept.** `md:solvate-system` default execution path: `Solvation + grompp_consistency_gate + ShortEM + SolvationValidator + EMValidator`. Explicit `skip_validation: true` produces `readiness_status: not_validated` artifacts. `md:validate-system` remains as the standalone "just run EM on an existing system" power-user skill.

**R2-35** (transcript model is the missing keystone): **Accept — this is the most important new piece.** See Section 2.3 below: the `Pdb2GmxTranscript` subsystem becomes a v0 design artifact.

## Section 2 — Updated artifact (delta from R2)

### 2.1 Revised DAG

```
Preflight → StructureIngest → SystemClassifier → StructurePrep
         → Topology (FF planning → pdb2gmx via transcript) → [consistency_gate (grompp)]
         → Solvation (box + solvate + ions) → [consistency_gate (grompp)]
         → ShortEM → [EMValidator]
         → Report

Visualization runs as checkpoint side-effects after any of {StructurePrep, Topology, Solvation, ShortEM} per config.
QC validators run between phases; Provenance collection wraps every executor call.
```

### 2.2 Agent roster (delta)

- **`StructureIngest`** *(new — split from `StructurePrep`)*: fetches PDB by ID or accepts path; selects model number, biological assembly (per `structure_ingest_policy`), chain set; emits the coordinate set `SystemClassifier` consumes. Records selection rationale.
- **`SystemClassifier`** *(updated)*: multi-label across `chemistry`, `assembly`, `environment`, `unsupported_features`. Membrane-likely heuristic + metadata lookup. Returns supported/unsupported with structured reasons.
- **`StructurePrep`** *(narrowed)*: analyzes only — protonation, water classification, altloc resolution, disulfide detection, MSE detection, missing-residue detection. Emits `observations.json` and `mutations.json`. Mutations include MSE→MET if policy allows.
- **`Topology`** *(extended)*: FF planning → emits `topology_plan.json` with FF, water model, ion include source, protonation decisions (`abstract_state` + `ff_template_name`), disulfide decisions, termini decisions, MSE handling. Drives `pdb2gmx` via the `Pdb2GmxTranscript` subsystem (see below). Records actual transcript stdin + parsed stdout.
- **`Solvation`** *(extended)*: solvent residue name discovered from `topology_plan.json`. Four-stage charge accounting. `-seed` recorded.
- **`ShortEM`** *(extended)*: emits convergence curve + per-step fmax. `EMValidator` outputs four-way verdict (`converged | needs_longer_em | diverged | stuck`).
- **`Visualization`** *(repositioned)*: checkpoint-triggered side-effect after configured steps, not terminal. Best-effort probe + script-always emission.
- **`Report`** *(updated)*: `readiness_status` derived from warning classification tree (R2-31).

### 2.3 Pdb2GmxTranscript subsystem (the new keystone)

`pdb2gmx`'s deterministic-CLI surface is limited: most chemistry decisions are made via interactive prompts. The transcript subsystem is what makes the whole architecture implementable.

**Components:**

1. **Prompt catalog** (`schemas/v0.1.0/pdb2gmx_prompts.json`): per supported GROMACS version, the expected prompt strings the binary emits and their decision space:
   - `force_field_prompt: "Select the Force Field:" → enum of available FFs from the version's `top/` directory`
   - `water_prompt: "Select the Water Model:" → enum from FF's `watermodels.dat``
   - `his_prompt: "Which HISTIDINE for residue HIS N (chain X)?" → {0: HID, 1: HIE, 2: HIP}` *(or HISD/HISE/HISH per FF)*
   - `ter_prompt_n: "Select N-terminus type for chain X:" → enum of FF-specific termini`
   - `ter_prompt_c: "Select C-terminus type for chain X:" → enum`
   - `ss_prompt: "Disulfide bond? CYS X-Y? (y/n):" → bool`
   
   Catalog versioned per GROMACS version; tested on each release.

2. **Transcript generator**: consumes `topology_plan.json` (with abstract protonation, termini, disulfide decisions) plus the prompt catalog for the current GROMACS version, plus the FF-specific residue/template mapping. Emits:
   - `stdin_lines: list[str]` — the answer sequence to pipe into `pdb2gmx`.
   - `expected_prompts: list[str]` — the prompts we expect to see in order, for verification.
   - `decision_trace: list[{prompt, answer, source_decision}]` — for audit.

3. **Transcript parser**: after `pdb2gmx` runs, parses stdout against `expected_prompts` to verify the binary asked the questions we expected, in the order we expected. Mismatch (extra prompt, missing prompt, prompt with different options) = hard fail with `unexpected_pdb2gmx_interaction: {expected, actual}`. This catches both (a) version drift and (b) structures that triggered prompts we didn't plan for (e.g. a residue we missed in detection).

4. **Pre-rename fallback**: for cases where transcript-driving is fragile (e.g., a CYS rename to CYX for FFs that don't support `-ss`), the subsystem alternatively rewrites residue names in the input PDB before calling `pdb2gmx`. Pre-renames are recorded in `mutations.json`.

**v0 deliverables for the transcript subsystem:**
- The catalog populated for the pinned GROMACS version.
- The generator/parser implementation with unit tests covering: every HIS branch, every termini branch, disulfide y/n, MSE pre-rename, and a "wrong-options" negative test.
- Integration test: drive `pdb2gmx` end-to-end on 1AKI and assert the decision trace matches the canonical tutorial's choices.

This subsystem is **what makes** the protonation/termini/disulfide architecture implementable, rather than aspirational.

### 2.4 Updated v0 acceptance criteria

Adds tests 9–12 from R2-32 plus an explicit transcript test:
1–8 unchanged (1AKI tutorial reproduction, non-interactive run, interactive run, ligand fixture rejection, crash recovery, schema validation, consistency_gate, EM convergence).
9. `strict-config-required` missing FF → preflight fails.
10. `strict-config-required` missing `random_seed` → preflight fails.
11. `strict-config-required` missing visualization config (when enabled) → preflight fails.
12. `strict-config-required` with unresolved HIS → topology-planning fails.
13. Transcript subsystem unit tests pass (per branch listed in 2.3).
14. Hash of `system.top` `[ molecules ]` block on 1AKI matches the pinned tutorial reference.

### 2.5 Updated state model (deltas)

- `<run_id>/.lock` (run lock).
- `step_NN_*/step_report.json` now declares `inputs: [{artifact, content_hash}]` for dependency invalidation.
- `step_03_topology/pdb2gmx_transcript.json` (decision trace).
- `step_03_topology/mdout.mdp` (from `grompp` consistency gate).
- `visualization/<checkpoint>/` per checkpoint, not flat.

## Section 3 — Continued critique prompt

Review the updated plan and my responses to your earlier issues. Push back on responses where I defended poorly — name which point. Raise any new issues the updated plan creates. Re-issue any earlier issue you don't think I addressed. Same numbered format and same verdict line at the end:

  VERDICT: APPROVED
  VERDICT: ISSUES_REMAIN

Two specific things I want you to pressure-test in this round:

**P1.** The `Pdb2GmxTranscript` subsystem (Section 2.3) is the load-bearing new piece. Is the design implementable as written, or am I underestimating the surface area of `pdb2gmx`'s interactive prompt space? In particular: are there prompts I've omitted (chain selection, alternate locations, missing-atom decisions) that should be in the catalog?

**P2.** Dependency invalidation by input content hash (R2-21 acceptance): is this enough, or do we also need to track *parameter* changes (e.g. user re-runs with the same input PDB but a different `--profile`) for full correctness? If yes, where does the parameter-hash live, and which steps are sensitive to which parameters?
