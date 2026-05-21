# Final revision — MD agentic system architecture (v0)

**Critique loop:** 5 rounds, gpt-5.5 via Codex, reasoning effort `high`.
**Final verdict:** `VERDICT: APPROVED` (R5).
**Original artifact:** `R1_to_gpt.md` Section 2 (the architecture proposal). This document is the consolidated, critique-hardened replacement.

## Summary

- **5 rounds, ~143 issues raised, 140 addressed, 3 defended (all defenses accepted by reviewer), 0 unresolved.**
- The architecture changed materially. The original v0 (Orchestrator + 7 agents, single mutable manifest, free-form `gmx` invocations, "ready to minimize" claimed without proof, OPLS-AA/L + SPC as a "general default") was hardened into a 9-agent pipeline gated by a `SystemClassifier`, with a load-bearing `DialogueRunner` for deterministic `pdb2gmx` control, a `StepFingerprint` for correct resume semantics, a canonical `run_config.schema.json` for parameter sensitivity, immutable per-step records with content hashes, a four-stage charge accounting, a positional bulk-solvent index that protects retained crystallographic waters, a multi-label classifier with explicit unsupported-feature reasons, a four-way EM verdict, and pinned tutorial-reproducibility references.
- The reviewer's day-1 build priorities (verbatim from R5): **(1) schemas first**, **(2) `DialogueRunner` vertical slice**, **(3) 1AKI golden path**.

---

## Consolidated v0 architecture (critique-hardened)

### Pipeline DAG

```
Preflight (early) → StructureIngest → Preflight (post-ingest) → SystemClassifier
  → StructurePrep (StructureAnalyze → StructureTransform)
  → Topology (FF planning → pdb2gmx via DialogueRunner) → [consistency_gate (grompp)]
  → Solvation (box + solvate + ions, four-stage charge accounting) → [consistency_gate (grompp)]
  → ShortEM → [EMValidator]
  → Report

Visualization runs as checkpoint side-effect after any of {StructurePrep, Topology, Solvation, ShortEM} per config.
QC validators run between phases; Provenance collection wraps every executor call.
```

### Agent roster

| Agent | Responsibility |
|---|---|
| `Preflight` | Capability-scoped tool/version availability (per skill chain). Two-stage: early (tools/dirs/viewer probe) + post-ingest (disk + resource estimate from structure size). |
| `StructureIngest` | Fetches mmCIF (canonical) from RCSB; selects model, biological assembly, chains. Emits `coordinate_id_map.json` (canonical mmCIF ↔ derived PDB residue/atom map with full coordinate injectivity verified). |
| `SystemClassifier` | Multi-label classification over `chemistry`, `assembly`, `environment`, `unsupported_features`. v0 supports `{protein}` or `{protein, water}`; everything else fails fast with structured reasons. Membrane heuristic + metadata lookup. |
| `StructurePrep` (`Analyze` + `Transform`) | Analyze: protonation analysis, water classification, altloc resolution, disulfide detection, MSE detection, missing-residue detection. Transform: applies recorded mutations, emits single-conformer derived PDB with `mutations.json` (reversible flag per mutation). |
| `Topology` | FF planning → `topology_plan.json` with FF, water model, ion include source, protonation decisions (`abstract_state` + `ff_template_name`), disulfide decisions, termini decisions, chain policy. Drives `pdb2gmx -ff X -water Y -ter -inter -ignh` via `DialogueRunner`. Records actual decision trace. Verifies topology against `coordinate_id_map.json`. |
| `Solvation` | `editconf` (dodecahedron under globular profile, cubic fallback), `solvate`, positional `bulk_solvent` index for `genion` (protects retained crystallographic waters), four-stage charge accounting, `-seed` recorded. |
| `ShortEM` | Validation gate: `grompp` + ≤1000-step steepest-descent EM. Four-way verdict (`converged | needs_longer_em | diverged | stuck`). Convergence curve recorded. |
| `Visualization` | Checkpoint-triggered side-effect (not terminal). Best-effort probe + script-always emission. Consumes artifacts by content hash. |
| `Report` | Regenerated from on-disk truth at write time. Surfaces `readiness_status` + `readiness_reason`. Hash-verified against manifest before claiming any field. |

