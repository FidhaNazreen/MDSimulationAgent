# Round 1 handoff: adversarial review of an agentic MD-simulation system design

---

## Section 1 — Context bundle

### What we are building

An **agentic system for molecular dynamics (MD) simulation** that a user can drive in natural language ("set up lysozyme in water and get me a system ready to minimize") and have a set of specialized sub-agents take over the multi-step CLI-heavy workflow. The long-term deliverable is a set of **Claude skills** — `md:prep-structure`, `md:build-topology`, `md:solvate-system`, `md:visualize`, `md:run-workflow`, etc. — where the orchestrator skill picks which sub-agents to dispatch based on the prompt.

### Why this problem

MD pipelines have several decision points that fixed scripts handle poorly:
- force-field selection (OPLS-AA/L vs. CHARMM36 vs. AMBER99SB-ILDN vs. GROMOS) with trade-offs by system type;
- protonation state (PROPKA at given pH vs. assume pH 7 vs. preserve crystallographic),
- crystallographic-water disposition (strip all vs. keep ordered waters near active site vs. surface to user),
- box geometry and padding (cubic vs. dodecahedron vs. octahedron — affects atom count and PBC artifacts),
- ion strategy (neutralize only vs. add physiological ~150 mM NaCl),
- equilibration quality judgments,
- analysis interpretation.

Each is a place where a deterministic script either guesses badly or punts on the user. An agentic layer can either pick a sensible default and explain, or ask once and remember — but doing this well requires the agent decomposition and skill boundaries to be right *before* we sink time into implementation.

### Toy benchmark

The **canonical GROMACS lysozyme-in-water tutorial** (PDB **1AKI** — hen egg-white lysozyme). This is the right toy problem because:
- It's well-trodden ground with a published step-by-step reference, giving us a ground truth for "did the agent get it right?"
- It includes every decision point listed above except free-energy / enhanced sampling.
- It's small enough to run end-to-end on a laptop in minutes for the prep+solvate phase.

### Confirmed scope decisions (these are pinned; please critique within these)

| Decision | Value | Why |
|---|---|---|
| MD engine | **GROMACS** | Matches the canonical tutorial. We get a reference oracle to compare agent output against. |
| Compute model | **Local-first** (Mac), with on-demand cloud escalation | User wants the dev loop to be a laptop. But the design must be **compute-agnostic** — an `Executor` abstraction so we can swap in HPC/SLURM or managed cloud GPU later without rewriting agents. |
| Prompt-mode delivery | **Claude skills** that internally orchestrate sub-agents | User wants to type a natural-language prompt and have the skill layer decide which agents to dispatch. |
| v0 scope under review | **Structure-prep + topology + solvate only** | Deliberately stops before minimization/dynamics. Goal of v0 is to validate orchestration, skill boundaries, and handoff semantics on a non-trivial-but-bounded slice before paying for long runs. v1 will add minimization/NVT/NPT/production; v2 adds analysis. |

### Prior decisions ruled out (don't relitigate, but flag if you think they're wrong)

- **Not OpenMM.** OpenMM is more Python-native, but choosing it would forfeit the lysozyme tutorial as a reference oracle. We accept the CLI ugliness for the validation benefit.
- **Not "one giant skill" that runs everything as a monolith.** That defeats the agentic decomposition the user wants and removes the decision points where agents add value.
- **Not "every gmx command is its own skill" either.** Too granular; the user would have to know GROMACS to invoke them. Skill boundaries should track *user-meaningful* steps, not CLI invocations.

### Starting agent breakdown (from prior ChatGPT discussion, used as a seed)

| Agent | Responsibility |
|---|---|
| Orchestrator | Chooses workflow order, checks that each step completed |
| Structure-prep agent | Cleans PDB, handles missing atoms, removes waters if needed |
| Topology agent | Selects force field, water model, generates topology |
| Solvation/ion agent | Builds box, solvates, adds ions |
| Simulation agent | Runs minimization, NVT, NPT, production (out of v0 scope) |
| QC agent | Checks logs, energy convergence, temperature, pressure, crashes |
| Analysis agent | Computes RMSD, Rg, RMSF, H-bonds (out of v0 scope) |
| Report agent | Writes final methods + results summary |

This is the seed; Section 2 below is our refined v0 proposal built on top of it. The user added a **Visualization** agent (VMD-first, ask the user up-front) which Section 2 incorporates.

---

## Section 2 — Artifact under review

The proposed v0 architecture, in full. This is what we want you to find holes in.

### 2.1 Agent roster (v0)

