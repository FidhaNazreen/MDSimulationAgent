from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


OUT_DIR = Path(__file__).resolve().parent


def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "Title",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=24,
            leading=29,
            spaceAfter=8,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#1f2933"),
        ),
        "subtitle": ParagraphStyle(
            "Subtitle",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=11,
            leading=15,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#52616b"),
            spaceAfter=20,
        ),
        "h1": ParagraphStyle(
            "Heading1",
            parent=base["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=16,
            leading=20,
            textColor=colors.HexColor("#102a43"),
            spaceBefore=14,
            spaceAfter=7,
        ),
        "h2": ParagraphStyle(
            "Heading2",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=15,
            textColor=colors.HexColor("#243b53"),
            spaceBefore=9,
            spaceAfter=5,
        ),
        "body": ParagraphStyle(
            "Body",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=9.6,
            leading=13.2,
            spaceAfter=5,
        ),
        "small": ParagraphStyle(
            "Small",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=8.3,
            leading=10.8,
            spaceAfter=3,
        ),
        "bullet": ParagraphStyle(
            "Bullet",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=9.2,
            leading=12.4,
            leftIndent=13,
            firstLineIndent=-8,
            spaceAfter=3,
        ),
        "code": ParagraphStyle(
            "Code",
            parent=base["Code"],
            fontName="Courier",
            fontSize=7.9,
            leading=9.6,
            textColor=colors.HexColor("#111827"),
        ),
        "callout": ParagraphStyle(
            "Callout",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=9.2,
            leading=12.5,
            leftIndent=8,
            rightIndent=8,
            spaceBefore=6,
            spaceAfter=6,
        ),
    }


def _footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#6b7280"))
    canvas.drawString(doc.leftMargin, 0.43 * inch, "MDSimulationAgent usage guide")
    canvas.drawRightString(LETTER[0] - doc.rightMargin, 0.43 * inch, f"Page {doc.page}")
    canvas.restoreState()


def p(text: str, style="body"):
    return Paragraph(text, STYLES[style])


def bullet(text: str):
    return Paragraph(f"- {text}", STYLES["bullet"])


def code_block(text: str):
    return Preformatted(text.strip("\n"), STYLES["code"])


def table(rows, widths=None, font_size=8.0, header=True):
    cooked = []
    for row in rows:
        cooked.append([Paragraph(str(cell), STYLES["small"]) for cell in row])
    t = Table(cooked, colWidths=widths, hAlign="LEFT", repeatRows=1 if header else 0)
    style = [
        ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d9e2ec")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("FONTSIZE", (0, 0), (-1, -1), font_size),
    ]
    if header:
        style += [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e6f0ff")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#102a43")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ]
    t.setStyle(TableStyle(style))
    return t


def callout(text: str):
    t = Table([[Paragraph(text, STYLES["callout"])]], colWidths=[6.7 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f0f7ff")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#9fb3c8")),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return t


def build_pdf(filename: str, title: str, subtitle: str, story):
    doc = SimpleDocTemplate(
        str(OUT_DIR / filename),
        pagesize=LETTER,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.68 * inch,
        bottomMargin=0.68 * inch,
        title=title,
        author="MDSimulationAgent",
    )
    flow = [p(title, "title"), p(subtitle, "subtitle")]
    flow.extend(story)
    doc.build(flow, onFirstPage=_footer, onLaterPages=_footer)