QC is the verdict layer composed of: `StructureValidator`, `TopologyValidator`, `SolvationValidator`, `EMValidator`, `ProvenanceValidator`. Provenance collection is a mandatory orchestrator responsibility, not a separate agent.

### Skill boundary map

| Skill | Wraps | Notes |
|---|---|---|
| `md:prep-structure` | `Preflight (early) + StructureIngest + SystemClassifier + StructurePrep + StructureValidator` | Optional `target_profile`; warns about topology-unvalidated state if used standalone. |
| `md:build-topology` | `Topology + TopologyValidator + consistency_gate` | FF selection is internal planning emitting `topology_plan.json` before `pdb2gmx` runs. |
| `md:solvate-system` | `Solvation + consistency_gate + ShortEM + SolvationValidator + EMValidator` | Validation is default-on; `skip_validation: true` produces `readiness_status: not_validated`. |
| `md:validate-system` | `ShortEM + EMValidator` | Standalone power-user skill for re-running EM on an existing system. |
| `md:visualize` | `Visualization` | Mode-gated (`disabled | default | requested`); respects interaction-mode contract. |
| `md:run-workflow` | `Orchestrator` (composes all above) | Single user-facing end-to-end entry point. |

### Modes

- **Pipeline mode** (changes contract): `tutorial_reproduction` (judged by tutorial parity — pinned GROMACS version, command transcript, input PDB sha256, expected `[ molecules ]` table) or `general_md_prep` (judged by chemical/topological correctness against the validator suite).
- **Interaction mode** (changes prompting): `interactive` | `noninteractive-defaults` | `strict-config-required`. Prompting is forbidden outside `interactive`; `strict-config-required` requires every applicable config field be specified.

### State & handoff model

```
<runs_root>/<run_id>/
├── .lock                              # fcntl-flocked, holds orchestrator PID
├── run_config.json                    # validated against schemas/v0.1.0/run_config.schema.json
├── index.json                         # step ordering + state machine + artifact roles + content hashes (atomic temp+rename only)
├── provenance.json                    # GROMACS version, FF hashes, host, container digest, executor identity, resolved env
├── schemas/v0.1.0/                    # canonical config schema + per-step schemas + pdb2gmx_prompts/<gmx_version>.json
├── step_00_preflight_early/
├── step_01_structure_ingest/
│   ├── original.cif
│   ├── derived.pdb
│   ├── coordinate_id_map.json
│   └── step_report.json + step_fingerprint.json
├── step_02_classifier/
├── step_03_structure_prep/
│   ├── observations.json
│   ├── mutations.json
│   ├── protonation_analysis.json
│   ├── water_classification.json
│   ├── retained_waters.json           # atom serial + coords, for positional re-identification
│   ├── working.pdb                    # single-conformer, mutations applied
│   └── step_report.json + step_fingerprint.json
├── step_04_topology/
│   ├── topology_plan.json             # FF, water, ions, abstract+template protonation, disulfides, termini, chains
│   ├── protonation_decisions.json
│   ├── pdb2gmx_transcript.json        # decision trace from DialogueRunner
│   ├── system_apo.gro
│   ├── system_apo.top
│   ├── posre.itp
│   ├── grompp_validation.log
│   └── step_report.json + step_fingerprint.json
├── step_05_solvation/
│   ├── system_solvated.gro
│   ├── bulk_solvent.ndx               # positional index, not residue-name based
│   ├── system_ions.gro
│   ├── system_ions.top
│   ├── charge_accounting.json         # 4-stage record
│   ├── grompp_validation.log
│   └── step_report.json + step_fingerprint.json
├── step_06_em/
│   ├── em.mdp                         # template-hashed
│   ├── em.gro
│   ├── em.log
│   ├── em_convergence.json            # fmax curve, max-force atoms
│   └── step_report.json + step_fingerprint.json
├── qc/
│   ├── structure_validator.json
│   ├── topology_validator.json
│   ├── solvation_validator.json
│   ├── em_validator.json
│   └── provenance_validator.json
├── visualization/                     # only if user opted in; one subdir per checkpoint
│   ├── prep/{prep.png, visualize.vmd, render_probe.json}
│   ├── topology/
│   ├── solvated/
│   └── em/
└── REPORT.md                          # with readiness_status + readiness_reason in title and final line
```

