"""Doctor — config-aware preflight checks.

Two entry points:
  - `check_for_run(cfg, planned_step_ids, ...)` — called by the orchestrator
    before a run. Derives required checks from the planned step list +
    config, so e.g. `prep-structure` (no gmx steps) doesn't require gmx.
  - `cli_main(args)` — the `mdagent doctor` subcommand. Same engine,
    explicit flags.

Output:
  - Default human-readable text on stdout.
  - `--json` emits a single JSON object on stdout (nothing else).
  - Exit code 0 if `result.ok`, 1 otherwise.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Any

from .run_config import RunConfig

# Pipeline steps that require GROMACS on PATH (anything that calls `gmx`).
GMX_REQUIRING_STEPS: frozenset[str] = frozenset({
    "step_04_topology",
    "step_05_solvation",
    "step_06_em",
    "step_07_nvt",
    "step_08_npt",
    "step_09_production",
    "step_10_analysis",
})

# Supported gmx versions for the v0 Pdb2GmxPromptRecognizer.
_PROMPT_CATALOG_VERSIONS: frozenset[str] = frozenset({"2026.2"})


@dataclass
class CheckEntry:
    status: str  # "ok" | "fail" | "skipped" | "warning"
    detail: dict[str, Any] = field(default_factory=dict)
    suggestion: str | None = None


@dataclass
class DoctorResult:
    ok: bool
    checks: dict[str, CheckEntry] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "checks": {k: asdict(v) for k, v in self.checks.items()},
            "errors": [
                {"name": k, "detail": v.detail, "suggestion": v.suggestion}
                for k, v in self.checks.items()
                if v.status == "fail"
            ],
        }


def _mdagent_version() -> str:
    try:
        from importlib.metadata import version
        return version("mdagent")
    except Exception:
        from . import __version__
        return __version__


def _gmx_version_info() -> tuple[str | None, str | None, str | None]:
    """Return (version_str, exe_path, raw_stdout) or (None, None, None) if gmx not found."""
    exe = shutil.which("gmx")
    if exe is None:
        return None, None, None
    try:
        out = subprocess.run(["gmx", "--version"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None, exe, None
    text = out.stdout + out.stderr
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("GROMACS version:"):
            return line.split(":", 1)[1].strip(), exe, text
    return None, exe, text


def _network_reachable(url: str = "https://files.rcsb.org/", timeout: float = 5.0) -> bool:
    try:
        urllib.request.urlopen(url, timeout=timeout)
        return True
    except (OSError, urllib.error.URLError, socket.timeout):
        return False


def _viewer_available(name: str) -> tuple[bool, str | None]:
    """Return (binary_on_path, executable_path)."""
    if name == "nglview":
        try:
            import nglview  # noqa: F401
            return True, None
        except ImportError:
            return False, None
    exe = shutil.which(name)
    return exe is not None, exe


def _compare_semver(installed: str, required: str) -> bool:
    """Return True iff installed >= required. Handles "X.Y.Z" only (no pre-release tags)."""
    def parts(v: str) -> tuple[int, ...]:
        return tuple(int(x) for x in v.split(".") if x.isdigit())
    try:
        return parts(installed) >= parts(required)
    except Exception:
        return False


def check_for_run(
    cfg: RunConfig,
    *,
    planned_step_ids: set[str] | frozenset[str],
    skip_gmx_version: bool = False,
    skip_network: bool = False,
    skip_viewer: bool = False,
) -> DoctorResult:
    """Config-aware doctor invocation called by the orchestrator."""
    checks: dict[str, CheckEntry] = {}

    # mdagent version always recorded.
    checks["mdagent_version"] = CheckEntry(status="ok", detail={"version": _mdagent_version()})

    gmx_required = bool(set(planned_step_ids) & GMX_REQUIRING_STEPS)
    gmx_version, gmx_path, _ = _gmx_version_info()
    if gmx_required:
        if gmx_path is None:
            checks["gmx_available"] = CheckEntry(
                status="fail",
                detail={"required": True},
                suggestion="Install GROMACS: brew install gromacs (macOS) or your OS package manager.",
            )
        else:
            checks["gmx_available"] = CheckEntry(
                status="ok",
                detail={"version": gmx_version, "path": gmx_path, "required": True},
            )
            if not skip_gmx_version:
                supported = gmx_version in _PROMPT_CATALOG_VERSIONS or (gmx_version or "").startswith("2026.")
                checks["gmx_prompt_catalog"] = CheckEntry(
                    status="ok" if supported else "warning",
                    detail={
                        "installed": gmx_version,
                        "catalog_versions": sorted(_PROMPT_CATALOG_VERSIONS),
                        "supported": supported,
                    },
                    suggestion=None if supported else (
                        f"Pdb2GmxPromptRecognizer was probed against {sorted(_PROMPT_CATALOG_VERSIONS)}. "
                        f"Installed gmx is {gmx_version}; prompt drift may cause topology failures."
                    ),
                )
            else:
                checks["gmx_prompt_catalog"] = CheckEntry(status="skipped", detail={"reason": "skip_gmx_version_check"})
    else:
        checks["gmx_available"] = CheckEntry(status="skipped", detail={"required": False})

    # Network — only when the run plans to fetch from RCSB.
    needs_network = (
        cfg.get_field("input.pdb_id") is not None
        and cfg.get_field("input.structure_path") is None
    )
    if needs_network and not skip_network:
        ok = _network_reachable("https://files.rcsb.org/")
        checks["rcsb_reachable"] = CheckEntry(
            status="ok" if ok else "fail",
            detail={"checked_url": "https://files.rcsb.org/"},
            suggestion=None if ok else "RCSB unreachable. Provide a local structure via input.structure_path or check connectivity.",
        )
    elif needs_network:
        checks["rcsb_reachable"] = CheckEntry(status="skipped", detail={"reason": "skip_network_check"})
    else:
        checks["rcsb_reachable"] = CheckEntry(status="skipped", detail={"reason": "no_pdb_id"})

    # PROPKA — only when the policy explicitly requests it AND the pipeline
    # will run prep (which is always in v0, but be explicit).
    if cfg.get_field("protonation_policy") == "propka" and "step_03_structure_prep" in planned_step_ids:
        try:
            from . import propka_helper
            available = propka_helper.propka_available()
        except ImportError:
            available = False
        checks["propka"] = CheckEntry(
            status="ok" if available else "warning",
            detail={"installed": available, "version": (propka_helper.propka_version() if available else None)},
            suggestion=None if available else (
                "protonation_policy=propka but the `propka` package is not installed. "
                "Install via: uv tool install --force --with propka git+https://github.com/<user>/MDSimulationAgent@<tag>. "
                "Falling back to fixed pH-7 defaults."
            ),
        )

    # Viewer — only when render requires it.
    viz_mode = cfg.get_field("visualization.mode") or "disabled"
    render = cfg.get_field("visualization.render") or "state_only"
    needs_renderer = viz_mode != "disabled" and render in ("png", "both")
    if needs_renderer and not skip_viewer:
        viewer = cfg.get_field("visualization.viewer") or "auto"
        if viewer == "auto":
            available_viewers = [n for n in ("vmd", "pymol", "nglview") if _viewer_available(n)[0]]
            available = bool(available_viewers)
        else:
            available, _ = _viewer_available(viewer)
        checks["viewer_renderable"] = CheckEntry(
            status="ok" if available else "fail",
            detail={"requested_viewer": viewer, "render": render},
            suggestion=None if available else "No viewer found. Install VMD: brew install --cask vmd (macOS).",
        )
    elif needs_renderer:
        checks["viewer_renderable"] = CheckEntry(status="skipped", detail={"reason": "skip_viewer_check"})
    else:
        checks["viewer_renderable"] = CheckEntry(
            status="skipped",
            detail={"reason": f"visualization.mode={viz_mode} render={render} — no renderer needed"},
        )

    ok = all(c.status != "fail" for c in checks.values())
    return DoctorResult(ok=ok, checks=checks)


def standalone(
    *,
    min_version: str | None = None,
    skill_name: str | None = None,
    skill_version: str | None = None,
    gmx_required: bool = False,
    check_network: bool = False,
    check_viewers: bool = False,
) -> DoctorResult:
    """The CLI `mdagent doctor` entry point (no run_config)."""
    checks: dict[str, CheckEntry] = {}
    installed = _mdagent_version()
    checks["mdagent_version"] = CheckEntry(status="ok", detail={"version": installed})

    if min_version is not None:
        ok = _compare_semver(installed, min_version)
        checks["min_version"] = CheckEntry(
            status="ok" if ok else "fail",
            detail={"installed": installed, "required": min_version},
            suggestion=None if ok else (
                f"mdagent {installed} is older than required {min_version}. "
                "Upgrade: uv tool install --force git+https://github.com/<user>/MDSimulationAgent@<newer_tag>"
            ),
        )

    if skill_name and skill_version:
        # In v0 every skill that ships in the package is current; in future
        # we can compare against a CLI-side `supported_skill_versions` table.
        checks["skill_version"] = CheckEntry(
            status="ok",
            detail={"skill_name": skill_name, "skill_version": skill_version},
        )

    if gmx_required:
        gmx_version, gmx_path, _ = _gmx_version_info()
        if gmx_path is None:
            checks["gmx_available"] = CheckEntry(
                status="fail",
                detail={"required": True},
                suggestion="Install GROMACS: brew install gromacs",
            )
        else:
            supported = (gmx_version in _PROMPT_CATALOG_VERSIONS) or (gmx_version or "").startswith("2026.")
            checks["gmx_available"] = CheckEntry(
                status="ok" if supported else "warning",
                detail={"version": gmx_version, "path": gmx_path, "supported_for_recognizer": supported},
                suggestion=None if supported else (
                    f"Installed gmx is {gmx_version}; prompt catalog probed against {sorted(_PROMPT_CATALOG_VERSIONS)}."
                ),
            )

    if check_network:
        ok = _network_reachable()
        checks["rcsb_reachable"] = CheckEntry(
            status="ok" if ok else "fail",
            detail={"checked_url": "https://files.rcsb.org/"},
            suggestion=None if ok else "RCSB unreachable.",
        )

    if check_viewers:
        details = {n: {"available": _viewer_available(n)[0]} for n in ("vmd", "pymol", "nglview")}
        any_avail = any(d["available"] for d in details.values())
        checks["viewers"] = CheckEntry(
            status="ok" if any_avail else "warning",
            detail=details,
            suggestion=None if any_avail else "No viewers detected. brew install --cask vmd (macOS) is the easiest.",
        )

    ok = all(c.status != "fail" for c in checks.values())
    return DoctorResult(ok=ok, checks=checks)


def _format_human(result: DoctorResult) -> str:
    lines: list[str] = []
    lines.append(f"mdagent doctor: {'OK' if result.ok else 'FAILED'}")
    for name, entry in result.checks.items():
        marker = {"ok": "✓", "fail": "✗", "warning": "!", "skipped": "-"}.get(entry.status, "?")
        lines.append(f"  {marker} {name}: {entry.status}")
        for k, v in entry.detail.items():
            lines.append(f"      {k}: {v}")
        if entry.suggestion:
            lines.append(f"      → {entry.suggestion}")
    return "\n".join(lines)


def cli_main(args) -> int:  # invoked by mdagent.cli with parsed argparse namespace
    """`mdagent doctor` subcommand entrypoint."""
    result = standalone(
        min_version=args.min_version,
        skill_name=args.skill_name,
        skill_version=args.skill_version,
        gmx_required=args.gmx_required,
        check_network=args.check_network,
        check_viewers=args.check_viewers,
    )
    if args.json:
        sys.stdout.write(json.dumps(result.to_dict(), indent=2, sort_keys=False) + "\n")
    else:
        sys.stdout.write(_format_human(result) + "\n")
    return 0 if result.ok else 1
