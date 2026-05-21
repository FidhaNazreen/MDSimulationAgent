**Clarifications**

**C1.** It should be both. `tutorial_reproduction` vs `general_md_prep` is a runtime mode because it changes validation criteria, prompting, and allowed behavior. It also selects a profile because FF/water/box/ion defaults live in profiles. Keep both layers, but do not let them blur: mode answers “what contract are we satisfying?”; profile answers “what parameters do we use?”

**C2.** The EM distinction is meaningful if you rename the v0 deliverable to “prepared and EM-validated starting system.” It is papering over the boundary if the report says “prep only” while using EM to decide readiness. The clean boundary is: v0 includes setup plus minimal validation EM; v1 starts equilibration and production.

**C3.** Keep `md:validate-system` as a standalone power-user skill, but make validation implicit in `md:solvate-system` and `md:run-workflow` by default. A solvation skill that emits an unvalidated system as “done” is a footgun. Allow `skip_validation: true`, but then readiness must be `not_validated`.

1. **WHAT:** Your DAG is structurally impossible: `SystemClassifier` runs before `StructurePrep`, but `StructurePrep` is where fetching happens.
   **WHY:** The classifier cannot classify a PDB ID without first resolving it to coordinates and metadata.
   **WHAT TO DO:** Add `StructureIngest` before `SystemClassifier`, or move fetch/model/assembly selection out of `StructurePrep`.

2. **WHAT:** The proposed `pdb2gmx --his` control is not a real per-residue CLI interface.
   **WHY:** GROMACS exposes `-[no]his` as interactive histidine selection; it does not provide a clean `--his residue=value` API. The docs say His choices are otherwise automatic from H-bond geometry.
   **WHAT TO DO:** Drive `pdb2gmx -his -ter` via a generated stdin transcript, or pre-rename residues using force-field-specific names and verify the resulting topology. Source: GROMACS `pdb2gmx` docs, https://manual.gromacs.org/documentation/2020/onlinehelp/gmx-pdb2gmx.html.

3. **WHAT:** “Drop `-ignh` from the default” is probably the wrong default.
   **WHY:** Most PDB inputs have no hydrogens or incompatible/partial hydrogens. Preserving them makes topology generation fragile. But using `-ignh` without an explicit protonation transcript loses intent.
   **WHAT TO DO:** Default to stripping/regenerating hydrogens through `pdb2gmx`, but require explicit recorded choices for HIS/termini/special protonation. Preserve input hydrogens only under a strict compatibility policy.

4. **WHAT:** `HID|HIE|HIP` is not portable GROMACS residue naming.
   **WHY:** Histidine residue names differ by force field and GROMACS database, e.g. HISD/HISE/HISH-style names appear in GROMACS topology inputs.
   **WHAT TO DO:** Store abstract decisions separately from force-field residue/template names: `abstract_state: delta|epsilon|doubly_protonated`, `ff_template: HSD/HSE/HSP/...`.

5. **WHAT:** Your FF/water allowlist contradicts the tutorial profile.
   **WHY:** You lock tutorial mode to OPLS-AA/L + SPC, but your example allowlist says OPLS-AA/L ↔ TIP3P/TIP4P and omits SPC.
   **WHAT TO DO:** Fix the matrix before implementation. If OPLS+SPC is allowed only for tutorial reproduction, encode that explicitly.

6. **WHAT:** `protein_only_soluble | multimer | mixed` are not mutually exclusive classes.
   **WHY:** A soluble protein homodimer is both protein-only and multimer. Your single-label classifier can reject valid systems or misreport why.
   **WHAT TO DO:** Make classification multi-label: `chemistry`, `assembly`, `environment`, `unsupported_features`.

7. **WHAT:** The classifier cannot detect “membrane” reliably from coordinates alone.
   **WHY:** A membrane protein PDB often has no membrane present. It may look like protein-only unless you inspect annotations, OPM/PPM metadata, hydrophobic span, or user intent.
   **WHAT TO DO:** Add a membrane-protein heuristic and metadata lookup; if ambiguous, fail/prompt instead of classifying as soluble.

8. **WHAT:** Biological assembly selection still sits in the wrong place.
   **WHY:** Assembly choice affects classification, chain count, interfaces, altlocs, waters, and topology. It must happen before most structure decisions.
   **WHAT TO DO:** Put `model/assembly/chain selection` in `StructureIngest`, then classify the selected coordinate set.

