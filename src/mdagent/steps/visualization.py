"""Visualization — VMD-first, PyMOL/NGLview fallback, scripts-always.

Per R3-25 (checkpoint-triggered, not terminal) and R3-23/R3-24/R4-22
(mode-gated, best-effort, scripts-always):

  - Mode-gated: `visualization.mode in {disabled, default, requested}`. The
    `disabled` mode is a no-op. `default` and `requested` produce
    checkpoint snapshots for each enabled checkpoint.

  - Viewer detection order: VMD → PyMOL → NGLview. `auto` walks the list;
    explicit choices honor the user's pick. If the chosen viewer is
    unavailable the step records `skipped: renderer_unavailable` and
    still emits the script (Tcl for VMD, PML for PyMOL).

  - Best-effort render: try `vmd -dispdev text -e script.tcl` for VMD,
    `pymol -cq -r script.pml` for PyMOL. If the binary exits non-zero or
    no PNG is produced, mark images skipped but keep scripts.

  - Checkpoints: subset of {prep, topology, solvated, em}. Each gets its
    own subdir under `step_07_visualization/<checkpoint>/`.

  - Resolves artifacts by role from upstream step reports (the orchestrator
    populates ctx.inputs with everything it has produced so far).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..hashing import sha256_file, sha256_text
from .base import StepContext, StepOutcome, find_input


# Roles a checkpoint refers to (the artifact name produced by an upstream step).
_CHECKPOINT_ROLE: dict[str, str] = {
    "prep": "working_pdb",
    "topology": "system_apo_gro",
    "solvated": "system_ions_gro",
    "em": "em_gro",
}


@dataclass
class ViewerProbe:
    name: str
    executable: str | None
    available: bool
    failure_reason: str | None = None


def _probe_vmd() -> ViewerProbe:
    exe = shutil.which("vmd")
    return ViewerProbe(name="vmd", executable=exe, available=exe is not None,
                       failure_reason=None if exe else "vmd not on PATH")


def _probe_pymol() -> ViewerProbe:
    # On macOS PyMOL frequently lives as `pymol` after `brew install pymol`.
    exe = shutil.which("pymol")
    return ViewerProbe(name="pymol", executable=exe, available=exe is not None,
                       failure_reason=None if exe else "pymol not on PATH")


def _probe_nglview() -> ViewerProbe:
    # NGLview is a Python package, not a CLI — check importability.
    try:
        import nglview  # type: ignore
        return ViewerProbe(name="nglview", executable=None, available=True)
    except ImportError:
        return ViewerProbe(name="nglview", executable=None, available=False, failure_reason="nglview not importable")


def probe_viewers() -> dict[str, ViewerProbe]:
    return {"vmd": _probe_vmd(), "pymol": _probe_pymol(), "nglview": _probe_nglview()}


def _select_viewer(requested: str | None) -> ViewerProbe | None:
    probes = probe_viewers()
    if requested in (None, "auto"):
        for name in ("vmd", "pymol", "nglview"):
            if probes[name].available:
                return probes[name]
        return None
    return probes.get(requested)


def _vmd_tcl(structure_path: Path, snapshot_png: Path) -> str:
    """Generate a tiny Tcl script that loads the structure + renders a snapshot."""
    return f"""\
# mdagent VMD visualization script
mol new {{{structure_path}}} type {{{structure_path.suffix.lstrip('.')}}} first 0 last -1 step 1 waitfor all
mol modstyle 0 0 NewCartoon
mol addrep 0
mol modselect 1 0 water
mol modstyle 1 0 Lines
mol modcolor 1 0 ColorID 4
mol addrep 0
mol modselect 2 0 ions
mol modstyle 2 0 VDW
mol modcolor 2 0 Type
display projection Orthographic
display rendermode GLSL
axes location LowerLeft
color Display Background white
render TachyonInternal {{{snapshot_png}}}
quit
"""


def _pymol_pml(structure_path: Path, snapshot_png: Path) -> str:
    return f"""\