Every JSON artifact carries `schema_version: "0.1.0"`. Every step has both a `step_report.json` (data) and a `step_fingerprint.json` (composite hash of inputs + parameters + profile + mode + tools + schema + code).

### Critical subsystems

**`DialogueRunner`** — PTY-driven interactive process driver. `pexpect`-style loop: wait for recognized prompt → resolve answer from `topology_plan.json` (or policy default, or user in interactive mode) → write answer → log exchange. Unknown prompts in `normal` mode raise `UnexpectedPromptError` with full debug payload. `LC_ALL=C` enforced via `Task.env`. Merged PTY transcript authoritative; separate stdout/stderr archived best-effort.

**`StepFingerprint`** — Per-step composite hash of `(inputs_hash, parameters_hash, profile_hash, mode_hash, tool_hash, schema_hash, code_hash)`. `tool_hash` is **step-specific** (each step declares which tools it depends on). `parameters_hash` derived programmatically from each step's `depends_on_config_fields` selectors against the canonical `run_config.schema.json`. Invalidation on resume walks per-step in DAG order; any composite-hash change → step + downstream steps `invalidated`.

**`Pdb2GmxTranscript` catalog** — Per pinned GROMACS version, snapshot of recognized prompt classes (`SELECT_FF`, `SELECT_WATER`, `HIS_CHOICE`, `INTER_RESIDUE_CHOICE`, `TER_N_CHOICE`, `TER_C_CHOICE`, `SS_YN`, ...) and their option tables. Generated via discovery-mode runs of `DialogueRunner` against curated tiny synthetic fixtures, then hand-curated for prompt-class names. `pdb2gmx` always invoked with `-ff` and `-water` explicitly (those prompts in the catalog exist only to detect unexpected fallback).

**`Executor` abstraction** — `submit/wait/collect/run_sync` + `stage_in/stage_out`. Structured `Task` (argv, env, stdin, resources, container, workdir, path_map, produces) and `ExecutionResult` (exit, stdout/stderr paths, host, wall time, resources used, scheduler metadata, env_resolved, artifacts_out). `LocalExecutor` ships in v0; `RemoteExecutor` is the next adapter slot.

### Acceptance criteria (v0)

1. `tutorial_reproduction` mode on PDB 1AKI matches the canonical tutorial: FF, water, ion counts, residue counts, `[ molecules ]` table hash, FF include hash, water include hash, ion include hash all equal the pinned reference.
2. `noninteractive-defaults` run on 1AKI with config supplied completes without any prompt.
3. Interactive run on 1AKI prompts at all documented decision points; defaults Enter-acceptable.
4. Protein+ligand fixture fails at `SystemClassifier` with `chemistry={protein, ligand}` and `unsupported_features=[ligand_parametrization_required]`.
5. Resume after simulated crash mid-`Solvation` picks up correctly via lock recovery + fingerprint dependency walk.
6. Schema validation passes for every written JSON artifact.
7. `consistency_gate` (zero-step `grompp`) passes at end of `Topology` and end of `Solvation`.
8. Short EM converges (`fmax < 1000 kJ/mol/nm`) on 1AKI within 1000 steps.
9. `strict-config-required` missing FF → fails at preflight with `config_missing: force_field`.
10. `strict-config-required` missing `random_seed` → fails at preflight.
11. `strict-config-required` missing visualization sub-config (when `visualization.mode != disabled`) → fails at preflight.
12. `strict-config-required` with unresolved HIS → topology-planning fails with `unresolved_decisions`.
13. Transcript subsystem unit tests pass: fixtures F1 (no titratable) — F8 (deliberate unexpected-prompt) all yield expected `decision_trace` and outcomes.
14. Multichain homodimer fixture (TBD PDB, pinned pre-implementation) succeeds: chain merge/no-merge behavior correct, no cross-chain disulfide drift, EM converges.
15. Adversarial fixture suite: altloc-mixed (handled or fail), missing-loop/backbone (hard fail), protein+ligand (classified unsupported), metalloprotein (classified unsupported), nucleic acid (classified unsupported), MSE (handled per mode policy), retained crystallographic waters (preserved positionally, never replaced by `genion`), deliberate `.top`/`.gro` mismatch (caught at `consistency_gate`).
16. Reviewer's residual nitpicks from R5: `coordinate_id_map` injectivity enforced over *all* atoms (not just topology-affecting); retained-water survival verified immediately after `pdb2gmx` (not deferred to post-`genion`); `bulk_solvent` index derived from actual molecule ranges after `solvate`, not from arithmetic.

