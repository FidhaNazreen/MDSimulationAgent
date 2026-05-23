"""Command-line entrypoint for mdagent.

Exposed as the `mdagent` console script via `[project.scripts]` in
pyproject.toml. The skills (`md-run-workflow`, `md-prep-structure`,
`md-visualize`) invoke this CLI directly — no `cd` into a checkout
required.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from importlib.metadata import version as _pkg_version
from pathlib import Path
from typing import Any

from . import doctor as doctor_mod
from .orchestrator import run_workflow
from .run_index import RunIndex


def _installed_version() -> str:
    try:
        return _pkg_version("mdagent")
    except Exception:
        from . import __version__
        return __version__


# ---- run-workflow ------------------------------------------------------


_PIPELINE_STOPPING_POINTS = {
    "prep": "step_03_structure_prep",
    "topology": "step_04_topology",
    "solvation": "step_05_solvation",
    "em": "step_06_em",
    "nvt": "step_07_nvt",
    "npt": "step_08_npt",
}


def _build_minimal_config(args: argparse.Namespace) -> dict[str, Any]:
    cfg: dict[str, Any] = {
        "schema_version": "0.1.0",
        "pipeline_mode": args.pipeline_mode,
        "interaction_mode": args.interaction_mode,
        "input": {},
        "force_field": args.force_field,
        "water_model": args.water_model,
        "ph": 7.0,
        "protonation_policy": "propka",
        "altloc_policy": "highest_occupancy",
        "water_retention_policy": "strip_all",
        "box": {
            "geometry": args.box_geometry,
            "padding_nm": args.box_padding_nm,
            "cutoff_nm": 1.0,
        },
        "ion_strategy": {
            "mode": args.ion_mode,
            "cation": args.cation,
            "anion": args.anion,
            "random_seed": args.random_seed,
        },
        "em": {
            "step_cap": args.em_step_cap,
            "fmax_tol_kjmolnm": args.em_fmax_tol,
        },
        "visualization": {
            "mode": args.viz_mode,
        },
    }
    if args.pdb_id:
        cfg["input"]["pdb_id"] = args.pdb_id
        cfg["input"]["biological_assembly"] = "asymmetric_unit"
    elif args.structure_path:
        cfg["input"]["structure_path"] = str(Path(args.structure_path).resolve())
    if args.viz_checkpoints:
        cfg["visualization"]["checkpoints"] = args.viz_checkpoints
    if args.viz_viewer:
        cfg["visualization"]["viewer"] = args.viz_viewer
    return cfg


def _resolve_config_path(args: argparse.Namespace) -> Path:
    """Use args.config when provided; otherwise materialize a minimal config."""
    if args.config:
        return Path(args.config)
    cfg = _build_minimal_config(args)
    runs_root = Path(args.runs_root).resolve()
    runs_root.mkdir(parents=True, exist_ok=True)
    cfg_path = runs_root / "_inline_run_config.json"
    cfg_path.write_text(json.dumps(cfg, indent=2, sort_keys=True))
    return cfg_path


def cmd_run_workflow(args: argparse.Namespace) -> int:
    cfg_path = _resolve_config_path(args)
    stop_after = getattr(args, "stop_after", None)
    stop_after_step = _PIPELINE_STOPPING_POINTS.get(stop_after) if stop_after else None

    run_root, index = run_workflow(
        run_config_path=cfg_path,
        runs_root=args.runs_root,
        run_id=args.run_id,
        stop_after_step_id=stop_after_step,
        skip_network_check=args.skip_network_check,
        skip_viewer_check=args.skip_viewer_check,
        skip_gmx_version_check=args.skip_gmx_version_check,
    )

    summary = {
        "run_root": str(run_root),
        "step_statuses": {s.step_id: s.status for s in index.steps},
        "report_path": str(run_root / "REPORT.md"),
    }
    print(json.dumps(summary, indent=2))
    return 1 if any(s.status == "failed" for s in index.steps) else 0


# ---- prep-structure (sugar over run-workflow --stop-after prep) --------


def cmd_prep_structure(args: argparse.Namespace) -> int:
    args.stop_after = "prep"
    return cmd_run_workflow(args)


# ---- visualize ---------------------------------------------------------


def cmd_visualize(args: argparse.Namespace) -> int:
    """Run the visualization step against an existing run root."""
    from .run_config import RunConfig
    from .steps import StepContext, visualization

    run_root = Path(args.run_root).resolve()
    if not (run_root / "index.json").is_file():
        sys.stderr.write(f"no index.json at {run_root}\n")
        return 1

    # Build an inline config for visualization. Stays self-contained: we
    # don't read the run's original run_config.json so the user can change
    # visualization knobs without disturbing it.
    viz_cfg = {
        "schema_version": "0.1.0",
        "pipeline_mode": "general_md_prep",
        "interaction_mode": "interactive",
        "input": {"pdb_id": "0000"},  # placeholder; not used by viz step
        "visualization": {
            "mode": "requested",
            "viewer": args.viewer or "auto",
            "checkpoints": args.checkpoints or ["all"],
            "render": args.render or "both",
        },
    }
    cfg = RunConfig.from_dict(viz_cfg)

    # Walk the run for upstream artifacts we can render.
    index = RunIndex.read(run_root / "index.json")
    inputs: list[dict[str, str]] = []
    for s in index.steps:
        for art in (s.artifacts or []):
            if art.get("role") in {"working_pdb", "system_apo_gro", "system_ions_gro", "em_gro"}:
                inputs.append(dict(art))

    step_dir = run_root / "step_10_visualization_cli"
    step_dir.mkdir(parents=True, exist_ok=True)
    ctx = StepContext(
        step_id="step_10_visualization_cli",
        run_root=run_root,
        step_dir=step_dir,
        run_config=cfg,
        inputs=inputs,
    )
    outcome = visualization.run(ctx)
    print(json.dumps({"ok": outcome.ok, "outputs": [o["role"] for o in outcome.outputs]}, indent=2))
    return 0 if outcome.ok else 1


# ---- inspect -----------------------------------------------------------


def cmd_inspect(args: argparse.Namespace) -> int:
    run_root = Path(args.run_root)
    index = RunIndex.read(run_root / "index.json")
    print(f"run_id: {index.run_id}")
    print(f"created: {index.created_at}")
    print(f"updated: {index.updated_at or '(never)'}")
    print(f"run_config_hash: {index.run_config_hash}")
    print("steps:")
    for s in index.steps:
        comp = (s.fingerprint_composite or "")[:16]
        print(f"  {s.step_id:32s} {s.status:12s} fp={comp}")
    report_path = run_root / "REPORT.md"
    if report_path.is_file():
        print()
        print(report_path.read_text())
    return 0


# ---- doctor ------------------------------------------------------------


def cmd_doctor(args: argparse.Namespace) -> int:
    return doctor_mod.cli_main(args)


# ---- install-skills ----------------------------------------------------


_MDAGENT_SKILL_MANIFEST = ".mdagent-install.json"


def _install_skills_core(*, dest_root: Path, dry_run: bool, force: bool) -> dict[str, Any]:
    """Materialize packaged skills into `dest_root` (= `.claude/skills/`).

    Default: each shipped skill dir is rsync'd into dest_root/<name>/
    (existing files overwritten). User-managed sibling skills are left alone.

    --force: in addition, mdagent-managed skill dirs recorded in the previous
    `.mdagent-install.json` (if any) are removed before re-copy, so removing
    a skill from a newer mdagent version → clean state after `--force`.

    Returns a payload dict suitable for embedding in larger CLI output.
    """
    from ._resources import skills_dir

    src = skills_dir()
    shipped_names = sorted(
        p.name for p in src.iterdir()
        if p.is_dir() and (p / "SKILL.md").is_file()
    )

    written: list[str] = []
    removed: list[str] = []
    previous_manifest: dict[str, Any] | None = None
    manifest_path = dest_root / _MDAGENT_SKILL_MANIFEST
    if manifest_path.is_file():
        try:
            previous_manifest = json.loads(manifest_path.read_text())
        except json.JSONDecodeError:
            previous_manifest = None

    if force and not dry_run and previous_manifest is not None:
        for prev_name in previous_manifest.get("managed_skills", []):
            prev_dir = dest_root / prev_name
            if prev_dir.is_dir():
                shutil.rmtree(prev_dir)
                removed.append(str(prev_dir))

    for name in shipped_names:
        skill_src = src / name
        dest_dir = dest_root / name
        if dry_run:
            written.append(f"would write {dest_dir / 'SKILL.md'}")
            continue
        dest_dir.mkdir(parents=True, exist_ok=True)
        for sub in skill_src.iterdir():
            if sub.is_file():
                shutil.copy2(sub, dest_dir / sub.name)
                written.append(str(dest_dir / sub.name))
            else:
                shutil.copytree(sub, dest_dir / sub.name, dirs_exist_ok=True)

    if not dry_run:
        dest_root.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps({
            "manifest_schema_version": "1.0.0",
            "mdagent_version": _installed_version(),
            "managed_skills": shipped_names,
        }, indent=2))

    return {
        "destination": str(dest_root),
        "written": written,
        "removed": removed,
        "managed_skills": shipped_names,
        "dry_run": bool(dry_run),
        "force": bool(force),
    }


def cmd_install_skills(args: argparse.Namespace) -> int:
    """Copy packaged SKILL.md files into a target `.claude/skills/` dir."""
    if args.user:
        dest_root = Path.home() / ".claude" / "skills"
    else:  # args.project is guaranteed by argparse mutex group
        dest_root = Path(args.project).resolve() / ".claude" / "skills"
    payload = _install_skills_core(
        dest_root=dest_root,
        dry_run=args.dry_run,
        force=getattr(args, "force", False),
    )
    print(json.dumps(payload, indent=2))
    return 0


# ---- init-project ------------------------------------------------------


def _starter_kit_dir() -> Path:
    from ._resources import _filesystem_path
    return _filesystem_path("mdagent._resources.starter_kit")


def _load_starter_kit_manifest() -> dict[str, Any]:
    kit = _starter_kit_dir()
    return json.loads((kit / "MANIFEST.json").read_text())


def _materialize_starter_kit(*, dest: Path, force: bool) -> dict[str, Any]:
    """Copy every payload file in the starter kit manifest into `dest`.

    Each file written via temp+atomic rename. Files marked `executable: true`
    get `chmod 0755` after rename.
    """
    kit = _starter_kit_dir()
    manifest = _load_starter_kit_manifest()
    src_files = manifest["files"]

    written: list[str] = []
    for entry in src_files:
        rel = entry["path"]
        src_path = kit / rel
        dest_path = dest / rel
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        if dest_path.exists() and not force:
            # Refuse only triggers at the top level (caller); here we just
            # overwrite (in --force mode), or skip (default if the file exists).
            continue
        # Temp+rename to keep the destination consistent on partial failures.
        tmp = dest_path.with_suffix(dest_path.suffix + ".mdagent_tmp")
        shutil.copy2(src_path, tmp)
        os.replace(tmp, dest_path)
        if entry.get("executable"):
            os.chmod(dest_path, 0o755)
        written.append(str(dest_path))

    # Always write the kit's MANIFEST.json into the target (with our version baked in).
    target_manifest = dict(manifest)
    target_manifest["materialized_at"] = _utc_now_iso()
    target_manifest["materialized_by_mdagent_version"] = _installed_version()
    target_mf_path = dest / "MANIFEST.json"
    target_mf_path.write_text(json.dumps(target_manifest, indent=2))
    written.append(str(target_mf_path))

    return {
        "destination": str(dest),
        "written": written,
        "file_count": len(written),
        "kit_manifest_schema_version": manifest.get("manifest_schema_version"),
    }


def _utc_now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def cmd_init_project(args: argparse.Namespace) -> int:
    """Materialize the starter kit into a target directory."""
    dest = Path(args.dir).resolve()
    if dest.exists() and any(dest.iterdir()) and not args.force:
        sys.stderr.write(
            f"refusing to init non-empty directory: {dest}\n"
            "Re-run with --force to overwrite kit files in place. Files outside the kit are left untouched.\n"
        )
        return 1
    dest.mkdir(parents=True, exist_ok=True)

    kit_payload = _materialize_starter_kit(dest=dest, force=args.force)

    skills_payload: dict[str, Any] = {}
    if not args.no_install_skills:
        skills_payload = _install_skills_core(
            dest_root=dest / ".claude" / "skills",
            dry_run=False,
            force=False,
        )

    payload = {
        "action": "init-project",
        "target": str(dest),
        "kit": kit_payload,
        "install_skills": skills_payload if skills_payload else "skipped (--no-install-skills)",
    }
    print(json.dumps(payload, indent=2))
    return 0


# ---- tutorials ---------------------------------------------------------


def _tutorials_source_dir() -> Path:
    from ._resources import _filesystem_path
    return _filesystem_path("mdagent._resources.tutorials")


def cmd_tutorials_extract(args: argparse.Namespace) -> int:
    """Copy the packaged tutorial bundle (markdown + notebooks + CSS) into DIR.

    If `--with-pdf`, additionally generate PDFs into DIR after extraction.
    """
    src = _tutorials_source_dir()
    dest = Path(args.dir).resolve()
    if dest.exists() and any(dest.iterdir()) and not args.force:
        sys.stderr.write(
            f"refusing to extract into non-empty directory: {dest}\n"
            "Re-run with --force to overwrite bundle files in place. "
            "Files outside the bundle are left untouched.\n"
        )
        return 1
    dest.mkdir(parents=True, exist_ok=True)

    written: list[str] = []
    # Copy every .md, .ipynb, the _shared/ dir, and _build/build.py.
    # Skip __init__.py package markers and __pycache__ caches.
    for src_path in src.rglob("*"):
        if not src_path.is_file():
            continue
        if src_path.name == "__init__.py":
            continue
        if "__pycache__" in src_path.parts:
            continue
        rel = src_path.relative_to(src)
        dest_path = dest / rel
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_path, dest_path)
        written.append(str(dest_path))

    # Generate notebooks alongside the markdown (always).
    nb_payload = _tutorials_build_core(source=dest, out=dest, notebooks=True, pdf=False)

    pdf_payload: dict[str, Any] = {"requested": False}
    if args.with_pdf:
        pdf_payload = _tutorials_build_core(source=dest, out=dest, notebooks=False, pdf=True)
        pdf_payload["requested"] = True

    payload = {
        "action": "tutorials-extract",
        "destination": str(dest),
        "files_copied": len(written),
        "notebooks": {"written": nb_payload.get("notebooks_written", [])},
        "pdfs": pdf_payload,
    }
    print(json.dumps(payload, indent=2))
    return 0


def cmd_tutorials_build(args: argparse.Namespace) -> int:
    """Build notebooks and/or PDFs from a directory of markdown tutorials."""
    payload = _tutorials_build_core(
        source=Path(args.source).resolve(),
        out=Path(args.out).resolve(),
        notebooks=args.notebooks,
        pdf=args.pdf,
    )
    print(json.dumps(payload, indent=2))
    return 0 if not payload.get("pdf_errors") else 1


def _tutorials_build_core(*, source: Path, out: Path, notebooks: bool, pdf: bool) -> dict[str, Any]:
    """Invoke the build pipeline (defined in _resources/tutorials/_build/build.py).

    Imported lazily so that base installs (without tutorials extras) can
    still run extract+notebook generation without requiring weasyprint /
    markdown-it-py to be installed.
    """
    from ._resources.tutorials._build import build as _build_mod
    css_path = source / "_shared" / "pdf.css"
    return _build_mod.build_all(
        source=source,
        out=out,
        notebooks=notebooks,
        pdf=pdf,
        css_path=css_path if css_path.is_file() else None,
    )


# ---- self-test ---------------------------------------------------------


def cmd_self_test_resources(args: argparse.Namespace) -> int:
    """Sanity-check that the packaged resources are discoverable + valid."""
    from . import schemas as schemas_mod
    from ._resources import schemas_dir, skills_dir

    s_dir = schemas_dir(version=schemas_mod.SCHEMA_VERSION)
    schema_files = sorted(s_dir.glob("*.json"))
    schema_loads_ok = 0
    schema_errors: list[str] = []
    for p in schema_files:
        try:
            with open(p) as f:
                data = json.load(f)
            assert isinstance(data, dict)
            schema_loads_ok += 1
        except Exception as e:  # noqa: BLE001
            schema_errors.append(f"{p.name}: {e}")

    sk_dir = skills_dir()
    skill_dirs = sorted(p for p in sk_dir.iterdir() if p.is_dir() and (p / "SKILL.md").is_file())

    payload = {
        "ok": (schema_loads_ok == len(schema_files) and len(schema_files) > 0 and len(skill_dirs) > 0),
        "mdagent_version": _installed_version(),
        "schemas": {
            "dir": str(s_dir),
            "count": len(schema_files),
            "loaded_ok": schema_loads_ok,
            "errors": schema_errors,
        },
        "skills": {
            "dir": str(sk_dir),
            "count": len(skill_dirs),
            "names": [p.name for p in skill_dirs],
        },
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"mdagent self-test resources: {'OK' if payload['ok'] else 'FAILED'}")
        print(f"  schemas: {payload['schemas']['count']} ({payload['schemas']['loaded_ok']} loaded)")
        print(f"  skills:  {payload['skills']['count']} ({', '.join(payload['skills']['names'])})")
    return 0 if payload["ok"] else 1


# ---- parser ------------------------------------------------------------


def _add_run_workflow_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--config", help="Path to a run_config.json. If omitted, build one from the flags below.")
    p.add_argument("--runs-root", required=True, help="Where to write the run directory.")
    p.add_argument("--run-id", help="Optional explicit run id. Defaults to a timestamped one.")
    inp = p.add_mutually_exclusive_group()
    inp.add_argument("--pdb-id", help="RCSB PDB ID, e.g. 1AKI.")
    inp.add_argument("--structure-path", help="Local PDB or mmCIF file path.")
    p.add_argument("--pipeline-mode", choices=["tutorial_reproduction", "general_md_prep"], default="tutorial_reproduction")
    p.add_argument("--interaction-mode", choices=["interactive", "noninteractive_defaults", "strict_config_required"], default="noninteractive_defaults")
    p.add_argument("--force-field", default="oplsaa")
    p.add_argument("--water-model", default="spc")
    p.add_argument("--box-geometry", choices=["dodecahedron", "cubic", "octahedron"], default="dodecahedron")
    p.add_argument("--box-padding-nm", type=float, default=1.0)
    p.add_argument("--ion-mode", choices=["neutralize_only", "physiological_salt", "custom"], default="neutralize_only")
    p.add_argument("--cation", default="NA")
    p.add_argument("--anion", default="CL")
    p.add_argument("--random-seed", type=int, default=42)
    p.add_argument("--em-step-cap", type=int, default=1000)
    p.add_argument("--em-fmax-tol", type=float, default=1000.0)
    p.add_argument("--viz-mode", choices=["disabled", "default", "requested"], default="disabled")
    p.add_argument("--viz-viewer", choices=["vmd", "pymol", "nglview", "auto"])
    p.add_argument("--viz-checkpoints", nargs="*", choices=["prep", "topology", "solvated", "em", "all"])
    p.add_argument("--stop-after", choices=list(_PIPELINE_STOPPING_POINTS.keys()),
                   help="Stop the pipeline after the named phase.")
    p.add_argument("--skip-network-check", action="store_true",
                   help="Don't doctor-check RCSB connectivity (you'll see the failure later if it's needed).")
    p.add_argument("--skip-viewer-check", action="store_true",
                   help="Don't doctor-check the visualization viewer.")
    p.add_argument("--skip-gmx-version-check", action="store_true",
                   help="Don't doctor-check the gmx version against the prompt catalog.")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mdagent", description="mdagent — agentic MD pipeline driver.")
    p.add_argument("-V", "--version", action="version", version=f"mdagent {_installed_version()}")
    sub = p.add_subparsers(dest="cmd", required=True)

    # run-workflow
    rw = sub.add_parser("run-workflow", help="Run the full pipeline on a PDB.")
    _add_run_workflow_args(rw)
    rw.set_defaults(func=cmd_run_workflow)

    # prep-structure
    ps = sub.add_parser("prep-structure", help="Run ingest + classify + prep only (no gmx).")
    _add_run_workflow_args(ps)
    ps.set_defaults(func=cmd_prep_structure)

    # visualize
    vz = sub.add_parser("visualize", help="Render checkpoint snapshots against a completed run.")
    vz.add_argument("--run-root", required=True)
    vz.add_argument("--viewer", choices=["vmd", "pymol", "nglview", "auto"])
    vz.add_argument("--checkpoints", nargs="*", choices=["prep", "topology", "solvated", "em", "all"])
    vz.add_argument("--render", choices=["png", "state_only", "both"])
    vz.set_defaults(func=cmd_visualize)

    # inspect
    ins = sub.add_parser("inspect", help="Print a run's index.json + REPORT.md.")
    ins.add_argument("--run-root", required=True)
    ins.set_defaults(func=cmd_inspect)

    # doctor
    doc = sub.add_parser("doctor", help="Preflight checks (env, deps, versions).")
    doc.add_argument("--json", action="store_true")
    doc.add_argument("--min-version", help="Minimum mdagent version required by the caller.")
    doc.add_argument("--skill-name")
    doc.add_argument("--skill-version")
    doc.add_argument("--gmx-required", action="store_true", help="Require GROMACS on PATH.")
    doc.add_argument("--check-network", action="store_true")
    doc.add_argument("--check-viewers", action="store_true")
    doc.set_defaults(func=cmd_doctor)

    # install-skills
    sk = sub.add_parser("install-skills", help="Copy packaged Claude skills into a .claude/skills/ dir.")
    sk_target = sk.add_mutually_exclusive_group(required=True)
    sk_target.add_argument("--user", action="store_true", help="Install to ~/.claude/skills/")
    sk_target.add_argument("--project", metavar="DIR", help="Install to DIR/.claude/skills/")
    sk.add_argument("--dry-run", action="store_true")
    sk.add_argument("--force", action="store_true",
                    help="Remove previously-managed mdagent skill dirs before copying. "
                         "Sibling user-owned skill dirs are left alone.")
    sk.set_defaults(func=cmd_install_skills)

    # init-project
    ip = sub.add_parser("init-project", help="Materialize the starter kit into a fresh directory.")
    ip.add_argument("dir", metavar="DIR", help="Target directory (created if it doesn't exist).")
    ip.add_argument("--force", action="store_true",
                    help="Overwrite kit files in DIR. Files outside the kit are left alone.")
    ip.add_argument("--no-install-skills", action="store_true",
                    help="Skip the implicit `install-skills --project DIR` call.")
    ip.set_defaults(func=cmd_init_project)

    # tutorials
    tu = sub.add_parser("tutorials", help="Tutorial-bundle helpers (extract + build).")
    tu_sub = tu.add_subparsers(dest="tutorials_target", required=True)

    tu_ext = tu_sub.add_parser("extract", help="Copy the packaged tutorial bundle into DIR.")
    tu_ext.add_argument("dir", metavar="DIR", help="Target directory.")
    tu_ext.add_argument("--with-pdf", action="store_true", help="Also generate PDFs (requires the 'tutorials' extra).")
    tu_ext.add_argument("--force", action="store_true", help="Overwrite bundle files in DIR.")
    tu_ext.set_defaults(func=cmd_tutorials_extract)

    tu_build = tu_sub.add_parser("build", help="Build notebooks (and/or PDFs) from .md tutorials.")
    tu_build.add_argument("--source", required=True, help="Directory of .md tutorial files.")
    tu_build.add_argument("--out", required=True, help="Directory to write outputs into.")
    tu_build.add_argument("--notebooks", action="store_true", default=True)
    tu_build.add_argument("--no-notebooks", dest="notebooks", action="store_false")
    tu_build.add_argument("--pdf", action="store_true", default=False)
    tu_build.set_defaults(func=cmd_tutorials_build)

    # self-test
    st = sub.add_parser("self-test", help="Run an internal sanity check.")
    st_sub = st.add_subparsers(dest="self_test_target", required=True)
    st_res = st_sub.add_parser("resources", help="Verify schemas + skills are discoverable.")
    st_res.add_argument("--json", action="store_true")
    st_res.set_defaults(func=cmd_self_test_resources)

    return p


def main(argv: list[str] | None = None) -> int:
    p = build_parser()
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
