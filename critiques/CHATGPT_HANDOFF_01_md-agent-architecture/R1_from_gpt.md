1. **WHAT:** `StructurePrep` says it chooses protonation, but `Topology` then runs `pdb2gmx -ignh`.
   **WHY:** `-ignh` discards input hydrogens, so any PROPKA-driven protonation/histidine work done upstream can be thrown away. Your manifest can claim one protonation policy while the topology encodes another.
   **WHAT TO DO:** Make protonation a topology-time decision. Either feed `pdb2gmx` explicit residue names/interactive choices, or preserve hydrogens and prove the force-field atom names match. Record the actual `pdb2gmx` choices, not just the intended policy.

2. **WHAT:** “PROPKA at pH 7 if available, else default protonation states” is not enough.
   **WHY:** PROPKA predicts pKa shifts, but GROMACS topology generation still needs discrete residue/tautomer choices. Histidine is the obvious failure case: HID/HIE/HIP-style choices are structure- and H-bond-network-dependent.
   **WHAT TO DO:** Add a required `protonation_decisions.json` containing residue-level choices for HIS/ASP/GLU/LYS/ARG/termini, source of decision, pH, tool version, and whether the user accepted or overrode them.

3. **WHAT:** Histidine handling is under-specified.
   **WHY:** `pdb2gmx` can make/ask histidine choices, but unattended CLI execution can silently choose defaults or hang depending on flags. Wrong HIS tautomer can change local H-bonding and active-site chemistry.
   **WHAT TO DO:** Detect all HIS residues before topology. For each, either auto-classify with explicit evidence or force a user decision in interactive mode. In non-interactive mode, fail unless policy is configured.

4. **WHAT:** `StructurePrep` conflates “cleaning” with chemically destructive decisions.
   **WHY:** Stripping waters, deleting ligands, resolving altlocs, choosing assemblies, and changing protonation are not mere cleanup. They change the simulated system.
   **WHAT TO DO:** Split the report into `observations` and `mutations`. Every deletion or chemical reinterpretation should be explicit, reversible, and linked to residue/atom IDs.

5. **WHAT:** PDB ID fetch is underspecified: asymmetric unit vs biological assembly.
   **WHY:** RCSB entries may contain asymmetric units, biological assemblies, multiple models, ligands, crystallographic additives, and chain copies. Picking the wrong unit can simulate the wrong system.
   **WHAT TO DO:** Add a structure-ingest policy: default to deposited asymmetric unit for tutorial reproducibility, but detect available biological assemblies and record the chosen assembly/model.

6. **WHAT:** Altloc handling is dangerously vague.
   **WHY:** Choosing altloc A blindly can create steric clashes, break ligand contacts, or mix incompatible conformers across residues.
   **WHAT TO DO:** Implement a deterministic altloc policy: prefer highest occupancy, maintain conformer consistency where possible, fail on ties or mixed networks unless configured.

7. **WHAT:** Crystallographic water policy is too aggressive.
   **WHY:** “Strip by default, list waters within 4 Å” is a post-hoc apology, not a decision rule. Bridging waters, catalytic waters, metal-coordinating waters, and ligand-interface waters can matter.
   **WHAT TO DO:** For pure lysozyme tutorial mode, strip all waters. For general mode, classify waters by protein/ligand/metal contacts, occupancy/B-factor if available, and conservation if known; ask or preserve high-confidence structural waters.

8. **WHAT:** There is no ligand/cofactor/metal parametrization boundary.
   **WHY:** `pdb2gmx` will not magically parameterize arbitrary HETATM residues. Refusing is acceptable for v0, but the architecture must represent this as a first-class unsupported case, not an incidental topology failure.
   **WHAT TO DO:** Add a `SystemClassifier` or preflight phase that labels system type: protein-only, protein+ligand, metalloprotein, nucleic acid, membrane, glycan, multimer. Gate the workflow before `pdb2gmx`.