---

## Day-1 build priorities (from R5)

1. **Schemas first.** Implement `run_config.schema.json`, `StepFingerprint`, artifact roles, per-step report and fingerprint schemas before touching any GROMACS execution. Provenance and invalidation bolted on later make the whole system untrustworthy.
2. **`DialogueRunner` vertical slice.** PTY runner + semantic prompt recognizer + one pinned `pdb2gmx` fixture path end-to-end. Riskiest subsystem; determines whether topology generation is deterministic.
3. **1AKI golden path.** Smallest full path from `StructureIngest` → `Topology` → `Solvation` → `consistency_gate` → `ShortEM` with the pinned tutorial reference. Forces the artifact, hash, provenance, and readiness contracts into real shape.

---

## Issue ledger (rounds 1–5)

### Round 1 — 40 issues raised

- **Accepted (40):** protonation pipeline (1, 2, 3), `StructurePrep` cleaning vs. mutation split (4), asymmetric unit vs. biological assembly (5), altloc policy (6), crystallographic waters (7), ligand/cofactor/metal boundary (8), tutorial-profile rename (9), FF/water allowlist (10), v0 scope to soluble protein-only (11), box geometry rationale (12), padding policy (13), interaction modes (14), ion model provenance (15), `genion` group robustness (16), four-stage charge accounting (17), atom-count band (18), `grompp` consistency gate (19), `ShortEM` in v0 as validation gate (20 — accepted with framing defense), QC validator decomposition (21), Visualization distinct from QC (22), visualization mode contract (23), VMD headless best-effort (24), `readiness_status` (25), immutable manifest + index (26), schema versioning (27), retry classification (28), executor abstraction shape (29), Artifact URIs (30), mandatory provenance (31), Preflight phase (32), `md:prep-structure` `target_profile` (33), internal FF planning (34), adversarial fixture suite (35), tutorial vs. general modes (36), choice specification structure (37), step status state machine + resume (38), report regenerated from truth (39), v0 acceptance criteria (40).
- **Defended (0):** R1 had no successful defends — point 20's framing defense (EM as validation gate, not simulation phase) was accepted by GPT in R2 as a meaningful distinction.

### Round 2 — 35 issues raised

- **Accepted (35):** `StructureIngest` split from `StructurePrep` (1), `Pdb2GmxTranscript` keystone (2), `-ignh` default reversal (3), abstract+template protonation layers (4), FF/water allowlist correction (5), multi-label classifier (6), membrane heuristic (7), assembly selection placement (8 → folded into 1), altloc network rule (9), retained-water classifier caveats (10), drop bad density formula (11), `consistency_gate` semantics (12), grompp warning policy (13), four-way EM verdict (14), tutorial reference pinning (15), `genion` solvent-name discovery (16), `random_seed` requirement (17), provenance via include graph (18), `Task` workdir + path_map + produces (19), run-lock + crash recovery (20), content-hash dependency invalidation (21), `choice_specification` machine-actionable fields (22), `general_md_prep` FF/water contract reconciliation (23), capability-scoped Preflight (24), checkpoint-triggered visualization (25), `protein_with_structural_waters` exception (26), disulfide policy (27), terminal-capping policy (28), missing-residue policy (29), MSE→MET conditional default (30), warning class refinement (31), strict-mode acceptance tests (32), GROMACS version pinning (33), skill-boundary leak fix (34), transcript model as v0 artifact (35).
- **Defended (0).**