9. **WHAT:** The altloc “neighbor clash < 2.0 Å” rule is not enough.
   **WHY:** Altloc networks are about mutually exclusive conformers, not only clashes. Occupancy labels can be correlated across residues without direct clashes.
   **WHAT TO DO:** Build altloc conformer sets by altloc ID and occupancy group first; use clash checks only as a sanity check.

10. **WHAT:** Your retained-water classifier is still too confident.
   **WHY:** “Buried + low B-factor + multiple partners” is useful, but B-factors are structure-specific and not normalized across chains, ligands, cryo-EM, or low-resolution structures.
   **WHAT TO DO:** Treat retained waters as “preserve with warning” unless tutorial mode strips them. Record confidence, but do not pretend the classifier knows catalytic relevance.

11. **WHAT:** The solvent estimate uses a bad protein atom-density approximation.
   **WHY:** `ρ_protein ≈ 30 atoms/nm³` is too low for all-atom protein density, so `V_excluded` is inflated and the expected-water band becomes meaningless.
   **WHAT TO DO:** Use a grid/VDW-volume estimate, solvent-accessible mask, or compare against `gmx solvate` topology deltas directly. Do not gate correctness on that crude formula.

12. **WHAT:** “Topology grompp gate” before box/solvent is underspecified.
   **WHY:** A post-`pdb2gmx` protein may lack the final box, solvent, ions, and production-relevant `.mdp`. A zero-step `grompp` can pass while the eventual system fails.
   **WHAT TO DO:** Define exactly what this gate proves: topology-coordinate consistency only. Do not count it as physical validation.

13. **WHAT:** `grompp` log scanning for “Fatal error” is not sufficient.
   **WHY:** `grompp` warnings can be fatal scientifically even when exit code is zero, especially if someone uses `-maxwarn`.
   **WHAT TO DO:** For validation gates, forbid `-maxwarn > 0` by default. Parse structured exit code plus warnings; maintain an allowlist of acceptable warnings.

14. **WHAT:** Short EM convergence criterion is too rigid.
   **WHY:** A valid large or strained system may not hit `fmax < 1000` in 1000 steps; a bad system may reduce below threshold while still chemically wrong.
   **WHAT TO DO:** Use EM as one validator, not the sole readiness determinant. Record convergence curve, max-force atoms, step count, and whether failure is “blocked” vs “needs longer EM.”

15. **WHAT:** Your v0 acceptance criterion says 1AKI must match canonical tutorial outputs exactly.
   **WHY:** GROMACS version, force-field files, `genion` seed, water model files, and tutorial revisions can change counts or logs.
   **WHAT TO DO:** Pin the reference: exact GROMACS version, tutorial revision, command transcript, random seed, and expected artifact hashes/counts.

16. **WHAT:** `genion` solvent group hard-codes `SOL`.
   **WHY:** Water residue names can differ by input, water model, or conversion path.
   **WHAT TO DO:** Discover solvent molecule name from topology/water model output, then generate the index from that. Verify molecule size and residue count.

17. **WHAT:** `genion -conc` with neutralization needs deterministic seed handling.
   **WHY:** Ion placement is random; resume/reproduction tests will drift without `-seed`.
   **WHAT TO DO:** Require `random_seed` in strict mode and record the effective seed in all modes. Source: `gmx genion` exposes `-seed`, https://manual.gromacs.org/documentation/2024.3/onlinehelp/gmx-genion.html.

18. **WHAT:** Provenance “parsed from stdout” is not reliable.
   **WHY:** GROMACS output may not list every included file, and include chains can be nested.
   **WHAT TO DO:** Parse the final `.top` include graph and hash the actual resolved files. Also archive `mdout.mdp` from `grompp`.

19. **WHAT:** `Artifact` handles are under-specified for command execution.
   **WHY:** `Task` lacks an explicit working directory, sandbox directory, and mapping from artifact URI to process-local path.
   **WHAT TO DO:** Add `workdir`, `path_map`, and `produces` semantics. Remote executors need a concrete execution filesystem.

20. **WHAT:** `index.json` still has race and crash ambiguity.
   **WHY:** Temp+rename prevents torn writes, but it does not prevent two orchestrator instances from racing or a stale `running` state after crash.
   **WHAT TO DO:** Add a run lock/lease file and recovery rules for stale `running` steps.

21. **WHAT:** Resume “restart at first non-succeeded step” is too simplistic.
   **WHY:** A downstream succeeded step can be invalidated by an upstream retry or changed config.
   **WHAT TO DO:** Use content-hash dependency invalidation. If an input hash changes, mark all dependent steps invalidated.

