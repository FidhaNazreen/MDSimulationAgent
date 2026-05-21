# Round 5 counterreply (final round of cap)

Substantive convergence: 4 BLOCKING issues + 13 nitpicks. Accepting all 4 BLOCKING with concrete fixes and all nitpicks with one-line resolutions. Asking for `VERDICT: APPROVED` at the end if the four BLOCKING items are correctly closed.

## Section 1 — Closing the BLOCKING issues

**R4-1 — Structural-water support breaks `pdb2gmx`.** **Accept. Option (c) chosen:** keep retained crystallographic waters under the FF's standard water residue name (e.g. `SOL` for SPC/TIP3P), let `pdb2gmx` see them as ordinary water molecules, and build the `genion` replacement index *positionally* from only the bulk waters added by `gmx solvate` — not by residue name. Implementation:

1. **Before `pdb2gmx`:** retained crystallographic waters keep the FF-expected residue name (`SOL`). Their original atom serial numbers and coordinates are recorded in `step_02_structure_prep/retained_waters.json` (atom serial, residue id, coordinates) so we can identify them later by *position*, not by name.
2. **Run `pdb2gmx`** normally — it produces `system.gro` with the retained waters indexed at the beginning of the solvent section.
3. **After `gmx solvate`:** the bulk waters added by `solvate` are appended *after* the retained waters in the `.gro` file (this is `gmx solvate`'s documented behavior — it appends to the existing solvent group). The `Solvation` agent records `n_retained_waters` (from step 2) and `n_bulk_waters_added` (from `solvate` stdout / topology diff).
4. **Index for `genion`:** build a custom index group `bulk_solvent` containing only the last `n_bulk_waters_added` water molecules in residue order — i.e. waters added by `solvate`. `genion` replaces atoms only from this group. Retained crystallographic waters are never replaced by ions.
5. **Verification:** after `genion`, count retained waters in the output `.gro` (positional match against `retained_waters.json` by coordinate proximity, since `genion` doesn't move other atoms). Any retained water displaced → hard fail with `retained_water_displaced`.

Result: no novel residue name (no need for `XWA` template), `pdb2gmx` happy, `genion` provably never touches structural waters. `XWA` proposal from R3-13 is withdrawn.

**R4-2 — `D1` mmCIF→PDB bridge needs `coordinate_id_map.json`.** **Accept.** `StructureIngest` emits `coordinate_id_map.json` containing per-residue and per-atom canonical-to-derived mappings:
```json
{
  "schema_version": "0.1.0",
  "residues": [
    {
      "canonical": {"model": 1, "label_asym_id": "A", "auth_asym_id": "A",
                    "label_seq_id": 15, "auth_seq_id": 15, "insertion_code": " ",
                    "residue_name": "HIS"},
      "derived_pdb": {"chain": "A", "resid": 15, "icode": " ", "residue_name": "HIS"}
    }, ...
  ],
  "atoms": [...],
  "injectivity": "verified" | "lossy_with_diff",
  "lossy_diff": [...]   // only if injectivity != verified
}
```
Validation at write time: every canonical residue with `residue_name ∈ {topology_affecting_set}` (any titratable, terminal, CYS, MSE, or otherwise-decision-bearing residue) must map injectively to a unique `derived_pdb` tuple. If any topology-affecting residue is not injective (e.g. two residues collide in `(chain, resid, icode)` after dropping mmCIF asym_id distinctions) → hard fail before `pdb2gmx` with `coordinate_id_map_not_injective`. Insertion codes that don't round-trip are detected here. Topology decisions are keyed by *canonical* IDs throughout the system; the bridge maps to derived IDs only at `pdb2gmx`-invocation time, and validates the answer-to-residue mapping per-prompt against `coordinate_id_map.json`.

**R4-7 — `StepFingerprint.tool_hash` too GROMACS-centric; must be step-specific.** **Accept.** `tool_hash` becomes a step-keyed map in `schemas/v0.1.0/steps/<step>.schema.json`:
```yaml
# StructureIngest:        [mmcif_parser_code_hash, gemmi_or_biopython_version, fetcher_code_hash]
# StructureAnalyze:       [propka_version_or_unavailable, structure_analyzer_code_hash, altloc_resolver_code_hash, water_classifier_code_hash]
# StructureTransform:     [transform_code_hash, residue_rename_table_hashes_per_ff, mmcif_to_pdb_converter_code_hash]
# Topology:               [gmx_version_stdout, ff_dir_recursive_hash, transcript_catalog_hash_for_version, dialogue_runner_code_hash]
# Solvation:              [gmx_version_stdout, ff_dir_recursive_hash, water_model_include_hash, ion_include_hash]
# ShortEM:                [gmx_version_stdout, ff_dir_recursive_hash, em_mdp_template_hash]
# Visualization:          [viewer_executable_path, viewer_version, viz_script_template_hash]
```
Each step's `tool_hash` is the sha256 of its own declared tool inputs. Resume invalidation walks per-step.

**R4-8 — `depends_on_parameters` must be derived from a canonical config schema, not hand-maintained.** **Accept.** Introducing `schemas/v0.1.0/run_config.schema.json` as **the** canonical, exhaustive config schema. Every configurable parameter (FF, water, pH, salt concentration, ion species, random seed, box geometry, padding, EM step cap, EM tolerance, assembly policy, chain selection, water-retention policy, environment override, MSE policy, altloc policy, disulfide policy, termini policy, interaction mode, pipeline mode, visualization mode/viewer/checkpoints/render, profile reference, target_profile) is a named field with type, default, applicability_predicate, and which step depends on it.

Each step's schema **does not list parameters by hand**. Instead it declares `depends_on_config_fields: list[<field-selector>]` referring to the canonical schema. A code-generated helper computes the per-step `parameters_hash` from those selectors. Adding a new parameter requires updating only the canonical schema; per-step sensitivity declarations refer to it by reference, and the implementation enforces that every canonical-schema field is referenced by *at least one* step's `depends_on_config_fields` (so no parameter can silently fall outside fingerprinting).

This subsumes the R4-18/P5 concern: the canonical run-config + step-specific external-tool manifests are now both first-class fingerprint inputs.

## Section 2 — Nitpicks resolved (one line each)

- **R4-3 (D2 correct):** Accepted — `tutorial_mode_does_not_handle_mse` stays.
- **R4-4 (D3 time-boxed):** Accepted — homodimer fixture marked `TBD-pre-implementation`; PDB ID pinned before any implementation work begins.
- **R4-5 (DialogueRunner caveat: don't promise separate stdout/stderr ordering under PTY):** Accepted — merged PTY transcript is authoritative; separate streams archived as best-effort only.
- **R4-6 (`CHAIN_MERGE` is not actually a prompt):** Accepted — `chain_policy` stays in plan, but `PromptKind.CHAIN_MERGE` removed. Chain merge driven by `pdb2gmx` flags only.
- **R4-9 (`code_hash` needs source-file hash + dirty flag):** Accepted — `code_hash = sha256(concat(sorted(source_file_hashes))) + git_commit + dirty_flag`.
- **R4-10 (`LC_ALL=C` in `Task.env`):** Accepted — `Task.env` carries `LC_ALL=C` (and `LANG=C`); the executor records actual env in `ExecutionResult.env_resolved` for provenance.
- **R4-11 (`UnexpectedPromptError` payload):** Accepted — includes `last_recognized_exchange`, `raw_buffer_tail`, `argv`, `gmx_version`, `topology_plan_excerpt`.
- **R4-12 (use synthetic tiny structures for transcript fixtures):** Accepted — F1–F8 use minimal hand-curated coordinate fixtures (≤ 30 residues each); 1AKI used only for the integration test.
- **R4-13 (`system_final.top` as artifact role, not symlink):** Accepted — `index.json` records artifact roles; symlink is local-convenience only.
- **R4-14 (preserve `readiness_reason`):** Accepted — `readiness_status` gains `readiness_reason: ["em_skipped" | "em_needs_longer" | "missing_tool" | ...]`.
- **R4-15 (pin command transcript + PDB hash + expected molecule counts for tutorial parity):** Accepted — `tutorial_reference.json` records the exact command sequence, input PDB sha256, expected `[ molecules ]` table, all pinned alongside the GROMACS version.
- **R4-16 (cross-chain disulfide auto-merge needs visibility):** Accepted — in `strict-config-required`, required as explicit config; in other modes, recorded as `auto_choice` with full reasoning in `topology_plan.json` and surfaced in the report.
- **R4-17 (`Preflight` does coarse pre-ingest check, refined post-ingest):** Accepted — preflight split into `preflight_early` (tool availability, writable dir, viewer probe) and `preflight_post_ingest` (disk space estimate from structure size, resource request feasibility).

## Section 3 — Final critique prompt

This is round 5, the final round of the cap. The four BLOCKING issues you identified are now closed:
- **R4-1** by positional `bulk_solvent` index, no `XWA` template needed.
- **R4-2** by `coordinate_id_map.json` with injectivity verification for topology-affecting residues.
- **R4-7** by per-step `tool_hash` declarations in step schemas.
- **R4-8** by a canonical `run_config.schema.json` with code-generated per-step `parameters_hash`.

All 13 nitpicks are resolved.

Apply the original threshold strictly:

  VERDICT: APPROVED
  VERDICT: ISSUES_REMAIN

`APPROVED` if there are no remaining issues you would *block* on. Nitpicks alone do not justify `ISSUES_REMAIN` — list them but verdict `APPROVED`. `ISSUES_REMAIN` only if a *new* blocking concern exists or one of the four fixes above is materially wrong.

If you find a fifth blocking issue we missed, name it explicitly and label it `BLOCKING:` at the front so the loop-exit code can route it correctly.

Final consolidation request: regardless of verdict, list the top 3 highest-leverage things the implementation should *start with* on day 1 of v0 build — the items where mistakes are hardest to fix later.
