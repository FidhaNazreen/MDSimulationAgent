1. **BLOCKING — Structural-water support is still broken.**
   **WHAT:** R3-13 says retained crystallographic waters are renamed to `XWA`, listed separately in `[ molecules ]`, and carried through topology.
   **WHY:** `pdb2gmx` will not know what `XWA` is unless you provide a matching residue/template/moleculetype. Renaming waters away from the FF water residue name avoids `genion`, but creates a topology problem.
   **WHAT TO DO:** Pick one:
   - v0 strips all crystallographic waters, including in general mode.
   - Or implement retained-water support explicitly: exclude retained waters from `pdb2gmx`, generate protein topology, then merge retained-water coordinates back with a known water moleculetype/include and molecule count.
   - Or keep retained waters as normal water residue names and build the `genion` index by selecting only bulk waters added by `gmx solvate`, not by residue name alone.

2. **BLOCKING — D1 is defensible only with an invertible mmCIF→PDB mapping.**
   **WHAT:** You say the PDB bridge may lose insertion codes and records the loss.
   **WHY:** Recording loss is not enough. Topology decisions are keyed by canonical mmCIF residue IDs; `pdb2gmx` consumes derived PDB residue IDs. If the mapping is not one-to-one, the transcript may answer for the wrong residue.
   **WHAT TO DO:** The bridge must emit `coordinate_id_map.json`: canonical mmCIF residue/atom ID → derived PDB chain/resid/icode/atom serial. If mapping is not injective and round-trippable for every residue that affects topology, hard fail before `pdb2gmx`.

3. **D2 is correct.**
   **WHAT:** Hard-failing MSE in `tutorial_reproduction` mode is better than silently converting.
   **WHY:** Tutorial mode is specifically for 1AKI parity; MSE is outside that contract.
   **WHAT TO DO:** Keep your counter-proposal: `tutorial_mode_does_not_handle_mse`.

4. **D3 is acceptable, but time-boxed.**
   **WHAT:** Deferring the exact homodimer fixture is not an architecture blocker.
   **WHY:** The requirement is the behavior tested, not the specific PDB ID.
   **WHAT TO DO:** Before implementation starts, pin the fixture. Until then mark the test as `TBD fixture`, not complete.

5. **P4 — `DialogueRunner` is implementable in a week if scoped to one pinned GROMACS version.**
   **WHAT:** The architecture is now clear enough for a competent engineer.
   **WHY:** PTY loop, prompt recognizer, plan resolver, exchange log, and failure taxonomy are concrete.
   **WHAT TO DO:** Use `pexpect` or equivalent. Do not promise separate stdout/stderr ordering if using a PTY; keep the merged PTY transcript as authoritative and archive separate streams only if technically available.

6. **Nitpick — `CHAIN_MERGE` may not be an actual prompt.**
   **WHAT:** Chain merge is mostly driven by CLI flags/options, not necessarily an interactive prompt.
   **WHY:** Treating it as a prompt kind may confuse the catalog.
   **WHAT TO DO:** Keep `chain_policy`, but model CLI-only decisions separately from prompt-driven exchanges.

7. **BLOCKING — `StepFingerprint.tool_hash` is too GROMACS-centric.**
   **WHAT:** It includes GROMACS, FF hash, transcript catalog, and `DialogueRunner` code, but not all tools that affect earlier steps.
   **WHY:** PROPKA version, structure parser version, catalog-probe code, residue-renaming table, water-classifier code, and mmCIF conversion code can change outputs without changing input artifacts.
   **WHAT TO DO:** Make `tool_hash` step-specific. For `StructureAnalyze`, include PROPKA/parser versions and structure-analysis code. For `StructureTransform`, include rename tables and conversion code. For `Topology`, include GROMACS/FF/transcript data.

8. **BLOCKING — `depends_on_parameters` enum is still incomplete unless treated as exhaustive schema, not examples.**
   **WHAT:** The examples omit pH, salt concentration, EM step cap, EM tolerance, assembly policy, chain selection, water-retention policy, environment override, and MSE policy in some places.
   **WHY:** A changed pH or assembly selection with the same input PDB must invalidate downstream artifacts.
   **WHAT TO DO:** Define a canonical config schema and compute each step’s parameter subset from that schema. Do not hand-maintain loose lists.

9. **Nitpick — `code_hash = git commit if available` is not enough.**
   **WHAT:** Dirty worktrees and generated schema files can change behavior without changing commit.
   **WHY:** Resume semantics during development will be wrong.
   **WHAT TO DO:** Prefer hash of loaded source files plus git commit metadata; record dirty status separately.

10. **Nitpick — `LC_ALL=C` should be enforced in `Task.env`, not only `DialogueRunner`.**
    **WHAT:** You mention env overrides in the runner.
    **WHY:** The executor should record the actual environment used for provenance and fingerprinting.
    **WHAT TO DO:** Make environment part of `Task`, provenance, and relevant fingerprints.

11. **Nitpick — `UnexpectedPromptError` should include the last recognized exchange.**
    **WHAT:** Debugging prompt drift without context is painful.
    **WHY:** The fix is usually “catalog missing a prompt after residue X.”
    **WHAT TO DO:** Include raw buffer, previous exchange, argv, GROMACS version, and topology plan excerpt.

12. **Nitpick — catalog discovery fixtures should be tiny synthetic structures where possible.**
    **WHAT:** Full PDB fixtures make prompt tests slower and noisier.
    **WHY:** Transcript behavior is about prompt coverage, not scientific realism.
    **WHAT TO DO:** Use minimal hand-curated coordinate fixtures for transcript tests; reserve real PDBs for integration.

13. **Nitpick — `system_final.top` symlink can be awkward on remote/object stores.**
    **WHAT:** Symlinks are not portable across all artifact backends.
    **WHY:** You already have artifact handles.
    **WHAT TO DO:** Make `output/system_final.top` an artifact role in `index.json`; create a symlink only for local convenience.

14. **Nitpick — readiness mapping should preserve `not_validated` reason.**
    **WHAT:** `not_validated` can mean skipped EM, longer EM needed, or missing tool.
    **WHY:** Same status, different user action.
    **WHAT TO DO:** Add `readiness_reason`.

15. **Nitpick — `v0 pins 2024.3` is fine, but tutorial parity requires exact tutorial command transcript too.**
    **WHAT:** GROMACS version alone is not the reference.
    **WHY:** Tutorial pages evolve and local commands can differ.
    **WHAT TO DO:** Pin command transcript, input PDB hash, and expected molecule counts.

16. **Nitpick — cross-chain disulfide auto-forcing merge needs user visibility.**
    **WHAT:** You auto-merge chains with cross-chain disulfides.
    **WHY:** Correct chemically, but it changes molecule semantics.
    **WHAT TO DO:** Record it as a blocking-required decision in strict mode and a visible auto-choice in other modes.

17. **Nitpick — `Preflight` should estimate disk after knowing structure size.**
    **WHAT:** Preflight runs before ingest.
    **WHY:** Disk estimate from prompt alone may be poor.
    **WHAT TO DO:** Do early coarse preflight, then post-ingest resource estimate.

18. **P5 summary — the fingerprint design is nearly right but not sufficient yet.**
    **WHAT:** It covers the right categories but misses complete per-step tool/config sensitivity.
    **WHY:** That can cause stale reuse after pH/profile/parser/tool changes.
    **WHAT TO DO:** Promote the full normalized run config and step-specific external tool manifests into the fingerprint contract.

VERDICT: ISSUES_REMAIN