9. **WHAT:** OPLS-AA/L + SPC is fine only as a tutorial profile, not a general v0 default.
   **WHY:** For proteins it reproduces the canonical lysozyme tutorial, but for membranes, nucleic acids, ligands, cofactors, glycans, or modern protein workflows it is not a defensible universal default.
   **WHAT TO DO:** Rename it `tutorial_lysozyme_profile`. For general protein-only prep, make FF/water selection explicit or use a configurable lab default.

10. **WHAT:** Force-field/water compatibility is treated as a one-line warning.
    **WHY:** Bad FF/water pairing is not cosmetic; it changes nonbonded balance and may invalidate the system.
    **WHAT TO DO:** Maintain an allowlist matrix of supported FF/water combinations. Block unsupported combinations unless the user explicitly overrides.

11. **WHAT:** Membrane, nucleic-acid, glycoprotein, and ligand systems are not just “alternatives.”
    **WHY:** They need different builders, force fields, ions, waters, boxes, restraints, and validation. The current agents would produce plausible-looking garbage or fail late.
    **WHAT TO DO:** In v0, explicitly scope to soluble protein-only systems accepted by `pdb2gmx`. Fail fast for everything else with a useful classification report.

12. **WHAT:** Box default is defensible for lysozyme, but the rationale is missing.
    **WHY:** Dodecahedron reduces solvent count for roughly globular solutes; GROMACS docs note rhombic dodecahedron/truncated octahedron are better suited to approximately spherical macromolecules and use less volume than cubic boxes. But newcomers may find non-orthogonal boxes confusing.
    **WHAT TO DO:** Default to dodecahedron only under the tutorial/protein-globular profile. Record box vectors and minimum image distance. Offer cubic as “more inspectable, more atoms.”

13. **WHAT:** Padding policy ignores nonbonded cutoff and planned simulation parameters.
    **WHY:** `-d 1.0` is only meaningful relative to cutoff, PME, expected conformational expansion, and whether the solute is compact. Too-small padding creates self-interaction artifacts.
    **WHAT TO DO:** Tie padding to planned `.mdp` nonbonded settings or require `padding >= max(1.0 nm, cutoff margin policy)`. Warn if future EM/MD settings are unknown.

14. **WHAT:** Ion strategy “always ask” is too noisy for automated mode and too weak for expert mode.
    **WHY:** Scripts need deterministic behavior; experts need ion model, salt identity, concentration, neutralization order, and random seed control.
    **WHAT TO DO:** Define interaction modes: `interactive`, `noninteractive-defaults`, `strict-config-required`. In noninteractive mode, use manifest-configured defaults and never prompt.

15. **WHAT:** Ion model mismatch is a blocker.
    **WHY:** Ion parameters are force-field/water-model-dependent. Randomly using whatever GROMACS includes can produce inconsistent Na/Cl behavior.
    **WHAT TO DO:** Add ion-parameter provenance and compatibility checks. At minimum, record ion include source, names, charges, FF directory, and whether the selected pair is recommended for the FF/water model.

16. **WHAT:** `genion` group selection is not robust.
    **WHY:** `genion` replaces solvent molecules; the selected group must be continuous solvent of identical molecule size per GROMACS documentation. Picking the wrong group can fail or corrupt topology/coordinates.
    **WHAT TO DO:** Generate an index group specifically for solvent, pass it non-interactively, verify molecule count changes, and diff `[ molecules ]` before/after.

17. **WHAT:** Net charge check `|q| < 1e-3 e` is oddly framed.
    **WHY:** GROMACS charges should usually sum to near an integer before ionization and near zero after neutralization. A tolerance alone does not catch “wrong integer charge neutralized with wrong ions.”
    **WHAT TO DO:** Record pre-ion total charge from `grompp`, expected ions from charge arithmetic, actual inserted ions, and final charge. Check all four.

18. **WHAT:** “Atom count within expected band” is currently hand-wavy.
    **WHY:** Without a real formula, the check will either overfit 1AKI or pass nonsense boxes.
    **WHAT TO DO:** Compute expected solvent from box volume using water number density around 33.3 molecules/nm³, subtract a conservative excluded-volume estimate, then use a broad tolerance. Also verify topology molecule counts match coordinate residues exactly.

