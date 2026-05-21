**P1.** The transcript subsystem is implementable, but not as a static “stdin lines + expected prompt strings” system. You are underestimating `pdb2gmx`’s prompt surface and how brittle exact prompt matching will be. It needs to be an interactive dialogue runner with semantic prompt recognition, version-pinned tests, and a hard fallback path.

**P2.** Input content hashes are not enough. You must track a step fingerprint: input artifact hashes + parameter/config/profile hash + mode hash + tool/version hash + relevant schema/code hash. Otherwise rerunning the same PDB with a different profile, FF, pH, box, ion policy, or GROMACS version can incorrectly reuse stale downstream outputs.

Sources I’m leaning on: GROMACS tutorial docs list `pdb2gmx -ter` and `-inter` behavior, including Glu/Asp/Lys/Arg/His/Cys interactive choices; GROMACS `pdb2gmx` docs call out `-ff`, `-water`, `-chainsep`, and `-merge`; current GROMACS docs are beyond 2024.3 as of May 21, 2026. See https://tutorials.gromacs.org/docs/md-intro-tutorial.html and https://manual.gromacs.org/documentation/2022-beta2/onlinehelp/gmx-pdb2gmx.html.

1. **WHAT:** `Pdb2GmxTranscript` omits `-inter`.
   **WHY:** `-inter` can prompt for Glu, Asp, Lys, Arg, His, and Cys/disulfide choices. Your catalog only covers HIS, termini, and disulfides.
   **WHAT TO DO:** Add `-inter` prompt families for ASP/ASH, GLU/GLH, LYS/LYN, ARG variants if supported by the selected FF, plus Cys oxidation choices.

2. **WHAT:** The transcript model treats static stdin as enough.
   **WHY:** Static piping can pass extra lines, miss a surprise prompt, or fail only after the command exits. It is also fragile against buffering.
   **WHAT TO DO:** Implement a PTY/dialogue runner: wait for a recognized prompt, parse available options, emit one answer, log the exchange. Static stdin is fallback only.

3. **WHAT:** Exact prompt-string matching is too brittle.
   **WHY:** GROMACS versions, terminal wrapping, stderr/stdout routing, localization, and option formatting can vary.
   **WHAT TO DO:** Set `LC_ALL=C`, pin version, then match semantic prompt classes and option tables, not full raw strings.

4. **WHAT:** You catalog force-field and water prompts, but those should not be interactive in normal runs.
   **WHY:** `pdb2gmx` supports `-ff` and `-water`. Relying on prompts for these adds avoidable fragility.
   **WHAT TO DO:** Always pass `-ff` and `-water` explicitly. Use prompt cataloging only to detect unexpected fallback behavior.

5. **WHAT:** Chain handling is still missing from the transcript surface.
   **WHY:** Multi-chain systems trigger decisions around `-chainsep` and `-merge`; cross-chain disulfides may require merging. GROMACS docs explicitly call chain separation/merge nontrivial.
   **WHAT TO DO:** Add chain policy to `topology_plan.json`: molecule separation, merge mode, termini per chain, cross-chain disulfide behavior.

6. **WHAT:** You now support “any assembly,” but have no multichain acceptance test that succeeds.
   **WHY:** Multimers are where chain merge, termini, molecule counts, and disulfides break.
   **WHAT TO DO:** Add a soluble homodimer success fixture, not only unsupported multimer/classifier fixtures.

7. **WHAT:** Missing-atom “decisions” should not be in the transcript catalog.
   **WHY:** `pdb2gmx` warnings/errors about missing atoms are not a clean interactive repair flow. Letting it proceed can generate bad topology.
   **WHAT TO DO:** Keep missing backbone/internal residues as pre-`pdb2gmx` hard fails. Do not try to answer them interactively.

8. **WHAT:** Altloc handling belongs before `pdb2gmx`, not in transcript.
   **WHY:** `pdb2gmx` is not an altloc resolver. Feeding unresolved altlocs is asking for unpredictable atom/residue mapping.
   **WHAT TO DO:** Require a single conformer coordinate set before topology.

9. **WHAT:** Pre-rename fallback is dangerous as described.
   **WHY:** Renaming residues can bypass explicit `pdb2gmx` chemistry checks and hide mismatches with FF templates.
   **WHAT TO DO:** Allow pre-renames only from a validated FF-specific mapping table. After `pdb2gmx`, verify the selected template/moleculetype matches the intended decision.

