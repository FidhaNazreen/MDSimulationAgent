"""Command-line entrypoint for mdagent.

Used by the Claude skills (`md:run-workflow`, etc.) to invoke the v0
pipeline from a shell. Argparse-based; no external CLI dep.

Examples:
  python -m mdagent run-workflow --config run_config.json --runs-root runs/
  python -m mdagent run-workflow --pdb-id 1AKI --runs-root runs/ --run-id demo
  python -m mdagent inspect --run-root runs/demo
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .orchestrator import run_workflow
from .run_index import RunIndex


def _build_minimal_config(args: argparse.Namespace) -> dict[str, Any]:
    """Construct a minimal valid run_config from CLI args."""
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
        "tool_versions": {"gromacs": args.gmx_version},
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


def cmd_run_workflow(args: argparse.Namespace) -> int:
    if args.config:
        cfg_path = Path(args.config)
    else:
        cfg = _build_minimal_config(args)
        runs_root = Path(args.runs_root).resolve()
        runs_root.mkdir(parents=True, exist_ok=True)
        cfg_path = runs_root / "_inline_run_config.json"
        cfg_path.write_text(json.dumps(cfg, indent=2, sort_keys=True))

    run_root, index = run_workflow(
        run_config_path=cfg_path,
        runs_root=args.runs_root,
        run_id=args.run_id,
    )

    summary = {
        "run_root": str(run_root),
        "step_statuses": {s.step_id: s.status for s in index.steps},
        "report_path": str(run_root / "REPORT.md"),
    }
    print(json.dumps(summary, indent=2))

    # Exit non-zero if any step failed (so calling skill can detect).
    any_failed = any(s.status == "failed" for s in index.steps)
    return 1 if any_failed else 0


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


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m mdagent", description="mdagent — agentic MD pipeline driver.")
    sub = p.add_subparsers(dest="cmd", required=True)

    # run-workflow
    rw = sub.add_parser("run-workflow", help="Run the full v0 pipeline on a PDB.")
    rw.add_argument("--config", help="Path to a run_config.json. If omitted, build one from the flags below.")
    rw.add_argument("--runs-root", required=True, help="Where to write the run directory.")
    rw.add_argument("--run-id", help="Optional explicit run id. Defaults to a timestamped one.")
    inp = rw.add_mutually_exclusive_group()
    inp.add_argument("--pdb-id", help="RCSB PDB ID, e.g. 1AKI.")
    inp.add_argument("--structure-path", help="Local PDB or mmCIF file path.")
    rw.add_argument("--pipeline-mode", choices=["tutorial_reproduction", "general_md_prep"], default="tutorial_reproduction")
    rw.add_argument("--interaction-mode", choices=["interactive", "noninteractive_defaults", "strict_config_required"], default="noninteractive_defaults")
    rw.add_argument("--force-field", default="oplsaa")
    rw.add_argument("--water-model", default="spc")
    rw.add_argument("--box-geometry", choices=["dodecahedron", "cubic", "octahedron"], default="dodecahedron")
    rw.add_argument("--box-padding-nm", type=float, default=1.0)
    rw.add_argument("--ion-mode", choices=["neutralize_only", "physiological_salt", "custom"], default="neutralize_only")
    rw.add_argument("--cation", default="NA")
    rw.add_argument("--anion", default="CL")
    rw.add_argument("--random-seed", type=int, default=42)
    rw.add_argument("--em-step-cap", type=int, default=1000)
    rw.add_argument("--em-fmax-tol", type=float, default=1000.0)
    rw.add_argument("--viz-mode", choices=["disabled", "default", "requested"], default="disabled")
    rw.add_argument("--viz-viewer", choices=["vmd", "pymol", "nglview", "auto"])
    rw.add_argument("--viz-checkpoints", nargs="*", choices=["prep", "topology", "solvated", "em", "all"])
    rw.add_argument("--gmx-version", default="2026.2")
    rw.set_defaults(func=cmd_run_workflow)

    # inspect
    ins = sub.add_parser("inspect", help="Print a run's index.json + REPORT.md.")
    ins.add_argument("--run-root", required=True)
    ins.set_defaults(func=cmd_inspect)

    return p


def main(argv: list[str] | None = None) -> int:
    p = build_parser()
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