19. **WHAT:** QC misses topology-coordinate consistency.
    **WHY:** A `.top` can reference files successfully while molecule counts still disagree with `.gro`. That failure often appears later at `grompp`, not at file-existence checks.
    **WHAT TO DO:** Run `gmx grompp` as a validation step after topology and after solvation/ions. Treat coordinate/topology mismatch as hard fail.

20. **WHAT:** v0 stopping before energy minimization is the wrong boundary.
    **WHY:** A solvated neutralized system can be syntactically valid but physically broken: clashes, bad contacts, bad protonation, overlapping ions, broken ligands. EM is the first practical sanity check.
    **WHAT TO DO:** Include at least `grompp + short steepest-descent EM` in v0, even if production MD is out of scope. Otherwise “ready to minimize” is not earned.

21. **WHAT:** `QC` is overloaded and still incomplete.
    **WHY:** It is asked to parse chemistry, logs, topology, geometry, and provenance. That makes silent gaps likely.
    **WHAT TO DO:** Keep `QC` as the verdict layer, but add concrete validators: structure validator, topology validator, solvation validator, provenance validator. They do not need to be user-facing skills.

22. **WHAT:** Visualization should not live inside `QC`.
    **WHY:** Rendering is optional observability; QC must be deterministic and machine-verifiable. A visual snapshot can support review, but it should not be required for correctness.
    **WHAT TO DO:** Keep `Visualization` distinct. Let QC optionally reference visualization artifacts, but do not make viewer availability a QC dependency.

23. **WHAT:** “Ask visualization up-front exactly once” breaks scripted runs unless there is a noninteractive contract.
    **WHY:** CI, batch prep, and remote execution cannot tolerate surprise prompts.
    **WHAT TO DO:** Add `visualization: disabled|default|requested` in config. If omitted in interactive mode, ask once. If omitted in noninteractive mode, skip and record `skipped: no_user_opt_in`.

24. **WHAT:** VMD headless rendering is optimistic.
    **WHY:** VMD installation, display backends, Tachyon availability, font/render paths, and macOS GUI constraints are not guaranteed. “Text mode” does not automatically mean PNG rendering works.
    **WHAT TO DO:** Treat rendering as best-effort. Probe executable and render capability with a tiny test scene. If unavailable, write scripts only and mark images skipped.

25. **WHAT:** Report can easily overstate readiness.
    **WHY:** “Ready to minimize” after soft failures, unsupported chemistry, or skipped validation is misleading.
    **WHAT TO DO:** Add a top-level `readiness_status`: `ready`, `ready_with_warnings`, `blocked`, `not_validated`. The report title and final line must use that value.

26. **WHAT:** Single mutable `manifest.json` is a weak source of truth.
    **WHY:** Partial writes, retries, concurrent agents, and crash recovery can corrupt or blur history.
    **WHAT TO DO:** Use immutable event files or per-step manifests plus an index. Write temp files and atomic rename. Include content hashes for every artifact.

27. **WHAT:** The manifest does not specify schema/versioning.
    **WHY:** Agents and reports will drift. Old runs become unreadable or misinterpreted.
    **WHAT TO DO:** Define JSON schemas with `schema_version`, validate at every handoff, and fail fast on unknown required fields.

28. **WHAT:** Retry policy is dangerous.
    **WHY:** Retrying `pdb2gmx`, `grompp`, or `genion` without classifying the failure can overwrite useful artifacts or hide deterministic chemistry errors.
    **WHAT TO DO:** Retry only transient executor failures. Do not retry chemical/topological failures unless an explicit remediation changed inputs.

29. **WHAT:** Executor abstraction is too `subprocess.run`-shaped.
    **WHY:** Remote jobs are asynchronous, have scheduler IDs, staging directories, environment modules, walltime, resource requests, logs, and failure states. `CompletedProcess` is local-centric.
    **WHAT TO DO:** Split `submit`, `wait`, `collect`, and `run_sync` convenience methods. Return a structured `ExecutionResult` with stdout/stderr paths, exit status, host, runtime, resources, and scheduler metadata.