# mdagent PyMOL visualization script
load {structure_path}
hide everything
show cartoon, polymer
show lines, resn HOH+SOL+WAT+TIP3+SPC
show spheres, name NA+CL+K+MG+ZN
color cyan, polymer
color blue, resn NA
color green, resn CL
bg_color white
ray 1024, 768
png {snapshot_png}
"""


def _resolve_artifact(inputs: list[dict[str, str]], role: str) -> Path | None:
    ref = find_input(inputs, role)
    if ref is None:
        return None
    return Path(ref["artifact_uri"].removeprefix("local://"))


def _render(viewer: ViewerProbe, script_path: Path, snapshot_png: Path, cwd: Path, timeout_s: float = 60.0) -> tuple[bool, str | None]:
    """Run the viewer headlessly. Returns (succeeded, failure_reason)."""
    if viewer.name == "vmd" and viewer.executable:
        argv = [viewer.executable, "-dispdev", "text", "-e", str(script_path)]
    elif viewer.name == "pymol" and viewer.executable:
        argv = [viewer.executable, "-cq", "-r", str(script_path)]
    elif viewer.name == "nglview":
        # NGLview is interactive-notebook-only; no headless render path in v0.
        return False, "nglview has no headless render path in v0; script not applicable"
    else:
        return False, f"viewer {viewer.name} not invocable"

    try:
        proc = subprocess.run(argv, cwd=str(cwd), capture_output=True, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        return False, "render timed out"
    except FileNotFoundError as e:
        return False, f"viewer binary missing: {e}"

    if proc.returncode != 0:
        return False, f"viewer exited {proc.returncode}: {proc.stderr.decode(errors='replace')[-500:]}"
    if not snapshot_png.is_file() or snapshot_png.stat().st_size == 0:
        return False, "renderer ran but produced no PNG"
    return True, None


def run(ctx: StepContext) -> StepOutcome:
    cfg = ctx.run_config
    mode = cfg.get_field("visualization.mode") or "disabled"
    if mode == "disabled":
        return StepOutcome(extra={"mode": "disabled", "skipped": True})

    requested_viewer = cfg.get_field("visualization.viewer")  # vmd|pymol|nglview|auto|None
    requested_checkpoints = cfg.get_field("visualization.checkpoints") or ["solvated", "em"]
    if "all" in requested_checkpoints:
        requested_checkpoints = list(_CHECKPOINT_ROLE.keys())

    viewer = _select_viewer(requested_viewer)
    viewer_status: dict[str, Any] = {
        "requested_viewer": requested_viewer or "auto",
        "selected_viewer": viewer.name if viewer else None,
        "all_probes": {name: {"available": p.available, "failure_reason": p.failure_reason}
                       for name, p in probe_viewers().items()},
    }

    outputs: list[dict[str, str]] = []
    warnings: list[dict[str, Any]] = []
    rendered: list[dict[str, Any]] = []

    for checkpoint in requested_checkpoints:
        role = _CHECKPOINT_ROLE.get(checkpoint)
        if role is None:
            warnings.append({"class": "visualization", "severity": "info",
                             "message": f"unknown checkpoint: {checkpoint}"})
            continue
        artifact = _resolve_artifact(ctx.inputs, role)
        if artifact is None or not artifact.is_file():
            warnings.append({"class": "visualization", "severity": "info",
                             "message": f"checkpoint {checkpoint} unavailable (role={role} not produced)"})
            rendered.append({"checkpoint": checkpoint, "status": "checkpoint_artifact_missing"})
            continue

        cp_dir = ctx.step_dir / checkpoint
        cp_dir.mkdir(parents=True, exist_ok=True)
        png = cp_dir / "snapshot.png"

        script_paths: list[Path] = []
        # Always write a VMD Tcl script (useful for the user even if PyMOL is selected).
        tcl_path = cp_dir / "visualize.vmd"
        tcl_path.write_text(_vmd_tcl(artifact, png))
        script_paths.append(tcl_path)
        # When PyMOL is selected (or available), also write a PML script.
        if viewer and viewer.name == "pymol":
            pml_path = cp_dir / "visualize.pml"
            pml_path.write_text(_pymol_pml(artifact, png))
            script_paths.append(pml_path)

        render_probe: dict[str, Any] = {"checkpoint": checkpoint, "viewer": None, "rendered": False, "reason": None}
        if viewer is None:
            render_probe["reason"] = "no_viewer_available"
            warnings.append({"class": "visualization", "severity": "info",
                             "message": f"no viewer available; wrote scripts for {checkpoint}",
                             "context": viewer_status})
        else:
            render_probe["viewer"] = viewer.name
            ok, reason = _render(viewer, script_paths[-1], png, cp_dir)
            render_probe["rendered"] = ok
            render_probe["reason"] = reason
            if not ok:
                warnings.append({"class": "visualization", "severity": "info",
                                 "message": f"viewer {viewer.name} did not render {checkpoint}: {reason}"})

        rendered.append(render_probe)
        # Record artifacts produced for this checkpoint.
        for sp in script_paths:
            outputs.append({
                "artifact_uri": f"local://{sp}",
                "content_hash": sha256_file(sp),
                "role": f"viz_script_{checkpoint}_{sp.suffix.lstrip('.')}",
            })
        if png.is_file() and png.stat().st_size > 0:
            outputs.append({
                "artifact_uri": f"local://{png}",
                "content_hash": sha256_file(png),
                "role": f"viz_snapshot_{checkpoint}",
            })

    probe_path = ctx.step_dir / "render_probe.json"
    probe_path.write_text(json.dumps({"viewer_status": viewer_status, "rendered": rendered}, indent=2, sort_keys=True))
    outputs.append({
        "artifact_uri": f"local://{probe_path}",
        "content_hash": sha256_text(probe_path.read_text()),
        "role": "render_probe",
    })

    return StepOutcome(
        outputs=outputs,
        warnings=warnings,
        extra={"mode": mode, "viewer_status": viewer_status, "checkpoints": requested_checkpoints, "rendered": rendered},
    )
