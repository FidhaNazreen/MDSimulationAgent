# Round 2 counterreply

Thanks — this was substantive. Almost all of it lands. I'm accepting most points, defending two on user-pinned-scope grounds (with caveats), and asking for clarification on three. The updated v0 architecture is in Section 2 below; Section 3 re-asks for adversarial pushback on the revisions and the points I defended.

## Section 1 — Acknowledgments (per issue)

**Re your point 1** (PROPKA upstream + `pdb2gmx -ignh` downstream contradiction):
**Accept.** Concrete fix: protonation becomes a *topology-time* decision. `StructurePrep` now only *analyzes* protonation (records pKa predictions, HIS H-bond network, termini context) into `protonation_analysis.json`; it does not modify the structure. `Topology` consumes that analysis to drive `pdb2gmx` non-interactively via `--his`/explicit residue rename or a Python wrapper that pipes interactive answers, and records the *actual* decisions made by `pdb2gmx` into `protonation_decisions.json`. Drop `-ignh` from the default. Use it only when the input PDB has hydrogens incompatible with the chosen FF, and record that branch explicitly.

**Re your point 2** (PROPKA at pH 7 isn't enough; need residue-level decisions):
**Accept.** Adding the required `protonation_decisions.json` schema covering HIS/ASP/GLU/LYS/ARG/N-term/C-term. Fields per residue: `resid`, `chain`, `decision` (e.g. `HID|HIE|HIP`), `source` (`propka@pH7|manual_override|crystal_preserved|ff_default`), `evidence` (predicted pKa, H-bond donors/acceptors within 3.5 Å, χ angle for HIS), and `accepted_by` (`auto|user`).

**Re your point 3** (HIS handling under-specified, silent defaults in non-interactive `pdb2gmx`):
**Accept.** New rule: enumerate every HIS, auto-classify with explicit evidence (PROPKA pKa + H-bond network within 3.5 Å + nearby metal coordination if any), and in **non-interactive mode fail unless every HIS has a recorded decision** (from policy file or prior manifest). In interactive mode prompt per residue with the evidence shown.

**Re your point 4** (cleaning vs. chemically destructive changes conflated):
**Accept.** `StructurePrep` output now splits into `observations.json` (what was found) and `mutations.json` (what was changed — every deletion, altloc resolution, chain selection, water strip, residue rename). Mutations carry `(action, target_ids, reason, reversible_diff_or_undo_recipe)`.

**Re your point 5** (asymmetric unit vs biological assembly):
**Accept.** Adding a `structure_ingest_policy`. Defaults: for `tutorial_reproduction` mode use the deposited asymmetric unit (matches the canonical 1AKI tutorial); for `general_md_prep` mode detect available biological assemblies (PDB `REMARK 350`), and either prompt or apply a configured default (`asymmetric_unit | first_biological_assembly | largest_biological_assembly`). Record the chosen unit, model number, and chain selection in the manifest.

**Re your point 6** (altloc handling vague, conformer consistency):
**Accept.** Deterministic altloc policy: prefer highest-occupancy per residue; tie-break by lowest B-factor then alphabetical. **Refuse a run when conformer networks mix (a residue's chosen altloc is incompatible with a neighboring residue's chosen altloc by clash distance < 2.0 Å)** unless `altloc_policy: force_consistent_set | force_single_letter` is set in config. Record the selected letter per residue.

**Re your point 7** (crystallographic water policy too aggressive):
**Accept.** Two-mode behavior: in `tutorial_reproduction` mode strip all waters (matches tutorial). In `general_md_prep` mode classify waters by: (a) contact partner type (protein / ligand / metal), (b) burial (≤ 4 Å contacts in ≥ 3 directions), (c) B-factor percentile if available. High-confidence structural waters (buried + low B-factor + multiple partners) are preserved by default; surface waters are stripped; ambiguous cases prompt.

**Re your point 8** (no ligand/cofactor/metal parametrization boundary):
**Accept.** Adding `SystemClassifier` as a preflight phase that labels system type before `pdb2gmx` ever runs. Classes: `protein_only_soluble`, `protein_ligand`, `metalloprotein`, `nucleic_acid`, `membrane`, `glycoprotein`, `multimer`, `mixed`. v0 supports only `protein_only_soluble`; all others fail fast with a useful classification report. This is the gating step that prevents `pdb2gmx` from being asked to do the impossible.

**Re your point 9** (OPLS-AA/L + SPC is a tutorial profile, not a general default):
**Accept.** Renamed `tutorial_lysozyme_profile`. For `general_md_prep` mode there is no implicit default; the topology agent either reads the configured lab default profile or asks. If neither, the run fails preflight with a clear "no FF/water profile configured for general mode" error.

**Re your point 10** (FF/water compatibility as warning, not block):
**Accept.** Adding an FF/water allowlist matrix (e.g. CHARMM36 ↔ TIP3P/CHARMM-modified, AMBER99SB-ILDN ↔ TIP3P/TIP4P-Ew, OPLS-AA/L ↔ TIP3P/TIP4P, GROMOS54a7 ↔ SPC/SPC/E). Unsupported pairs are blocked unless `--allow-unsupported-ff-water` is explicitly set and that override is recorded in the manifest.

**Re your point 11** (membrane/nucleic-acid/etc are not "alternatives"):
**Accept.** v0 explicitly scoped to soluble protein-only systems (the `SystemClassifier` gate from point 8). All other classes fail fast in v0 with a classification report telling the user *why* it's unsupported, not just *that* it is.

**Re your point 12** (dodecahedron rationale missing):
**Accept.** Default dodecahedron only under the protein-globular profile (and recorded as such). For non-globular or anisotropic solutes (computed by gyration tensor inertia ratio thresholds) fall back to cubic. Manifest records: box type, vectors, minimum image distance, gyration ratios that drove the choice.

**Re your point 13** (padding tied to cutoff, not just `1.0 nm`):
**Accept.** Padding policy formalized: `padding >= max(1.0 nm, planned_cutoff + 0.2 nm, expected_expansion)`. If downstream `.mdp` (EM/NVT/NPT) parameters aren't yet known the agent uses 1.2 nm as a conservative default and emits a warning that the box may be re-built if the planned cutoff changes.

**Re your point 14** (ion strategy: "always ask" too noisy / too weak):
**Accept.** Introducing three interaction modes (applies system-wide, not just to ions):
- `interactive` — prompt for ambiguous choices, fall back to defaults if declined.
- `noninteractive-defaults` — never prompt; apply configured defaults; record `auto_choice` in manifest with reasoning.
- `strict-config-required` — refuse to run if any required choice is not in the config.
Ion-strategy defaults per mode: `interactive` asks neutralize-only vs. 150 mM; `noninteractive-defaults` neutralizes only (safer for free-energy compatibility); `strict-config-required` must specify `ion_strategy: {mode, salt_M, cation, anion, random_seed}`.

**Re your point 15** (ion model mismatch is a blocker):
**Accept.** Ion-parameter provenance is mandatory. The topology agent records: ion include source (`#include "amber99sb-ildn.ff/ions.itp"` etc.), ion residue names, charges, and whether the (FF, water, ion-set) triple is on the compatibility allowlist. Joung–Cheatham vs. default-GROMACS ions is a named, recorded choice. Triple-incompatible combinations are blocked unless overridden.

**Re your point 16** (`genion` group selection not robust):
**Accept.** Replacing free-form `genion` invocation with: (1) build a dedicated solvent index group via `gmx make_ndx` (or programmatically) containing only `SOL` residues, (2) pass it non-interactively via `-p` + index file, (3) diff `[ molecules ]` in `.top` before/after to verify exactly the expected number of `SOL` molecules were replaced by the expected `NA`/`CL` counts, and assert solvent uniformity (single residue type, expected molecule size).

**Re your point 17** (charge check tolerance alone is insufficient):
**Accept.** Four-stage charge accounting recorded in `solvation_report.json`:
1. `pre_ion_total_charge` (from `grompp` before genion),
2. `expected_ions` (derived from charge arithmetic + salt concentration),
3. `actual_inserted_ions` (counted from final `.top`),
4. `final_total_charge` (re-grompp'd). All four must agree within tolerance; mismatch = hard QC fail.

**Re your point 18** (atom-count band hand-wavy):
**Accept.** Expected solvent estimate from box volume: `N_water_expected ≈ ρ * (V_box - V_excluded)`, with `ρ = 33.3 nm⁻³` (≈ 55.5 mol/L), `V_excluded ≈ N_solute_atoms / ρ_protein` using a conservative `ρ_protein ≈ 30 atoms/nm³`. Tolerance ±10%. Separate check: topology `[ molecules ]` counts match coordinate residues exactly (hard fail).

**Re your point 19** (topology↔coordinate consistency missed):
**Accept — and this is the single biggest improvement.** Adding `grompp` as a validation step (with a placeholder zero-step `.mdp`) immediately after `Topology` *and* immediately after `Solvation`. Any `grompp` non-zero exit or any "Fatal error" / "Number of coordinates does not match" message = hard QC fail. This catches the silent corruption case where `.top` looks self-consistent but doesn't match `.gro`.

**Re your point 20** (v0 stops too early; "ready to minimize" can't be claimed):
**Partial accept / partial defend.** You're right that a system can be syntactically valid but physically broken, and "ready to minimize" is currently unearned. **Accept**: include `grompp + short steepest-descent EM` (≤ 1000 steps, F_tol = 1000 kJ/mol/nm) as the **final validation step** of v0 prep — explicitly framed as validation, not as a "simulation phase." **Defend**: the user pinned v0 scope to exclude minimization-as-deliverable; calling EM a *validation gate* keeps v0 honest about that boundary while satisfying your correctness concern. The `Report.readiness_status` (from your point 25) will key off whether EM converged. If EM diverges or atoms fly apart, readiness is `blocked`, not `ready`.

**Re your point 21** (QC overloaded and incomplete):
**Accept.** QC becomes the *verdict layer only*. Beneath it: `StructureValidator`, `TopologyValidator`, `SolvationValidator`, `ProvenanceValidator`, `EMValidator`. These are not user-facing skills; they're called by the QC agent. Each emits a structured pass/fail with reasons.

**Re your point 22** (Visualization should not live inside QC):
**Accept.** Visualization stays distinct. Removing the "should it live inside QC?" question — settled. QC may *reference* visualization artifacts in its report when present, but visualization is never required for correctness.

**Re your point 23** (up-front ask breaks scripted runs):
**Accept.** Visualization respects the interaction-mode contract from point 14. Config keys: `visualization: {mode: disabled|default|requested, viewer: vmd|pymol|nglview|auto, checkpoints: [prep, solvated, neutralized, all], render: png|state_only|both}`. Only ask in `interactive` mode when key is unset; in `noninteractive-defaults` skip with `skipped: no_user_opt_in` recorded; in `strict-config-required` refuse to start until set.

**Re your point 24** (VMD headless rendering optimistic):
**Accept.** Treat rendering as best-effort. Probe sequence: (1) check executable on PATH, (2) probe `-dispdev text` with a 1-frame test scene that renders a single sphere, (3) verify the PNG was written and is non-zero. If any probe fails, write the Tcl/PML *scripts* (so the user can render later if they install Tachyon/X11/etc.) and mark images as `skipped: renderer_unavailable` with the failure reason.

**Re your point 25** (report overstates readiness):
**Accept.** Adding top-level `readiness_status: ready | ready_with_warnings | blocked | not_validated`. The status is derived from the QC verdict tree: `ready` ⇔ all hard validators passed + EM converged; `ready_with_warnings` ⇔ all hard validators passed + soft warnings; `blocked` ⇔ any hard validator failed; `not_validated` ⇔ EM was skipped or didn't run. Report title and final line both surface this value.

**Re your point 26** (single mutable manifest weak):
**Accept.** Manifest model becomes: per-step immutable `step_NN_<agent>/step_report.json` files (write to temp + atomic rename), plus an `index.json` at the run root that lists step status, ordering, and content hashes of every artifact. The orchestrator only appends to `index.json` via temp+rename; agents never write to it. Crash recovery: scan step dirs, rebuild index from on-disk truth.

**Re your point 27** (no manifest schema versioning):
**Accept.** Every JSON artifact (step reports, manifest index, qc reports, etc.) gets `schema_version: "0.1.0"` and is validated at write and at read. Schemas live in `schemas/v0.1.0/*.schema.json`. Unknown required fields = fail fast.

**Re your point 28** (retry policy dangerous):
**Accept.** Retry classification: only retry transient *executor* failures (process killed by signal, executor lost connection to remote, IO error not attributable to inputs). Never retry deterministic chemistry/topology errors (`pdb2gmx` fatal error, `grompp` topology mismatch, `genion` group failure) — these require an input change. Retry attempts are recorded as separate immutable step files (`step_03_solvation/attempt_01_*.json`, `attempt_02_*.json`) so history is preserved.

**Re your point 29** (executor too `subprocess.run`-shaped):
**Accept.** New executor interface:
```python
class Executor:
    def submit(self, task: Task) -> JobHandle
    def wait(self, handle: JobHandle, timeout: float | None = None) -> JobStatus
    def collect(self, handle: JobHandle) -> ExecutionResult
    def run_sync(self, task: Task, timeout: float | None = None) -> ExecutionResult  # convenience: submit + wait + collect
    def stage_in(self, paths: list[Artifact]) -> dict[Artifact, RemoteArtifact]
    def stage_out(self, handles: list[RemoteArtifact]) -> dict[RemoteArtifact, Artifact]
```
`Task` carries argv, env, resource request, walltime, container image (optional). `ExecutionResult` carries `exit_status`, `stdout_path`, `stderr_path`, `host`, `wall_time`, `resources_used`, `scheduler_metadata`. `LocalExecutor` implements all of this trivially (submit ≡ Popen, wait ≡ wait, collect ≡ read paths). `RemoteExecutor` (v1+) wraps SLURM/cloud.

**Re your point 30** (paths and staging):
**Accept.** Introducing `Artifact` (a URI-like handle: `local://...`, `slurm-scratch://job_id/...`, `s3://...`) that agents pass around. Local paths only appear at the orchestration boundary, when an agent has to invoke a process. Stage-in/out resolve `Artifact` ↔ filesystem path on whichever host the executor runs on.

**Re your point 31** (environment capture insufficient):
**Accept.** Provenance is now a mandatory orchestrator responsibility, not an optional separate agent. Captured at run start and on every executor invocation: GROMACS version + build options (from `gmx -version`), `GMXLIB`, FF directory path + recursive content hashes of the FF files actually loaded (parsed from `pdb2gmx`/`grompp` stdout), executor identity, host, container image digest if applicable. Lives in `provenance.json` at the run root.

**Re your point 32** (DAG hides preflight):
**Accept.** Adding `Preflight` as the first phase (before `SystemClassifier`, which runs second). Preflight checks: GROMACS available + version ≥ configured min, PROPKA available (or marked unavailable), VMD/PyMOL/NGLview availability for viz config, writable run dir, config completeness for the selected interaction mode, disk space estimate. Hard fail surfaces before any structure is touched.

**Re your point 33** (`md:prep-structure` alone is a trap):
**Accept.** `md:prep-structure` accepts an optional `target_profile` parameter; if set, prep-time decisions consider the downstream FF/water (e.g. altloc letters compatible with FF residue templates). If unset, the skill emits a warning at completion: "topology compatibility is unvalidated until `md:build-topology` runs."

**Re your point 34** (internal FF planning vs. external skill):
**Accept.** FF selection is an internal planning sub-phase of `md:build-topology` that emits `topology_plan.json` (containing chosen FF, water model, ion set, termini policy, with full reasoning) *before* any `pdb2gmx` invocation. The plan is durable and re-readable. Externally there's still one `md:build-topology` skill — users don't pick FF separately as a skill action.

**Re your point 35** (1AKI is too friendly a benchmark):
**Accept.** Adding an **adversarial fixture set** to the v0 test suite: (a) protein with altloc mixing, (b) protein with missing loop + missing backbone atoms, (c) protein + ligand HETATM with no parameters available, (d) metalloprotein (e.g. with a Zn²⁺), (e) nucleic acid (DNA hairpin), (f) multimer where biological assembly differs from asymmetric unit, (g) protein with a nonstandard residue (e.g. selenomethionine), (h) protein with retained crystallographic waters, (i) topology with deliberate `.top`/`.gro` molecule count mismatch. Each fixture has an expected outcome (success / classified-unsupported / specific-error-message). v0 passes only if all expected outcomes hit.

**Re your point 36** (tutorial as ground truth vs. workflow reference):
**Accept.** Two modes formalized: `tutorial_reproduction` (judged by step-by-step command-and-output match with the GROMACS lysozyme tutorial — workflow reproducibility), and `general_md_prep` (judged by chemical/topological correctness against the validator suite — *not* against tutorial commands). Acceptance criteria are separate per mode.

**Re your point 37** ("one-line tradeoffs" too shallow):
**Accept.** Each user-facing choice now carries a structured `choice_specification.json`:
```
{
  "choice_id": "force_field",
  "default": "OPLS-AA/L",
  "applicability": ["protein_only_soluble"],
  "unsupported": ["nucleic_acid", "membrane", "glycoprotein"],
  "alternatives": [{"id": "CHARMM36", "when": "...", "consequence": "..."}, ...],
  "consequence_summary": "Choosing FF determines water-model allowlist, ion parameters, and validation expectations.",
  "decision_recorded_in": "topology_plan.json"
}
```
The exact prompt presented to the user and the exact response are recorded in the manifest (`prompt_text`, `response_text`, `timestamp`).

**Re your point 38** (no explicit run-resume model):
**Accept.** Step status state machine: `planned | running | succeeded | failed | skipped | invalidated`. Transitions: `planned → running → (succeeded | failed)`; `succeeded → invalidated` only on explicit user intervention; `failed → planned` only via `--retry-step N` which writes a new attempt under the same step dir. Resume: orchestrator reads `index.json` step states, restarts at the first non-`succeeded` step. Refuses to overwrite a `succeeded` step unless `--force-new-step` is passed.

**Re your point 39** (report depends on stale fields):
**Accept.** Report regenerates from on-disk truth at write time: reads final artifacts directly (`.top`, `.gro`), reads per-step immutable `step_report.json` files, verifies each artifact's content hash against the manifest index, and fails to produce a report (returning `not_validated`) if any hash mismatches.

**Re your point 40** (no v0 acceptance criteria):
**Accept.** v0 acceptance criteria (all must pass):
1. `tutorial_reproduction` mode on 1AKI produces a `.gro`+`.top`+`grompp`-clean+EM-converged system whose force field, water model, ion counts, and final residue counts match the canonical tutorial outputs exactly.
2. Non-interactive run (`noninteractive-defaults` mode) on 1AKI with all required config supplied — completes without prompting.
3. Interactive run on 1AKI — prompts for the documented user-choice points; defaults can be accepted with Enter.
4. Run on the protein+ligand fixture — fails at `SystemClassifier` with class `protein_ligand`, exit code documented.
5. Resume after simulated crash mid-`Solvation` (kill process, restart) — picks up at solvation, completes correctly.
6. Manifest JSON schema validation passes for all written artifacts.
7. `grompp` validation passes at end of `Topology` and end of `Solvation`.
8. Final short EM converges (`fmax < 1000 kJ/mol/nm`) on the 1AKI system.

## Section 2 — Updated artifact

**Summary of changes from R1:**
- v0 scope expanded by one step: `grompp` validation + short steepest-descent EM as the final validation gate (per points 19, 20).
- New agents: `Preflight`, `SystemClassifier`. v0 now scoped strictly to `protein_only_soluble`.
- New modes: interaction modes (`interactive | noninteractive-defaults | strict-config-required`) and pipeline modes (`tutorial_reproduction | general_md_prep`).
- Protonation moved from `StructurePrep` (analysis only) to `Topology` (decision + execution).
- QC restructured: verdict layer + named validators (`StructureValidator`, `TopologyValidator`, `SolvationValidator`, `ProvenanceValidator`, `EMValidator`).
- Manifest model: immutable per-step files + `index.json` with hashes + schema versioning.
- Executor abstraction redesigned: `submit/wait/collect/run_sync` + structured `Task`/`ExecutionResult` + `Artifact` URI handles.
- Step status state machine + resume-after-crash semantics.
- Provenance is mandatory orchestrator behavior, not an optional add-on.
- v0 acceptance criteria pinned (8 concrete tests) and adversarial fixture set added.
- Report exposes `readiness_status: ready | ready_with_warnings | blocked | not_validated`, regenerated from on-disk truth at write time.

### 2.1 Pipeline DAG (v0)

```
Preflight → SystemClassifier → StructurePrep → [StructureValidator]
         → Topology (FF planning + pdb2gmx) → [TopologyValidator + grompp gate]
         → Solvation (box + solvate + ions) → [SolvationValidator + grompp gate]
         → ShortEM (≤1000 steps SD) → [EMValidator]
         → Visualization (optional, mode-gated)
         → Report
```

QC is invoked between each pair of arrows (verdict layer; validators in brackets are its inputs). Provenance collection wraps every executor call.

### 2.2 Agent roster (v0, revised)

- **`Preflight`** — tool/version availability, writable run dir, viewer probe, config completeness check (mode-aware), disk space estimate.
- **`SystemClassifier`** — labels structure as `protein_only_soluble | protein_ligand | metalloprotein | nucleic_acid | membrane | glycoprotein | multimer | mixed`. In v0, only `protein_only_soluble` proceeds; everything else fails fast with a classification report.
- **`StructurePrep`** — fetch + analyze + record. Splits output into `observations.json` (what was found) and `mutations.json` (what was changed). Analyzes protonation (`protonation_analysis.json`) but does **not** modify hydrogens; analyzes crystallographic waters (`water_classification.json`); resolves altlocs deterministically with conformer-consistency checks.
- **`Topology`** — internal FF-planning phase emits `topology_plan.json`; then `pdb2gmx` runs non-interactively with explicit HIS / termini / FF / water choices; protonation decisions are recorded in `protonation_decisions.json`; ion include source recorded in `topology_plan.json`. Validates against FF/water allowlist matrix.
- **`Solvation`** — `editconf` with shape policy (dodecahedron under globular profile, cubic fallback), padding `>= max(1.0, cutoff+0.2, expected_expansion) nm`, `solvate`, then `genion` with explicit solvent index group and four-stage charge accounting.
- **`ShortEM`** (validation gate, not a "simulation phase") — `grompp` + ≤1000-step steepest-descent EM. Convergence target `fmax < 1000 kJ/mol/nm`. Output feeds `readiness_status`.
- **`QC`** — verdict layer. Composes: `StructureValidator`, `TopologyValidator`, `SolvationValidator`, `EMValidator`, `ProvenanceValidator`. Each validator emits structured pass/fail.
- **`Visualization`** — distinct from QC. Mode-gated (`disabled | default | requested`), viewer-detection + best-effort probe (executable + test render + non-zero PNG), writes scripts even if rendering fails. Checkpoints per config: `prep | solvated | neutralized | em | all`.
- **`Report`** — regenerated from on-disk truth at write time; verifies artifact hashes against manifest index before claiming any field; surfaces `readiness_status` in title and final line.

Provenance collection is **not** a separate agent — it's an orchestrator responsibility that wraps every executor invocation.

### 2.3 Skill boundary map (revised)

| Skill | Wraps | Notes |
|---|---|---|
| `md:prep-structure` | `Preflight` + `SystemClassifier` + `StructurePrep` + `StructureValidator` | Accepts optional `target_profile`; warns about topology-unvalidated state if used standalone. |
| `md:build-topology` | `Topology` (FF planning + `pdb2gmx`) + `TopologyValidator` + `grompp` gate | FF selection is an internal planning sub-phase that emits `topology_plan.json`. |
| `md:solvate-system` | `Solvation` + `SolvationValidator` + `grompp` gate | Implements four-stage charge accounting. |
| `md:validate-system` | `ShortEM` + `EMValidator` | The "is this physically buildable?" gate. May be merged into `md:solvate-system`; see Section 3. |
| `md:visualize` | `Visualization` | Mode-gated; respects interaction mode contract. |
| `md:run-workflow` | `Orchestrator` (composes all above) | Single user-facing entry point for end-to-end runs. |

User-surfaced decisions (presented via `choice_specification.json`):
- Force field & water model — in `general_md_prep` mode always; in `tutorial_reproduction` mode locked to OPLS-AA/L + SPC.
- Ion strategy — `interactive` asks; `noninteractive-defaults` neutralize-only; `strict-config-required` must specify.
- Visualization — only `interactive` asks if unset.
- Altloc tie-breaking, biological-assembly selection — mode-dependent (defaults in `tutorial_reproduction`, surfaced in `general_md_prep`).

Internal decisions with manifest-recorded defaults:
- Box geometry (dodecahedron under globular profile, cubic otherwise).
- Padding (formula above).
- Water disposition in `tutorial_reproduction` mode (strip all); in `general_md_prep` mode (classify + preserve high-confidence structural).

### 2.4 State & handoff model

```
<runs_root>/<run_id>/
├── index.json                    # step ordering + status state machine + content hashes (append via temp+rename only)
├── provenance.json               # GROMACS version, FF hashes, host, container digest, executor identity
├── schemas/v0.1.0/               # JSON schemas referenced by every artifact
├── step_00_preflight/
│   └── step_report.json
├── step_01_classifier/
│   └── step_report.json
├── step_02_structure_prep/
│   ├── 1aki_clean.pdb
│   ├── observations.json
│   ├── mutations.json
│   ├── protonation_analysis.json
│   ├── water_classification.json
│   └── step_report.json
├── step_03_topology/
│   ├── topology_plan.json
│   ├── protonation_decisions.json
│   ├── system.gro
│   ├── system.top
│   ├── posre.itp
│   ├── grompp_validation.log
│   └── step_report.json
├── step_04_solvation/
│   ├── system_solvated.gro
│   ├── system_neutralized.gro
│   ├── system.top
│   ├── charge_accounting.json   # 4-stage record
│   ├── ion_index.ndx
│   ├── grompp_validation.log
│   └── step_report.json
├── step_05_em/
│   ├── em.mdp
│   ├── em.gro
│   ├── em.log
│   └── step_report.json
├── qc/
│   ├── structure_validator.json
│   ├── topology_validator.json
│   ├── solvation_validator.json
│   ├── em_validator.json
│   └── provenance_validator.json
├── visualization/                # only if user opted in
│   ├── prep.png
│   ├── solvated.png
│   ├── em.png
│   ├── visualize.vmd
│   └── render_probe.json         # records whether rendering actually worked
└── REPORT.md                     # with readiness_status header
```

Every JSON file carries `schema_version: "0.1.0"`. Every artifact has a SHA-256 hash recorded in `index.json`. `index.json` is the only mutable file at the run root and is updated only via temp+rename.

Retry attempts are preserved: `step_04_solvation/attempt_01_*.json`, `attempt_02_*.json`. The "current" step report is `attempt_<N>_step_report.json` symlinked or referenced from `index.json`.

### 2.5 Executor abstraction (revised)

```python
@dataclass
class Task:
    argv: list[str]
    env: dict[str, str]
    stdin: bytes | None
    resources: ResourceRequest      # cpus, mem_gb, gpu, walltime
    container_image: str | None
    artifacts_in: list[Artifact]
    artifacts_out: list[str]        # relative paths the task is expected to produce

@dataclass
class ExecutionResult:
    exit_status: int
    stdout_path: Artifact
    stderr_path: Artifact
    host: str
    wall_time_s: float
    resources_used: ResourceUsage
    scheduler_metadata: dict        # SLURM job id, etc. — empty for local
    artifacts_out: dict[str, Artifact]

class Executor(Protocol):
    def submit(self, task: Task) -> JobHandle: ...
    def wait(self, handle: JobHandle, timeout: float | None = None) -> JobStatus: ...
    def collect(self, handle: JobHandle) -> ExecutionResult: ...
    def run_sync(self, task: Task, timeout: float | None = None) -> ExecutionResult: ...
    def stage_in(self, paths: list[Artifact]) -> dict[Artifact, Artifact]: ...
    def stage_out(self, handles: list[Artifact]) -> dict[Artifact, Artifact]: ...
```

`LocalExecutor`: `submit ≡ Popen`, `wait ≡ wait`, `collect ≡ read files`, `stage_*` ≡ identity. `RemoteExecutor` (v1+): SLURM/cloud-backed; not implemented in v0. The interface ships in v0 even though only the local impl is wired.

### 2.6 v0 acceptance criteria (the 8 tests from point 40)

(Reproduced for cross-reference; this is the test contract that closes "validate orchestration" properly.)

1. `tutorial_reproduction` on 1AKI matches canonical tutorial outputs (FF, water, ion counts, residue counts).
2. Non-interactive (`noninteractive-defaults`) run on 1AKI with config supplied — no prompts, completes.
3. Interactive run on 1AKI — prompts at documented decision points; defaults Enter-acceptable.
4. Protein+ligand fixture — fails at `SystemClassifier` with class `protein_ligand`.
5. Resume after simulated crash mid-`Solvation` — picks up correctly.
6. All artifacts pass schema validation.
7. `grompp` gate passes at end of `Topology` and end of `Solvation`.
8. Short EM converges (`fmax < 1000 kJ/mol/nm`).

### 2.7 Adversarial fixtures (from point 35)

(a) altloc-mixed protein, (b) missing-loop/missing-backbone protein, (c) protein+ligand with no params, (d) metalloprotein (Zn²⁺), (e) nucleic acid (DNA hairpin), (f) multimer (asymmetric unit ≠ biological assembly), (g) selenomethionine, (h) retained crystallographic waters, (i) deliberate `.top`/`.gro` molecule mismatch. Each has a documented expected outcome (success vs. classified-unsupported vs. specific-error).

## Section 3 — Continued critique prompt

Review the updated plan and my responses to your earlier issues. Push back on responses where I defended poorly — name which point. Raise any new issues the updated plan creates. Re-issue any earlier issue you don't think I addressed. Same numbered format and same verdict line at the end:

  VERDICT: APPROVED
  VERDICT: ISSUES_REMAIN

Additionally, I have **three clarification questions** for you — answer them inline before/within your next critique:

**C1.** On the `tutorial_reproduction` vs. `general_md_prep` split (your points 9, 36): is this a *runtime mode* (user picks at run start), or a *profile* the topology agent reads, or both? I treated it as a runtime mode in the revision; push back if that's the wrong layer.

**C2.** On point 20 (EM in v0): I defended including EM only as a "validation gate," not as a "simulation phase," to honor the user's pinned v0 scope. Is that distinction meaningful, or am I papering over a real boundary violation? If the latter, propose where the boundary should sit.

**C3.** On the skill granularity (points 33, 34): I kept `md:validate-system` as a separate skill exposing `ShortEM + EMValidator`. Should it instead be folded into `md:solvate-system` (since you can't trust solvation output without EM validation anyway)? Or further: should there be no `md:validate-system` as a user-facing skill at all, since validation should be implicit in every upstream skill?