30. **WHAT:** `cwd: str` and `stage_in/out` identity mapping are not enough.
    **WHY:** Remote paths, object stores, containers, and HPC scratch directories are not interchangeable with local strings.
    **WHAT TO DO:** Introduce artifact handles or URI-like paths. Keep local paths at the orchestration boundary, not inside agent logic.

31. **WHAT:** Environment capture is insufficient.
    **WHY:** Reproducibility depends on GROMACS version, build options, FFT/MPI/GPU support, force-field directory contents, `GMXLIB`, executable path, and sometimes container image.
    **WHAT TO DO:** Add provenance collection as mandatory orchestrator behavior, not a separate optional agent. Hash FF files actually used.

32. **WHAT:** The DAG hides preflight checks.
    **WHY:** You discover missing GROMACS, PROPKA, VMD, force fields, or unsupported residue types mid-run.
    **WHAT TO DO:** Add `Preflight` before `StructurePrep`: tool availability, versions, writable run dir, viewer capability, supported system class, config completeness.

33. **WHAT:** Skill granularity is mostly right, but `md:prep-structure` alone is a trap.
    **WHY:** A “cleaned PDB” is not necessarily meaningful without knowing the target force field and topology constraints.
    **WHAT TO DO:** Keep separate skills for power users, but make `md:prep-structure` accept an optional target FF/profile and warn that topology compatibility is unvalidated until `md:build-topology`.

34. **WHAT:** Splitting FF-selection from `pdb2gmx` would be overkill as a user-facing skill but useful internally.
    **WHY:** Users think in “build topology,” but the system needs a durable decision record before execution.
    **WHAT TO DO:** Implement FF selection as an internal planning phase that produces `topology_plan.json`; keep one external `md:build-topology` skill.

35. **WHAT:** The v0 benchmark can pass while the architecture fails real prep.
    **WHY:** 1AKI is unusually friendly: soluble protein, known tutorial, no ligand parametrization. It will not exercise the worst failure modes.
    **WHAT TO DO:** Add adversarial fixtures: altloc protein, missing loop/backbone, ligand, metal, nucleic acid, multimer, nonstandard residue, retained waters, and bad topology/coordinate mismatch.

36. **WHAT:** You cite the tutorial as a “ground truth,” but it is only a workflow reference.
    **WHY:** Matching tutorial commands does not prove chemically correct decisions; it proves tutorial reproducibility.
    **WHAT TO DO:** Define two modes: `tutorial_reproduction` and `general_md_prep`. Judge them with different acceptance criteria.

37. **WHAT:** “Surface alternatives with one-line tradeoffs” is too shallow for blocking scientific choices.
    **WHY:** FF/water/protonation/ions are not UI preferences. Bad defaults can invalidate conclusions.
    **WHAT TO DO:** For each user-facing choice, include default, applicability, unsupported cases, and consequence. Store the exact prompt/answer in manifest.

38. **WHAT:** There is no explicit run-resume model.
    **WHY:** Directory-rooted artifacts invite resume/retry, but mutable outputs and single manifest make it unclear whether a run is fresh, resumed, or contaminated.
    **WHAT TO DO:** Add step status states: `planned`, `running`, `succeeded`, `failed`, `skipped`, `invalidated`. Refuse to overwrite succeeded steps unless `--force-new-step`.

39. **WHAT:** The report depends on stale fields unless it recomputes.
    **WHY:** If `system.top` changes after report fields are written, the report lies.
    **WHAT TO DO:** Report should read final artifacts and per-step immutable reports, verify hashes against manifest, and fail if mismatched.

40. **WHAT:** The current architecture does not define acceptance criteria for v0.
    **WHY:** Without concrete pass/fail tests, “validate orchestration” is vague.
    **WHAT TO DO:** Require: reproducible 1AKI tutorial prep, noninteractive run, interactive run, forced failure on ligand system, resume after crash, manifest schema validation, topology-coordinate `grompp` pass, final EM pass.

VERDICT: ISSUES_REMAIN