### Round 3 — 35 issues raised

- **Accepted (32):** `-inter` expansion (1), PTY/dialogue runner (2), semantic prompt recognition (3), explicit `-ff`/`-water` (4), chain policy (5), homodimer success fixture (6), missing-atom hard fail (7), altloc resolution before `pdb2gmx` (8), pre-rename validation (9), `StructureAnalyze` + `StructureTransform` split (10), MSE irreversible (11), MSE mode-conditional defaults (12), `XWA` proposal (13 — initially accepted, later withdrawn in R5 via positional index), water naming normalization (14), provenance via `.top` walk (15), `StepFingerprint` (16), step-specific sensitivity declarations (17), tool/version in fingerprint (18), GROMACS version framing (19), `needs_longer_em → not_validated` (20), warning severity (21), strict-mode viz conditional (22), `target_profile` preflight (23), membrane heuristic refinement (24), mmCIF canonical ingest (25), full residue identifiers (26), catalog discovery (27), stderr capture (28), error taxonomy (29), tutorial test hash expansion (30), visualization on hash-verified artifacts (31), explicit topology file naming (32).
- **Defended (3):** D1 (mmCIF→PDB bridge — defended, then strengthened in R4 with `coordinate_id_map.json`), D2 (tutorial-mode MSE hard-fail — accepted by GPT in R4), D3 (homodimer fixture deferred to implementation — accepted by GPT in R4 as not architecture-blocking).
- **Accepted at structural level (33, 34, 35):** profile versioning (33), transcript fixture matrix (34), `DialogueRunner` + `StepFingerprint` first-class (35).

### Round 4 — 18 issues raised (4 BLOCKING, 13 nitpicks, 1 D2/D3 acceptance)

- **BLOCKING accepted (4):** retained-water support via positional `bulk_solvent` index (R4-1), `coordinate_id_map.json` with injectivity verification (R4-2), per-step `tool_hash` declarations (R4-7), canonical `run_config.schema.json` with code-generated per-step `parameters_hash` (R4-8).
- **Defenses validated by reviewer (3):** D2 correct; D3 acceptable (time-boxed); D1 acceptable conditional on `coordinate_id_map.json` (now satisfied).
- **Nitpicks accepted (13):** DialogueRunner PTY caveat (R4-5), `PromptKind.CHAIN_MERGE` removal (R4-6), `code_hash` with source-file hash + dirty flag (R4-9), `LC_ALL=C` in `Task.env` (R4-10), `UnexpectedPromptError` payload (R4-11), synthetic transcript fixtures (R4-12), `system_final.top` as artifact role (R4-13), `readiness_reason` (R4-14), tutorial command-transcript pin (R4-15), cross-chain disulfide visibility (R4-16), two-stage Preflight (R4-17), fingerprint completeness (R4-18).

### Round 5 — Verdict `APPROVED`

Three additional residual nitpicks ingested as acceptance-criterion #16:
- `coordinate_id_map` injectivity enforced over all atoms, not just topology-affecting.
- Retained-water survival check immediately after `pdb2gmx`, not deferred.
- `bulk_solvent` index derived from molecule ranges after `solvate`, not arithmetic.

---

## Pointer to original artifact

`R1_to_gpt.md` Section 2 is the *original* architecture and was deliberately left intact for auditability. The consolidated, critique-hardened architecture is this document. Future work should reference this `FINAL_REVISION.md`, not `R1_to_gpt.md` Section 2.
