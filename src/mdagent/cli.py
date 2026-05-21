"""Command-line entrypoint for mdagent.

Exposed as the `mdagent` console script via `[project.scripts]` in
pyproject.toml. The skills (`md-run-workflow`, `md-prep-structure`,
`md-visualize`) invoke this CLI directly — no `cd` into a checkout
required.
"""

from __future__ import annotations

import argparse
import json
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


def cmd_install_skills(args: argparse.Namespace) -> int:
    """Copy packaged SKILL.md files into a target `.claude/skills/` dir."""
    from ._resources import skills_dir
    if args.user:
        dest_root = Path.home() / ".claude" / "skills"
    else:  # args.project is guaranteed by argparse mutex group
        dest_root = Path(args.project).resolve() / ".claude" / "skills"

    src = skills_dir()
    written: list[str] = []
    skipped: list[str] = []
    for skill_path in sorted(src.iterdir()):
        if not skill_path.is_dir() or not (skill_path / "SKILL.md").is_file():
            continue
        dest_dir = dest_root / skill_path.name
        if args.dry_run:
            written.append(f"would write {dest_dir / 'SKILL.md'}")
            continue
        dest_dir.mkdir(parents=True, exist_ok=True)
        for sub in skill_path.iterdir():
            if sub.is_file():
                shutil.copy2(sub, dest_dir / sub.name)
                written.append(str(dest_dir / sub.name))
            else:
                shutil.copytree(sub, dest_dir / sub.name, dirs_exist_ok=True)

    payload = {"destination": str(dest_root), "written": written, "skipped": skipped, "dry_run": bool(args.dry_run)}
    print(json.dumps(payload, indent=2))
    return 0


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
    sk.set_defaults(func=cmd_install_skills)

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