10. **WHAT:** `StructurePrep` is described as “analyzes only,” but it emits mutations including MSE→MET and altloc resolution.
    **WHY:** That is not analysis-only. The architecture language is inconsistent.
    **WHAT TO DO:** Split `StructureAnalyze` from `StructureTransform`, or admit `StructurePrep` mutates and require mutation validation.

11. **WHAT:** MSE→MET is not reversible.
    **WHY:** Replacing selenium with sulfur loses the original chemistry in the working coordinate set. Archiving the original is recoverable, not reversible.
    **WHAT TO DO:** Mark this mutation as `reversible: false`, keep original coordinates, and require explicit policy in general mode.

12. **WHAT:** Default MSE→MET conversion is too aggressive for `general_md_prep`.
    **WHY:** It is common, but still a chemical substitution.
    **WHAT TO DO:** In tutorial/noninteractive lab-profile mode, allow configured conversion. In general interactive mode, prompt. In strict mode, require `mse_policy`.

13. **WHAT:** Structural waters and `genion` now conflict.
    **WHY:** If retained waters share the solvent residue name, `genion` may replace structural waters with ions.
    **WHAT TO DO:** Separate retained crystallographic waters from bulk solvent in the index. `genion` replacement group must include only bulk solvent added by `gmx solvate`.

14. **WHAT:** Water residue normalization is underspecified.
    **WHY:** Crystal waters may be `HOH`, generated waters may be `SOL`, and FF water models may expect specific names.
    **WHAT TO DO:** Normalize or map water residue names before topology, then track `structural_water` vs `bulk_water` separately.

15. **WHAT:** `mdout.mdp` is not a resolved topology include graph.
    **WHY:** `mdout.mdp` records processed run parameters, not every FF/template/include file used.
    **WHAT TO DO:** Parse the `.top` include graph yourself, resolve `#include`s against working dir/`GMXLIB`, and hash those files directly.

16. **WHAT:** Parameter-hash invalidation is missing.
    **WHY:** Same PDB + different `--profile`, pH, FF, water model, ion seed, box padding, or interaction mode must invalidate different downstream steps.
    **WHAT TO DO:** Add `step_fingerprint.json` per step with `inputs_hash`, `parameters_hash`, `profile_hash`, `mode_hash`, `tool_hash`, `schema_hash`, and `code_hash`.

17. **WHAT:** You need step-specific sensitivity declarations.
    **WHY:** Not every parameter invalidates every step. Visualization config should not invalidate topology; pH should.
    **WHAT TO DO:** Each step schema declares `depends_on_parameters`. Resume computes invalidation from those declarations.

18. **WHAT:** Tool/version hash must participate in invalidation.
    **WHY:** Reusing a topology generated under GROMACS 2024.3 after upgrading to 2026.x is not reproducible.
    **WHAT TO DO:** Include GROMACS executable path, `gmx -version`, FF directory hash, and transcript catalog version in topology/solvation/EM fingerprints.

19. **WHAT:** “GROMACS 2024.3 — current stable as of writing” is false as of May 21, 2026.
    **WHY:** Current GROMACS docs/search results show newer 2026 releases. Pinning 2024.3 is fine; calling it current is not.
    **WHAT TO DO:** Say “v0 pins 2024.3 for tutorial reproducibility,” not “current stable.”

20. **WHAT:** `needs_longer_em → ready_with_warnings` is too lenient.
    **WHY:** If EM did not meet the validation criterion, the system is not validated as ready. A user may run dynamics on a bad starting structure.
    **WHAT TO DO:** Map `needs_longer_em` to `not_validated` or `blocked_pending_longer_em`, not `ready_with_warnings`.

21. **WHAT:** Warning class alone is insufficient.
    **WHY:** A minor physics warning and a severe physics warning should not produce the same readiness status.
    **WHAT TO DO:** Add severity: `info | warning | blocking`. Chemistry/physics warnings can be nonblocking only when explicitly classified as low severity.

22. **WHAT:** `strict-config-required` blocking on missing visualization config is wrong when visualization is disabled.
    **WHY:** Strict mode should require only parameters relevant to enabled features.
    **WHAT TO DO:** Require visualization config only when `visualization.mode != disabled`.