def detailed_story():
    s = []
    s.append(callout(
        "<b>What this repo is:</b> an installable Python package named "
        "<b>mdagent</b> that wraps a GROMACS molecular-dynamics workflow in a "
        "CLI, a resumable artifact ledger, and three bundled Claude Code skills. "
        "It is strongest as a reproducible setup-and-validation assistant for "
        "soluble protein-only systems."
    ))

    s += [
        p("1. Package Map", "h1"),
        p("The repository is organized around a small Python CLI plus bundled resources. "
          "The CLI lives in <b>src/mdagent/cli.py</b>, the ordered workflow lives in "
          "<b>src/mdagent/orchestrator.py</b>, one module per pipeline phase lives under "
          "<b>src/mdagent/steps/</b>, and the packaged schemas, tutorials, starter kit, "
          "and Claude skills live under <b>src/mdagent/_resources/</b>."),
        table([
            ["Area", "Purpose"],
            ["mdagent run-workflow", "Runs ingest, classification, prep, topology, solvation, EM, NVT, NPT, production, analysis, optional visualization, and report."],
            ["mdagent prep-structure", "Runs only ingest, classifier, and prep. It does not require GROMACS."],
            ["mdagent visualize", "Writes VMD/PyMOL/NGL scripts and optionally renders checkpoint PNGs for an existing run."],
            ["mdagent install-skills", "Copies the bundled Claude skills into ~/.claude/skills or a project .claude/skills directory."],
            ["mdagent init-project", "Creates a runnable starter project with example configs, local skills, a bundled 1AKI PDB, and verify.sh."],
            ["mdagent pack-bundle", "Builds a self-contained handoff folder or tarball, optionally with a wheelhouse for offline installs."],
            ["mdagent tutorials", "Extracts or builds the packaged tutorial bundle."],
            ["mdagent doctor", "Checks mdagent, GROMACS, RCSB connectivity, PROPKA, and viewer availability as needed."],
        ], widths=[1.75 * inch, 4.95 * inch]),
    ]

    s += [
        p("2. Installation", "h1"),
        p("For normal use, install the package as a uv tool, then install GROMACS for any step past structure prep. "
          "The README uses a placeholder GitHub path; replace it with the real remote or a local checkout path."),
        code_block("""
brew install uv
uv tool install --force git+https://github.com/mjayadharan/MDSimulationAgent@v0.1.0
brew install gromacs
mdagent install-skills --user

mdagent --version
mdagent doctor --gmx-required
mdagent self-test resources
"""),
        p("For local development in this repo:", "h2"),
        code_block("""
uv sync
uv run pytest
uv run pytest --run-slow
uv run pytest --run-wheel
"""),
        p("The base Python dependencies are jsonschema, pexpect, gemmi, and packaging. Optional extras include PROPKA for pKa-aware protonation and tutorial PDF generation dependencies."),
    ]

    s += [
        p("3. Fastest Ways To Use It", "h1"),
        p("A. Direct CLI run from any directory", "h2"),
        code_block("""
mdagent run-workflow --runs-root ./runs --pdb-id 1AKI --run-id demo
mdagent inspect --run-root ./runs/demo
"""),
        p("B. Stop at a partial workflow point", "h2"),
        code_block("""
mdagent run-workflow --runs-root ./runs --pdb-id 1AKI --run-id prep-only --stop-after prep
mdagent run-workflow --runs-root ./runs --pdb-id 1AKI --run-id solvated --stop-after solvation
"""),
        p("Valid stop points are <b>prep</b>, <b>topology</b>, <b>solvation</b>, <b>em</b>, <b>nvt</b>, and <b>npt</b>."),
        p("C. Use the starter kit", "h2"),
        code_block("""
mdagent init-project ./my-md-project
cd ./my-md-project
./verify.sh
./verify.sh --run-smoke
mdagent inspect --run-root ./runs/smoke
"""),
        p("D. Use Claude Code naturally", "h2"),
        p("After the skills are installed, open Claude Code in a project and ask for a concrete MD task, such as "
          "<i>Set up lysozyme in water and minimize it</i> or <i>Prep this local PDB for simulation, but do not run dynamics</i>. "
          "The skills route those requests to the same CLI commands and surface structured failures from step reports."),
        p("E. Ship a bundle to someone else", "h2"),
        code_block("""
mdagent pack-bundle ./mdagent-bundle --with-vendor --with-propka --archive
tar -xzf mdagent-bundle-macos-arm64-py311.tar.gz
cd mdagent-bundle
./setup.sh --check-only
./setup.sh
./run_simulation.sh
"""),
    ]

    s += [
        PageBreak(),
        p("4. Run Configuration", "h1"),
        p("Every run is controlled by a JSON object validated against <b>run_config.schema.json</b>. "
          "If you omit <b>--config</b>, the CLI materializes a minimal inline config from flags. "
          "For real work, copy one of the starter configs and edit it."),
        code_block("""
{
  "schema_version": "0.1.0",
  "pipeline_mode": "tutorial_reproduction",
  "interaction_mode": "noninteractive_defaults",
  "input": { "pdb_id": "1AKI" },
  "force_field": "oplsaa",
  "water_model": "spc",
  "box": { "geometry": "dodecahedron", "padding_nm": 1.0, "cutoff_nm": 1.0 },
  "ion_strategy": { "mode": "neutralize_only", "cation": "NA", "anion": "CL", "random_seed": 42 },
  "em": { "step_cap": 1000, "fmax_tol_kjmolnm": 1000.0 },
  "nvt": { "nsteps": 50000, "dt_ps": 0.002, "temperature_K": 300.0 },
  "npt": { "nsteps": 50000, "dt_ps": 0.002, "temperature_K": 300.0, "pressure_bar": 1.0 },
  "production": { "enabled": true, "nsteps": 500000, "dt_ps": 0.002 },
  "analysis": { "enabled": true }
}
"""),
        table([
            ["Field", "Meaning"],
            ["pipeline_mode", "tutorial_reproduction uses the GROMACS lysozyme tutorial style; general_md_prep switches default ingest to mmCIF and uses pdb2gmx -inter for titratable residue prompts."],
            ["interaction_mode", "Schema exposes interactive, noninteractive_defaults, and strict_config_required, but the current automated topology path mostly uses planned/default answers."],
            ["input", "Use either input.pdb_id for RCSB fetches or input.structure_path for local PDB/mmCIF files. Relative structure paths are resolved relative to the config file."],
            ["force_field / water_model", "Passed to gmx pdb2gmx. Defaults are oplsaa and spc. The schema allows any force-field string, so local GROMACS availability still matters."],
            ["box", "Controls editconf geometry and padding."],
            ["ion_strategy", "neutralize_only, physiological_salt, or custom. The solvation step validates final charge accounting."],
            ["em", "Short steepest-descent minimization, used as a validation gate."],
            ["nvt / npt / production", "Length, timestep, temperature, pressure, and trajectory output stride."],
            ["visualization", "disabled by default. Set mode/requested render options or run mdagent visualize later."],
            ["tool_versions", "Optional pinned versions for reproducibility and fingerprinting."],
        ], widths=[1.55 * inch, 5.15 * inch]),
    ]

    s += [
        p("5. Pipeline Internals", "h1"),
        p("The orchestrator walks a fixed DAG. After each successful step, it writes a step_report.json and, for most computational steps, a step_fingerprint.json. "
          "The top-level index.json records status, attempts, artifacts, and fingerprint composites."),
        table([
            ["Step", "What happens", "Main outputs"],
            ["00 preflight", "Skipped as a step, but doctor preflight runs before compute.", "doctor result surfaced on failure"],
            ["01 ingest", "Fetches RCSB PDB/mmCIF or copies local input; can derive PDB from mmCIF and verify coordinate ID injectivity.", "original structure, working.pdb, optional coordinate_id_map.json"],
            ["02 classifier", "Counts residues and rejects unsupported chemistry.", "classification.json"],
            ["03 prep", "Collects chain, HIS, CYS, and titratable-residue observations; strips HETATM in tutorial mode during ingest; optionally runs PROPKA if available.", "observations.json, mutations.json, optional protonation_analysis.json"],
            ["04 topology", "Drives gmx pdb2gmx through a PTY-based DialogueRunner, answering termini, disulfide, and optional per-residue prompts.", "system_apo.gro/top, posre.itp, topology_plan.json, pdb2gmx transcript, protonation decisions"],
            ["05 solvation", "Runs editconf, solvate, grompp, genion, and a second grompp consistency gate.", "system_ions.gro/top/tpr, charge_accounting.json"],
            ["06 EM", "Runs grompp and mdrun for steepest-descent minimization; parses em.log for convergence.", "em.gro, em.log, em_convergence.json"],
            ["07 NVT", "Position-restrained constant-temperature equilibration.", "nvt.gro/cpt/xtc/log/edr/tpr"],
            ["08 NPT", "Position-restrained constant-pressure equilibration from NVT checkpoint.", "npt.gro/cpt/xtc/log/edr/tpr"],
            ["09 production", "Free production MD from NPT checkpoint; skipped when production.enabled is false.", "production.gro/cpt/xtc/log/edr/tpr"],
            ["10 analysis", "Runs RMSD, Rg, RMSF, H-bonds, and energy summaries.", "analysis.json and .xvg files"],
            ["11 visualization", "Optional static checkpoint rendering or script generation.", "VMD/PyMOL scripts and optional PNGs"],
            ["12 report", "Regenerates REPORT.md from on-disk step reports and sidecars.", "REPORT.md"],
        ], widths=[0.85 * inch, 3.35 * inch, 2.5 * inch]),
    ]

    s += [
        p("6. Reading Outputs", "h1"),
        p("The run directory is intentionally verbose. Treat it as a provenance bundle, not just a scratch folder."),
        code_block("""
runs/<run_id>/
  run_config.json
  index.json
  step_01_structure_ingest/working.pdb
  step_02_classifier/classification.json
  step_03_structure_prep/observations.json
  step_04_topology/system_apo.gro system_apo.top pdb2gmx_transcript.json
  step_05_solvation/system_ions.gro system_ions.top charge_accounting.json
  step_06_em/em.gro em.log em_convergence.json
  step_07_nvt/nvt.*
  step_08_npt/npt.*
  step_09_production/production.*
  step_10_analysis/analysis.json *.xvg
  REPORT.md
"""),
        table([
            ["Readiness", "Meaning"],
            ["ready", "Every gate passed, EM converged, and no chemistry/physics warnings were recorded."],
            ["ready_with_warnings", "The run completed but chemistry or physics warnings deserve review."],
            ["blocked", "A step failed or a blocking warning was emitted."],
            ["not_validated", "EM did not run or needs a longer minimization, so the system should not be treated as validated."],
        ], widths=[1.6 * inch, 5.1 * inch]),
        p("For quick scientific sanity checks on lysozyme, inspect Rg around 1.4 nm, density near 1000 kg/m^3 after NPT, and RMSD behavior. These are sanity checks, not proof of production-quality science."),
    ]

    s += [
        p("7. Resume And Reproducibility", "h1"),
        p("Re-run the same command with the same <b>--run-id</b> to resume. The orchestrator locks the run directory, recovers stale running steps, recomputes fingerprints for succeeded steps, invalidates stale descendants when configuration, inputs, schema, tool components, or source code changed, and continues from the first non-succeeded step."),
        code_block("""
mdagent run-workflow --runs-root ./runs --config ./run_configs/my_run.json --run-id demo
"""),
        p("This makes the package useful for iterative setup: adjust a config, rerun, and keep the unaffected upstream artifacts."),
    ]

    s += [
        p("8. Common Failure Triage", "h1"),
        table([
            ["Failure", "Where to look", "Typical cause"],
            ["UnsupportedResidueError", "step_02_classifier/classification.json", "Ligands, nucleic acids, modified residues, or HETATM records outside tutorial stripping."],
            ["CoordinateIdMapNotInjective", "step_01_structure_ingest/coordinate_id_map.json", "mmCIF to PDB derivation would collapse distinct canonical residues onto one PDB identifier."],
            ["UnexpectedPromptError", "step_04_topology/pdb2gmx_transcript.json and step_report.json", "GROMACS prompt changed or a prompt family is not recognized by the current catalog."],
            ["ConsistencyGateFailure", "The failing step's step_report.json stderr tail", "gmx grompp rejected topology, coordinates, mdp, or constraints."],
            ["ChargeAccountingMismatch", "step_05_solvation/charge_accounting.json", "Inserted ions do not match expected neutralization or final charge is not near zero."],
            ["EMDiverged / EMStuck", "step_06_em/em.log and em_convergence.json", "Bad contacts, poor starting geometry, topology issue, or too-strict/too-short EM settings."],
            ["No viewer detected", "visualization render_probe.json", "VMD/PyMOL/NGLview unavailable; scripts are still written for later rendering."],
        ], widths=[1.55 * inch, 2.25 * inch, 2.9 * inch]),
    ]

    s += [
        p("9. Current Limitations", "h1"),
        bullet("Scientific scope is deliberately narrow: soluble protein-only systems are the supported path. Ligands, cofactors, nucleic acids, glycans, membranes, metal centers, covalent modifications, and mixed biomolecular assemblies fail fast or require manual preprocessing outside this package."),
        bullet("The classifier is simple and mostly PDB-line based. It does not yet do rich biological assembly reasoning, membrane detection, OPM lookup, or full mmCIF chemistry classification."),
        bullet("Structure prep is useful but still shallow. It observes HIS/CYS/titratable residues and can attempt PROPKA, but altloc resolution, MSE conversion, missing-loop repair, termini policy breadth, retained-water decisions, and general repair workflows are not mature."),
        bullet("Topology automation depends on recognized pdb2gmx prompts. The recognizer was probed against GROMACS 2026.2 and may need prompt catalogs for other versions."),
        bullet("PROPKA support is conditional. If the optional propka package is missing or fails, the code falls back to fixed pH-7 defaults. Current pKa-aware mapping is limited to the handled pdb2gmx prompt families and should be audited for unusual chemistry or non-OPLS force-field prompt orderings."),
        bullet("The schema allows broad force-field strings, but the actual local GROMACS force-field directory, water model compatibility, and prompt order still govern success."),
        bullet("Dynamics defaults are tutorial-sized. A 1 ns default production run, or the even shorter starter-kit smoke run, is not enough for publishable sampling."),
        bullet("Execution is local only. The README explicitly notes that remote HPC/cloud/GPU execution is not wired yet."),
        bullet("Analysis is a compact sanity suite, not a full scientific analysis workflow. H-bond analysis is best-effort, and statistical convergence is left to the user."),
        bullet("Visualization is static checkpoint rendering, not trajectory movies or interactive trajectory analysis."),
        bullet("Security and provenance are local-file oriented. The package writes rich artifacts, but it does not yet provide signed manifests for individual runs, formal audit logging across machines, or data-management integration."),
    ]

    s += [
        p("10. Possible Improvements", "h1"),
        table([
            ["Area", "Improvement"],
            ["Chemistry coverage", "Add ligand/cofactor parametrization paths, nucleic-acid support, glycan handling, metal-center strategies, and explicit fail/ask policies for modified residues."],
            ["Structure prep", "Implement robust altloc selection, MSE to MET conversion, missing-residue checks, disulfide planning, chain merge/split policies, retained-water classification, and better repair handoffs."],
            ["Prompt automation", "Generate versioned prompt catalogs for multiple GROMACS releases and force fields; add discovery-mode fixtures that update recognizers safely."],
            ["Remote execution", "Introduce a RemoteExecutor abstraction for Slurm/PBS/cloud runners, checkpoint sync, GPU queues, and resumable artifact transfer."],
            ["Configuration UX", "Add a config wizard, schema-aware validation messages, force-field/water compatibility checks, and clearer profiles for common lab policies."],
            ["Scientific validation", "Add longer equilibration recipes, replicate runs, convergence diagnostics, ensemble checks, automatic plots, and thresholds configurable by system class."],
            ["Analysis", "Add plotting, PCA, clustering, secondary-structure analysis, binding-site metrics, trajectory stripping/centering, and export-ready report figures."],
            ["Visualization", "Support movies, NGL web reports, trajectory snapshots over time, and richer default molecular representations."],
            ["Packaging", "Replace placeholder GitHub URLs in docs, add release automation, publish wheels, and include platform-specific install checks."],
            ["Testing", "Broaden golden paths beyond 1AKI, add more GROMACS versions, add real-world failure fixtures, and include regression tests for PROPKA-backed decisions."],
        ], widths=[1.45 * inch, 5.25 * inch]),
    ]

    s += [
        p("11. Practical Guidance", "h1"),
        bullet("Use <b>prep-structure</b> first for unfamiliar structures; read classification.json before committing compute time."),
        bullet("Keep each scientific hypothesis in its own config file and reuse run IDs only for intentional resume/update cycles."),
        bullet("Pin GROMACS, mdagent, force field, water model, and random seeds when reproducibility matters."),
        bullet("Read REPORT.md first, then step_report.json for any failed step, then the relevant sidecar JSON."),
        bullet("Treat ready as a workflow validation result, not as a scientific conclusion."),
        bullet("For real production, extend equilibration/production lengths and add domain-specific analysis outside the smoke-test defaults."),
    ]
    return s