**`Orchestrator`**
- *Inputs:* user prompt (e.g. "prep 1AKI for simulation"), optional config overrides.
- *Outputs:* a directory-rooted run with `<run_id>/{step_NN_<agent>/...}` artifacts and a `manifest.json` recording every step's inputs, outputs, parameters, warnings.
- *Responsibilities:* decide which agents to invoke based on the prompt (in v0 the DAG is static: StructurePrep → Topology → Solvation → (Visualization?) → Report, with QC interleaved); retry policy; surface user-facing choices (force field, ion strategy, viz preference) at the right moment; abort cleanly on hard QC failures.
- *State model:* every agent reads previous-step outputs from disk (no in-memory shared state across agent boundaries). The manifest is the source of truth for what happened.
- *Failure modes:* infinite-retry traps if an upstream agent's output is malformed; mis-routing because the prompt was ambiguous about scope.

**`StructurePrep`**
- *Inputs:* a PDB ID or a local PDB/CIF path.
- *Outputs:* cleaned PDB ready for topology generation, plus a `prep_report.json` listing what was changed.
- *Responsibilities:* fetch from RCSB if given an ID; strip crystallographic waters (with the option to retain ordered ones — see decision points); identify missing atoms / residues / chains; choose protonation strategy; flag non-standard residues; warn about heteroatoms, alternate locations (altloc), disulfide bonds, cofactors, metal ions.
- *Failure modes:* silently accepting a structure with missing backbone atoms; protonating a histidine the wrong tautomer; dropping a structurally important crystallographic water; not handling altloc A vs. B correctly.

**`Topology`**
- *Inputs:* cleaned PDB from `StructurePrep`, force-field selection (or "ask user" / "use default").
- *Outputs:* GROMACS `.gro` + `.top` + per-chain `.itp` files via `gmx pdb2gmx`; a `topology_report.json` with the FF used, water model, termini choices, any pdb2gmx warnings.
- *Responsibilities:* invoke `gmx pdb2gmx` with the right `-ff`, `-water`, `-ter`, `-ignh` flags; handle interactive prompts (capping termini, choosing histidine tautomers); deal with non-standard residues (refuse, or load a custom .itp if provided).
- *Default:* OPLS-AA/L + SPC (tutorial default). Surface alternatives (CHARMM36 + TIP3P, AMBER99SB-ILDN + TIP3P) and a one-line trade-off summary when the user asks.
- *Failure modes:* pdb2gmx exits with a residue-not-found error and the agent retries blindly; the agent picks a force field whose recommended water model it doesn't pair with; HIS tautomer set wrong.

**`Solvation`**
- *Inputs:* `.gro` + `.top` from `Topology`, box parameters (geometry, padding), ion parameters (neutralize-only vs. salt concentration, cation/anion choice).
- *Outputs:* solvated + neutralized `.gro` + updated `.top`, ion-addition log.
- *Responsibilities:*
  - `gmx editconf -bt <cubic|dodecahedron|octahedron> -d <padding_nm>` to define the box.
  - `gmx solvate -cs spc216.gro` (or the right `-cs` for non-SPC water).
  - Build an `ions.mdp` (zero-step EM-equivalent so genion can run), then `gmx grompp -f ions.mdp ...` and `gmx genion -neutral [-conc 0.15]` with the chosen ion pair.
- *Default:* dodecahedron box with 1.0 nm padding; neutralize-only with Na+/Cl-; ask the user before defaulting to 150 mM salt (some users want minimal-ion systems for free-energy work later).
- *Failure modes:* padding too small → PBC artifacts downstream; box geometry inconsistent with the simulation goal; net-charge non-zero after genion because we asked it to swap the wrong solvent group; ion model mismatched with FF (e.g. Joung-Cheatham vs. default GROMACS ions).

**`QC`** (interleaved — runs after each prior agent before the next is allowed to start)
- *Inputs:* artifacts from the just-completed agent, plus the manifest.
- *Outputs:* a pass/fail verdict per check, written to `qc_report.json`. Hard fails abort the workflow; soft fails warn and continue.
- *Responsibilities (v0 checks):*
  - After `StructurePrep`: PDB parses; chain count matches expectation; no missing backbone atoms in standard residues; protonation choice recorded.
  - After `Topology`: `.top` references all generated `.itp` files; total residue count matches input minus stripped waters; `pdb2gmx` exit code == 0 and stderr free of "fatal error".
  - After `Solvation`: net charge ≈ 0 (|q| < 1e-3 e); total atom count within an expected band given box volume and water density; `genion` ran without warnings; box volume non-degenerate.
- *Failure modes:* thresholds set so loosely that real problems pass; or so tightly that pdb2gmx's normal warnings cause hard aborts; missing checks for the silent-corruption cases (e.g., a topology that references a deleted residue).