23. **WHAT:** `Preflight` says `md:prep-structure` does not need GROMACS, but `target_profile` may require FF database knowledge.
    **WHY:** If prep decisions depend on downstream FF templates, you may need the FF files even during prep.
    **WHAT TO DO:** If `target_profile` is supplied, preflight must verify the profile/FF metadata needed for prep-time compatibility.

24. **WHAT:** Membrane detection heuristic will false-positive soluble helical bundles and false-negative beta-barrels.
    **WHY:** “20 contiguous nonpolar residues + cylindrical span” is crude.
    **WHAT TO DO:** Treat heuristic positives as `environment: unknown_or_membrane_likely` unless metadata confirms. Block in noninteractive, prompt in interactive.

25. **WHAT:** `StructureIngest` still needs mmCIF-first handling.
    **WHY:** Modern PDB entries often require mmCIF for complete assembly, chain, auth/label ID, insertion-code, and metadata fidelity.
    **WHAT TO DO:** Use mmCIF as canonical ingest from RCSB; emit PDB only as a derived working format if GROMACS requires it.

26. **WHAT:** Residue identity needs insertion codes and auth IDs.
    **WHY:** `(chain, resid)` is not unique enough across PDB/mmCIF edge cases.
    **WHAT TO DO:** Use full residue identifiers: model, auth_asym_id, label_asym_id, auth_seq_id, label_seq_id, insertion code, residue name.

27. **WHAT:** Transcript catalog options should be discovered, not hand-entered.
    **WHY:** Force-field-specific termini/protonation options can drift.
    **WHAT TO DO:** Generate catalog entries from a controlled probe run and/or FF database parsing, then snapshot them for the pinned version.

28. **WHAT:** The transcript parser must capture stderr too.
    **WHY:** GROMACS prompts and warnings may appear on stderr depending on build/runtime.
    **WHAT TO DO:** Dialogue runner must merge or monitor stdout/stderr and preserve both raw streams.

29. **WHAT:** You still do not define how `pdb2gmx` failures are normalized.
    **WHY:** Agents need structured failure reasons, not just “unexpected interaction.”
    **WHAT TO DO:** Add error taxonomy: unsupported residue, missing atom, chain inconsistency, prompt mismatch, FF/water unavailable, template mismatch, disulfide mismatch.

30. **WHAT:** Acceptance test 14 hashes only `[ molecules ]`.
    **WHY:** Molecule counts can match while topology parameters differ.
    **WHAT TO DO:** Hash `[ molecules ]` for stable count matching, but also validate FF include hashes, water include, ion include, and selected moleculetype/template names.

31. **WHAT:** Optional visualization checkpoint side effects can race with mutable upstream artifacts.
    **WHY:** If a downstream step rewrites `system.top` or `system.gro`, visualization may render a moving target.
    **WHAT TO DO:** Visualization must consume immutable artifact hashes from the completed step report, not path names that may be overwritten.

32. **WHAT:** `system.top` appears in both topology and solvation steps.
    **WHY:** Reusing the same filename across step directories is fine, but reports and users can confuse pre-solvation vs post-ion topology.
    **WHAT TO DO:** Use explicit names: `topology/system.top`, `solvation/system_ions.top`, or require artifact role labels.

33. **WHAT:** You have not specified how profiles are versioned.
    **WHY:** Changing a lab profile silently changes scientific outputs.
    **WHAT TO DO:** Profiles need IDs, semantic versions, content hashes, changelogs, and inclusion in step fingerprints.

34. **WHAT:** The transcript subsystem is now load-bearing enough to deserve its own acceptance fixture matrix.
    **WHY:** One 1AKI integration test will not cover prompt drift.
    **WHAT TO DO:** Add fixtures for: no HIS, one HIS, multiple HIS, termini prompts, disulfide yes/no, multichain merge/no-merge, charged side-chain `-inter`, and unexpected extra prompt.

35. **WHAT:** This is close, but not approvable until transcript execution and parameter invalidation are specified at implementation level.
    **WHY:** Those two pieces determine whether the system is deterministic or just well-documented.
    **WHAT TO DO:** Make `DialogueRunner` and `StepFingerprint` first-class v0 design artifacts with schemas and tests.

VERDICT: ISSUES_REMAIN