def short_story():
    s = [
        callout("<b>Short version:</b> install <b>mdagent</b>, install GROMACS, run a config or ask Claude Code to run one of the bundled skills, then inspect <b>REPORT.md</b> plus the per-step JSON artifacts."),
        p("What It Does", "h1"),
        p("MDSimulationAgent is a Python CLI and Claude Code skill bundle for agent-driven GROMACS workflows. "
          "It takes a PDB ID or local structure, prepares a soluble protein system, builds topology, solvates and neutralizes it, runs EM/NVT/NPT/production, performs basic analysis, and writes a readiness report."),
        p("Quick Start", "h1"),
        code_block("""
brew install uv
uv tool install --force git+https://github.com/mjayadharan/MDSimulationAgent@v0.1.0
brew install gromacs
mdagent install-skills --user

mdagent run-workflow --runs-root ./runs --pdb-id 1AKI --run-id demo
mdagent inspect --run-root ./runs/demo
"""),
        p("Starter Kit Option", "h1"),
        code_block("""
mdagent init-project ./my-md-project
cd ./my-md-project
./verify.sh
./verify.sh --run-smoke
"""),
        p("Core Commands", "h1"),
        table([
            ["Command", "Use"],
            ["mdagent doctor --gmx-required", "Check the environment before running MD."],
            ["mdagent prep-structure", "Ingest, classify, and prep only; no GROMACS required."],
            ["mdagent run-workflow", "Run the full or partial pipeline."],
            ["mdagent inspect", "Print index.json status and REPORT.md."],
            ["mdagent visualize", "Generate viewer scripts and optional static checkpoint PNGs."],
            ["mdagent init-project", "Create a runnable starter directory."],
            ["mdagent pack-bundle", "Create a handoff bundle for another machine."],
        ], widths=[2.35 * inch, 4.35 * inch]),
        p("Useful Flags", "h1"),
        code_block("""
--config path/to/run_config.json
--runs-root ./runs
--run-id meaningful-name
--pdb-id 1AKI
--structure-path /path/to/protein.pdb
--stop-after prep|topology|solvation|em|nvt|npt
--pipeline-mode tutorial_reproduction|general_md_prep
--viz-mode disabled|default|requested
"""),
        p("What To Inspect", "h1"),
        table([
            ["File", "Why it matters"],
            ["REPORT.md", "Readiness headline: ready, ready_with_warnings, blocked, or not_validated."],
            ["index.json", "Step statuses, artifacts, attempts, and fingerprints."],
            ["step_report.json", "Inputs, outputs, warnings, executor calls, and failure reason per step."],
            ["classification.json", "Supported/unsupported chemistry decision."],
            ["charge_accounting.json", "Ion insertion and final charge validation."],
            ["em_convergence.json", "Whether minimization converged, needs longer, diverged, or stuck."],
            ["analysis.json", "RMSD, Rg, RMSF, H-bonds, temperature, pressure, and density summaries."],
        ], widths=[2.0 * inch, 4.7 * inch]),
        p("Limits To Remember", "h1"),
        bullet("Best-supported systems are soluble protein-only. Ligands, nucleic acids, membranes, glycans, cofactors, and many modifications are outside the current supported path."),
        bullet("GROMACS prompt automation is version-sensitive; current recognizers target modern 2026.x prompt shapes."),
        bullet("PROPKA is optional and conditional. Without the extra package, the workflow falls back to fixed pH-7 defaults."),
        bullet("The starter smoke run and default tutorial-scale runs validate the workflow, not scientific convergence."),
        bullet("Execution is local; HPC/cloud execution is not wired yet."),
        bullet("Analysis and visualization are sanity checks, not full downstream science."),
        p("Best Next Improvements", "h1"),
        bullet("Add ligand/cofactor/membrane/nucleic-acid support and richer structure repair."),
        bullet("Build versioned GROMACS prompt catalogs and broader force-field tests."),
        bullet("Add remote executor support for Slurm/cloud/GPU runs."),
        bullet("Improve config UX, force-field/water compatibility checks, plots, and richer analysis reports."),
        bullet("Expand golden-path tests beyond lysozyme and document release-ready install URLs."),
    ]
    return s


STYLES = _styles()


if __name__ == "__main__":
    build_pdf(
        "MDSimulationAgent_usage_detailed.pdf",
        "MDSimulationAgent Detailed Usage Guide",
        "How to install, run, inspect, troubleshoot, and improve the agent-driven GROMACS workflow",
        detailed_story(),
    )
    build_pdf(
        "MDSimulationAgent_usage_short.pdf",
        "MDSimulationAgent Short Usage Guide",
        "Quick start, key commands, outputs, limitations, and improvement ideas",
        short_story(),
    )
    print(f"Wrote {OUT_DIR / 'MDSimulationAgent_usage_detailed.pdf'}")
    print(f"Wrote {OUT_DIR / 'MDSimulationAgent_usage_short.pdf'}")