22. **WHAT:** `choice_specification.json` records prompts, but not machine-actionable policy.
   **WHY:** Natural-language consequence text is not enough for noninteractive or reproducible runs.
   **WHAT TO DO:** Store both user-facing text and normalized decision fields with enums, schema, defaults, and validation rules.

23. **WHAT:** `general_md_prep` says FF/water is always user-surfaced, but noninteractive modes forbid prompting.
   **WHY:** This is a contract conflict.
   **WHAT TO DO:** Rephrase: in general mode FF/water is required. It is prompted only in `interactive`; otherwise it must come from config/profile or fail.

24. **WHAT:** `md:prep-structure` running `Preflight` every time is noisy and possibly wrong.
   **WHY:** Prep alone does not need VMD, EM, ion tools, or maybe even full GROMACS availability.
   **WHAT TO DO:** Make preflight capability-scoped: check only tools needed for the requested skill plus declared downstream target profile.

25. **WHAT:** Visualization after EM loses earlier failure observability.
   **WHY:** If solvation fails, users may still want the prep/topology snapshot. Your DAG places visualization after EM only.
   **WHAT TO DO:** Treat visualization as checkpoint-triggered side effects after selected steps, not a single terminal phase.

26. **WHAT:** “All other classes fail fast” conflicts with retained-water fixture success.
   **WHY:** A protein with crystallographic waters is not protein-only if waters are treated as separate molecules, but you also want retained-water support.
   **WHAT TO DO:** Define `protein_only_soluble` as allowing crystallographic waters subject to water policy, or add `protein_with_structural_waters` as supported.

27. **WHAT:** You still lack a clear policy for disulfides.
   **WHY:** `pdb2gmx` can detect/choose disulfide bonds; wrong CYS/CYX handling changes protein topology.
   **WHAT TO DO:** Add disulfide detection and decision records alongside protonation decisions. Use `-ss` transcript or explicit residue/template handling.

28. **WHAT:** You lack terminal-capping policy.
   **WHY:** ACE/NME, charged termini, chain breaks, and missing terminal residues affect total charge and topology.
   **WHAT TO DO:** Add termini decisions to `topology_plan.json` with actual `pdb2gmx` transcript and final template names.

29. **WHAT:** Missing-residue handling is still not operational.
   **WHY:** You say missing loops/backbone fixture exists, but not whether gaps are allowed, capped, modeled, or rejected.
   **WHAT TO DO:** For v0, hard-fail missing backbone atoms or internal missing residues. Allow missing terminal tails only if explicitly configured and recorded.

30. **WHAT:** `SystemClassifier` rejection of selenomethionine may be too blunt.
   **WHY:** MSE-to-MET conversion is common and often acceptable for protein-only prep.
   **WHAT TO DO:** Decide whether MSE→MET is an allowed reversible mutation in v0. If yes, implement it explicitly; if no, classify unsupported with a precise reason.

31. **WHAT:** `readiness_status` conflates validation completeness and warning severity.
   **WHY:** `ready_with_warnings` could mean harmless visualization skip or serious retained-water ambiguity.
   **WHAT TO DO:** Add warning classes: `reproducibility`, `chemistry`, `physics`, `io`, `visualization`. Chemistry/physics warnings should probably block in strict mode.

32. **WHAT:** The acceptance tests still do not include a noninteractive failure for missing required config.
   **WHY:** Your new mode contract is central. It must be tested.
   **WHAT TO DO:** Add tests for `strict-config-required` missing FF, missing ion seed, missing visualization setting, and unresolved HIS.

33. **WHAT:** You cite GROMACS version minimum, but not supported major-version behavior.
   **WHY:** `pdb2gmx` prompts, force-field directories, water names, and outputs can vary across versions.
   **WHAT TO DO:** Pin a supported version range for v0, likely one exact version for tutorial reproduction and a tested range for general mode.

34. **WHAT:** The skill boundary is still slightly leaky.
   **WHY:** `md:validate-system` is useful, but validation is not optional if upstream skills claim readiness.
   **WHAT TO DO:** Keep the skill, but make `md:solvate-system` default to `Solvation + grompp + ShortEM + validators`. Only produce unvalidated artifacts under an explicit skip flag.

35. **WHAT:** The updated plan is much better, but still not implementable without a concrete GROMACS interaction transcript model.
   **WHY:** Most hard cases now depend on driving `pdb2gmx` choices deterministically. Without a transcript generator/parser, the protonation/termini/disulfide plan is aspirational.
   **WHAT TO DO:** Make the transcript model a v0 design artifact: expected prompts by GROMACS version, generated stdin, parsed stdout, and tests for every interactive branch.

VERDICT: ISSUES_REMAIN