**`Visualization`** *(new per user request)*
- *Inputs:* the artifact from whichever upstream agent the user wants to visualize (cleaned PDB, post-topology `.gro`, solvated `.gro`, post-ion `.gro`).
- *Outputs:* rendered PNG snapshots, a launchable VMD state file (`.vmd` or Tcl script), and optionally a NGLview HTML if running in a notebook context. All written to `<run_id>/visualization/`.
- *Responsibilities:*
  - **Asks the user up-front, exactly once per workflow**: "Do you want visualizations? If yes: VMD (default if installed) / PyMOL / NGLview (web). Which checkpoints: prep / topology / solvated / neutralized / all?" Persists the answer in the run manifest so subsequent agents don't re-prompt.
  - Detects which viewers are installed on the host. If the user picks VMD and it isn't installed, falls back with explicit messaging (offer Homebrew/conda install hint) — does not silently use a different tool.
  - For headless runs (no DISPLAY), uses VMD's text-mode rendering (`vmd -dispdev text -e render.tcl`) or PyMOL's `cmd.png` to produce images without a window.
  - Generates a VMD Tcl script (or PyMOL `.pml`) that sets sensible defaults: NewCartoon for protein, Lines or Points for water (or hide water), VDW for ions colored by type.
- *Open design question for you (the reviewer):* should visualization be a distinct agent at all, or should it live inside `QC` since visual inspection *is* a quality check? See decision points.
- *Failure modes:* prompting the user mid-run instead of up-front, breaking unattended/automated invocations; silently producing no output if no viewer is installed; rendering on every checkpoint by default and burning disk space; embedding viewer-specific assumptions that don't survive when the viewer is swapped.

**`Report`**
- *Inputs:* the manifest, all per-step `*_report.json` files, the `qc_report.json` files, and any visualization outputs.
- *Outputs:* a single `REPORT.md` summarizing the prepared system — residue count, force field, water model, box geometry + volume, total atom count, ion counts and species, net charge before/after neutralization, all warnings raised across the run, and embedded links/images from the visualization agent if it ran.
- *Failure modes:* report lies because it pulled stale fields from the manifest; embeds broken image paths; says "ready to minimize" when QC actually flagged a soft failure.

### 2.2 Skill boundary proposal

One Claude skill per user-meaningful step, not per `gmx` command:

| Skill | Wraps | Agent(s) |
|---|---|---|
| `md:prep-structure` | "Clean a PDB for MD" | `StructurePrep` + `QC` (structure checks) |
| `md:build-topology` | "Generate force-field topology" | `Topology` + `QC` (topology checks) |
| `md:solvate-system` | "Solvate and neutralize" | `Solvation` + `QC` (solvation checks) |
| `md:visualize` | "Render the current system / trajectory" | `Visualization` |
| `md:run-workflow` | "Do the whole pipeline end-to-end" | `Orchestrator` (calls the above skills) |

The orchestrator skill is the entry point; the sub-skills can also be called directly by power users.

User-surfaced decisions (the agent *must* ask before defaulting):
- Force field & water model — only if the system has anything non-standard, or if the user prompt indicates they care.
- Ion strategy — always ask between "neutralize only" and "physiological salt", unless the prompt is explicit.
- Visualization — always ask up-front (per user requirement).

Agent-internal decisions (defaults applied, recorded in manifest, surfaced in report):
- Box geometry: dodecahedron, padding 1.0 nm.
- Protonation: PROPKA at pH 7 if PROPKA available; else assume standard pH-7 protonation states; never silently change crystallographic protonation if explicitly set.
- Crystallographic waters: strip by default, but list count and resids of any that were within 4 Å of the protein in the manifest so the user can see what was discarded.

### 2.3 State & handoff model

```
<runs_root>/<run_id>/
├── manifest.json
├── step_01_structure_prep/
│   ├── 1aki_clean.pdb
│   └── prep_report.json
├── step_02_topology/
│   ├── system.gro
│   ├── system.top
│   ├── posre.itp
│   └── topology_report.json
├── step_03_solvation/
│   ├── system_solvated.gro
│   ├── system_neutralized.gro
│   ├── system.top
│   └── solvation_report.json
├── qc/
│   ├── qc_step_01.json
│   ├── qc_step_02.json
│   └── qc_step_03.json
├── visualization/        # only if user opted in
│   ├── prep.png
│   ├── solvated.png
│   ├── neutralized.png
│   └── visualize.vmd
└── REPORT.md
```

Every agent reads its inputs from a path passed by the orchestrator; writes outputs to a directory it owns; writes its `*_report.json` recording (a) inputs consumed by absolute path, (b) commands run with full argv, (c) parameter values, (d) warnings. The manifest is appended to atomically after each step.

### 2.4 Compute abstraction

```
class Executor:
    def run(self, argv: list[str], cwd: str, env: dict, stdin: str | None) -> CompletedProcess
    def stage_in(self, local_paths: list[str]) -> dict[str, str]   # local -> remote map
    def stage_out(self, remote_paths: list[str]) -> dict[str, str]
```

- `LocalExecutor` (v0): wraps `subprocess.run`. `stage_in` and `stage_out` are no-ops (identity map).
- `RemoteExecutor` (placeholder, not implemented in v0): would submit via SLURM or call a managed-cloud API, then SCP/rsync results back.

Agents never call `subprocess` directly — they go through the executor. v0 only ships `LocalExecutor` but the interface is in place so swapping to remote is mechanical.

The orchestrator picks the executor; the user can request cloud via the prompt ("run this on the GPU node") and the orchestrator confirms before invoking a remote executor.

### 2.5 Decision points to pressure-test

Please be specific about each of these:

1. **Force-field/water-model selection logic** — When should the topology agent ask the user vs. pick a default? Is "OPLS-AA/L + SPC if no signal from user" the right default for v0? What about for membrane systems, nucleic acids, or systems with cofactors?
2. **Protonation strategy** — Is "PROPKA at pH 7 if available, else default protonation states" defensible? When is it wrong? What about His tautomer assignment specifically, where pdb2gmx's interactive prompts are notorious?
3. **Crystallographic water disposition** — Strip-by-default with a manifest record of what was within 4 Å of the protein: too aggressive? Too lenient? Should there be an active-site detection step before deciding?
4. **Box geometry and padding** — Dodecahedron, 1.0 nm padding: is this the right v0 default, or is cubic the safer choice for newcomers? Does the answer depend on whether the user plans to do PME later?
5. **Ion strategy** — Always-ask between "neutralize only" vs. "150 mM NaCl": is the "always ask" too noisy? What about the ion model mismatch problem (Joung-Cheatham vs. default), which we currently don't flag at all?
6. **QC thresholds** — Net charge `|q| < 1e-3 e`: defensible? Atom-count-within-an-expected-band: how do we compute the band without overfitting to lysozyme? What checks are we missing?
7. **Skill granularity** — Is one skill per agent right, or should `md:prep-structure` swallow `md:build-topology` (since you almost never run one without the other)? Or should `md:build-topology` split into FF-selection and pdb2gmx-execution?
8. **Visualization agent placement** — Is this a distinct agent, or should it sit inside `QC` (since visual inspection is itself a quality check)? Does the "ask up-front, once per workflow" UX hold up in non-interactive / scripted invocations? What does "skip visualization" do cleanly to the report?
9. **Executor abstraction shape** — Does the `Executor` interface as written actually generalize, or have we baked in local-subprocess assumptions (like the `stdin: str` parameter, or the `cwd: str` instead of a remote-aware path object)?
10. **Manifest as source of truth** — Is appending to a single `manifest.json` after each step the right move, or should each step's manifest be a separate immutable file with a small index? Concurrency, partial writes, recoverability.
11. **What's missing from the agent roster** — Are there decision points in MD prep that we haven't named an agent for? (Examples we considered: a `Validation` agent that runs a 0-step `gmx mdrun` to catch parameter-file errors; a `Provenance` agent that records exact GROMACS version + FF version + library hashes for reproducibility. Both seem useful — should they be agents, skills, or just orchestrator responsibilities?)
12. **The "v0 stops before dynamics" choice itself** — Are we hardening the wrong slice? Should v0 include energy minimization since it's the first sanity check that the prepared system is physical?

---

## Section 3 — Critique prompt

You are an adversarial reviewer. Be critical. Be argumentative.
Find every hole: missing steps, wrong algebra, untested assumptions,
edge cases not addressed, implicit dependencies, claims without
evidence, off-by-one errors, sign errors, dimensional errors. Don't
be polite — if something is wrong, say so. Concision over hedging.

For each issue, state:
  - WHAT is wrong (specific, not vague — name the line or symbol)
  - WHY it matters (what breaks downstream if uncorrected)
  - WHAT to do (concrete fix, or what evidence would close the gap)

Number your issues. After all issues, end your response with exactly
one of these lines, no other text after it:

  VERDICT: APPROVED
  VERDICT: ISSUES_REMAIN

Use APPROVED only when there are no issues you would block on.
Minor nitpicks alone do not justify ISSUES_REMAIN — call them out
but still verdict APPROVED. Use ISSUES_REMAIN whenever any of your
issues are genuinely blocking.
