"""Analysis — RMSD / Rg / RMSF / H-bonds + NVT/NPT thermodynamics.

Drives standard GROMACS analysis tools against the production trajectory
and the equilibration energy files:

  - `gmx rms`    → RMSD vs. starting structure (Backbone group by default).
  - `gmx gyrate` → radius of gyration (Protein).
  - `gmx rmsf`   → per-residue root-mean-square fluctuation.
  - `gmx hbond`  → intramolecular protein–protein H-bond count over time
                   (best-effort; skipped silently if unavailable).
  - `gmx energy` → Temperature curve from NVT (.edr) + Pressure/Density
                   curves from NPT (.edr). Surfaced as the thermodynamic
                   summary in the report.

Emits an `analysis.json` aggregating the time series + summary stats
plus the raw `.xvg` outputs for downstream plotting.
"""

from __future__ import annotations

import json
import os
import statistics
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..hashing import sha256_file, sha256_text
from .base import StepContext, StepOutcome, find_input


def _run_gmx(argv: list[str], cwd: Path, *, stdin_bytes: bytes | None = None, timeout: float = 600.0):
    env = os.environ.copy()
    env.setdefault("LC_ALL", "C")
    env.setdefault("LANG", "C")
    t0 = time.monotonic()
    proc = subprocess.run(argv, cwd=str(cwd), env=env, input=stdin_bytes, capture_output=True, timeout=timeout)
    return proc, time.monotonic() - t0


def _parse_xvg(path: Path) -> list[tuple[float, ...]]:
    """Read a GROMACS .xvg file. Skip lines starting with `#` or `@`.
    Returns a list of tuples (one per data row), each holding floats.
    """
    rows: list[tuple[float, ...]] = []
    if not path.is_file():
        return rows
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("@"):
            continue
        parts = line.split()
        try:
            rows.append(tuple(float(x) for x in parts))
        except ValueError:
            continue
    return rows


def _summary(values: list[float]) -> dict[str, float]:
    if not values:
        return {"n": 0}
    return {
        "n": len(values),
        "mean": statistics.fmean(values),
        "stdev": statistics.pstdev(values) if len(values) > 1 else 0.0,
        "min": min(values),
        "max": max(values),
    }


def run(ctx: StepContext) -> StepOutcome:
    prod_xtc = find_input(ctx.inputs, "production_xtc")
    prod_tpr = find_input(ctx.inputs, "production_tpr")
    if prod_xtc is None or prod_tpr is None:
        # If production didn't run we have nothing to analyze. That's fine —
        # mark as skipped via the orchestrator (it short-circuits when
        # production.enabled=false). If we get here without inputs the
        # production step failed; emit a structured failure.
        return StepOutcome(failure={
            "code": "ConfigMissing",
            "message": "production trajectory unavailable (production may have been disabled or failed)",
        })

    xtc_path = Path(prod_xtc["artifact_uri"].removeprefix("local://"))
    tpr_path = Path(prod_tpr["artifact_uri"].removeprefix("local://"))

    # Copy inputs into the step dir so analysis is self-contained.
    local_xtc = ctx.step_dir / "production.xtc"
    local_tpr = ctx.step_dir / "production.tpr"
    local_xtc.write_bytes(xtc_path.read_bytes())
    local_tpr.write_bytes(tpr_path.read_bytes())

    executor_calls: list[dict[str, Any]] = []

    # ---- RMSD (vs starting structure; backbone group) ------------------
    rmsd_xvg = ctx.step_dir / "rmsd.xvg"
    # gmx rms asks twice: reference group + group to compute on.
    # Backbone group typically is "Backbone".
    argv = ["gmx", "rms", "-s", str(local_tpr), "-f", str(local_xtc),
            "-o", str(rmsd_xvg), "-tu", "ns"]
    proc, wall = _run_gmx(argv, ctx.step_dir, stdin_bytes=b"Backbone\nBackbone\n")
    executor_calls.append({"argv": argv, "exit_status": proc.returncode, "wall_time_s": wall})
    rmsd_ok = proc.returncode == 0 and rmsd_xvg.is_file()

    # ---- Radius of gyration --------------------------------------------
    rg_xvg = ctx.step_dir / "gyrate.xvg"
    argv = ["gmx", "gyrate", "-s", str(local_tpr), "-f", str(local_xtc), "-o", str(rg_xvg)]
    proc, wall = _run_gmx(argv, ctx.step_dir, stdin_bytes=b"Protein\n")
    executor_calls.append({"argv": argv, "exit_status": proc.returncode, "wall_time_s": wall})
    rg_ok = proc.returncode == 0 and rg_xvg.is_file()

    # ---- RMSF (per residue) -------------------------------------------
    rmsf_xvg = ctx.step_dir / "rmsf.xvg"
    argv = ["gmx", "rmsf", "-s", str(local_tpr), "-f", str(local_xtc),
            "-o", str(rmsf_xvg), "-res"]
    proc, wall = _run_gmx(argv, ctx.step_dir, stdin_bytes=b"Protein\n")
    executor_calls.append({"argv": argv, "exit_status": proc.returncode, "wall_time_s": wall})
    rmsf_ok = proc.returncode == 0 and rmsf_xvg.is_file()

    # ---- H-bond count (protein–protein, intramolecular) ----------------
    # `gmx hbond` in modern GROMACS uses -r / -t selection strings.
    hbnum_xvg = ctx.step_dir / "hbnum.xvg"
    argv = ["gmx", "hbond",
            "-s", str(local_tpr), "-f", str(local_xtc),
            "-num", str(hbnum_xvg),
            "-r", "protein", "-t", "protein"]
    proc, wall = _run_gmx(argv, ctx.step_dir, timeout=900.0)
    executor_calls.append({"argv": argv, "exit_status": proc.returncode, "wall_time_s": wall})
    hbond_ok = proc.returncode == 0 and hbnum_xvg.is_file()

    # ---- Thermodynamic summary from NVT/NPT .edr ----------------------
    # Read paths to the NVT and NPT .edr files from the run's index by
    # walking the per-step dirs (parent of step_dir).
    nvt_edr = ctx.run_root / "step_07_nvt" / "nvt.edr"
    npt_edr = ctx.run_root / "step_08_npt" / "npt.edr"

    temperature_xvg = ctx.step_dir / "temperature.xvg"
    pressure_xvg = ctx.step_dir / "pressure.xvg"
    density_xvg = ctx.step_dir / "density.xvg"

    temperature_ok = pressure_ok = density_ok = False
    if nvt_edr.is_file():
        argv = ["gmx", "energy", "-f", str(nvt_edr), "-o", str(temperature_xvg)]
        proc, wall = _run_gmx(argv, ctx.step_dir, stdin_bytes=b"Temperature\n0\n")
        executor_calls.append({"argv": argv, "exit_status": proc.returncode, "wall_time_s": wall})
        temperature_ok = proc.returncode == 0 and temperature_xvg.is_file()

    if npt_edr.is_file():
        argv = ["gmx", "energy", "-f", str(npt_edr), "-o", str(pressure_xvg)]
        proc, wall = _run_gmx(argv, ctx.step_dir, stdin_bytes=b"Pressure\n0\n")
        executor_calls.append({"argv": argv, "exit_status": proc.returncode, "wall_time_s": wall})
        pressure_ok = proc.returncode == 0 and pressure_xvg.is_file()

        argv = ["gmx", "energy", "-f", str(npt_edr), "-o", str(density_xvg)]
        proc, wall = _run_gmx(argv, ctx.step_dir, stdin_bytes=b"Density\n0\n")
        executor_calls.append({"argv": argv, "exit_status": proc.returncode, "wall_time_s": wall})
        density_ok = proc.returncode == 0 and density_xvg.is_file()

    rmsd_rows = _parse_xvg(rmsd_xvg) if rmsd_ok else []
    rg_rows = _parse_xvg(rg_xvg) if rg_ok else []
    rmsf_rows = _parse_xvg(rmsf_xvg) if rmsf_ok else []
    hbnum_rows = _parse_xvg(hbnum_xvg) if hbond_ok else []
    temperature_rows = _parse_xvg(temperature_xvg) if temperature_ok else []
    pressure_rows = _parse_xvg(pressure_xvg) if pressure_ok else []
    density_rows = _parse_xvg(density_xvg) if density_ok else []

    # gmx rms emits (time_ns, rmsd_nm)
    rmsd_values = [row[1] for row in rmsd_rows if len(row) >= 2]
    rmsd_times = [row[0] for row in rmsd_rows if len(row) >= 2]
    # gmx gyrate emits (time_ps, Rg, RgX, RgY, RgZ)
    rg_values = [row[1] for row in rg_rows if len(row) >= 2]
    rg_times = [row[0] for row in rg_rows if len(row) >= 2]
    # gmx rmsf emits (residue_index, rmsf_nm)
    rmsf_values = [row[1] for row in rmsf_rows if len(row) >= 2]
    rmsf_residues = [row[0] for row in rmsf_rows if len(row) >= 2]
    # gmx hbond emits (time_ps, n_hbonds, n_pairs)
    hbnum_values = [row[1] for row in hbnum_rows if len(row) >= 2]
    hbnum_times = [row[0] for row in hbnum_rows if len(row) >= 2]
    # gmx energy → (time_ps, value)
    temperature_values = [row[1] for row in temperature_rows if len(row) >= 2]
    temperature_times = [row[0] for row in temperature_rows if len(row) >= 2]
    pressure_values = [row[1] for row in pressure_rows if len(row) >= 2]
    pressure_times = [row[0] for row in pressure_rows if len(row) >= 2]
    density_values = [row[1] for row in density_rows if len(row) >= 2]
    density_times = [row[0] for row in density_rows if len(row) >= 2]

    analysis = {
        "rmsd": {
            "ok": rmsd_ok,
            "units": {"time": "ns", "value": "nm"},
            "summary": _summary(rmsd_values),
            "time_series": [{"t": t, "rmsd": v} for t, v in zip(rmsd_times, rmsd_values)],
        },
        "radius_of_gyration": {
            "ok": rg_ok,
            "units": {"time": "ps", "value": "nm"},
            "summary": _summary(rg_values),
            "time_series": [{"t": t, "Rg": v} for t, v in zip(rg_times, rg_values)],
        },
        "rmsf": {
            "ok": rmsf_ok,
            "units": {"residue_index": "1-based", "value": "nm"},
            "summary": _summary(rmsf_values),
            "by_residue": [{"resid": int(r), "rmsf": v} for r, v in zip(rmsf_residues, rmsf_values)],
        },
        "hbonds": {
            "ok": hbond_ok,
            "units": {"time": "ps", "value": "count"},
            "summary": _summary(hbnum_values),
            "time_series": [{"t": t, "n": v} for t, v in zip(hbnum_times, hbnum_values)],
        },
        "thermodynamics": {
            "temperature_K_nvt": {
                "ok": temperature_ok,
                "units": {"time": "ps", "value": "K"},
                "summary": _summary(temperature_values),
                "time_series": [{"t": t, "T": v} for t, v in zip(temperature_times, temperature_values)],
            },
            "pressure_bar_npt": {
                "ok": pressure_ok,
                "units": {"time": "ps", "value": "bar"},
                "summary": _summary(pressure_values),
                "time_series": [{"t": t, "P": v} for t, v in zip(pressure_times, pressure_values)],
            },
            "density_kgm3_npt": {
                "ok": density_ok,
                "units": {"time": "ps", "value": "kg/m^3"},
                "summary": _summary(density_values),
                "time_series": [{"t": t, "rho": v} for t, v in zip(density_times, density_values)],
            },
        },
    }
    analysis_path = ctx.step_dir / "analysis.json"
    analysis_path.write_text(json.dumps(analysis, indent=2, sort_keys=False))

    outputs: list[dict[str, str]] = [{
        "artifact_uri": f"local://{analysis_path}",
        "content_hash": sha256_text(analysis_path.read_text()),
        "role": "analysis",
    }]
    for p, role in [
        (rmsd_xvg, "rmsd_xvg"),
        (rg_xvg, "rg_xvg"),
        (rmsf_xvg, "rmsf_xvg"),
        (hbnum_xvg, "hbnum_xvg"),
        (temperature_xvg, "temperature_xvg"),
        (pressure_xvg, "pressure_xvg"),
        (density_xvg, "density_xvg"),
    ]:
        if p.is_file():
            outputs.append({
                "artifact_uri": f"local://{p}",
                "content_hash": sha256_file(p),
                "role": role,
            })

    warnings: list[dict[str, Any]] = []
    # Core trajectory analyses must succeed; thermodynamics + hbond are
    # best-effort (gmx hbond is occasionally unstable on tiny trajectories).
    if not (rmsd_ok and rg_ok and rmsf_ok):
        warnings.append({
            "class": "io",
            "severity": "warning",
            "message": "one or more core analyses did not complete",
            "context": {"rmsd_ok": rmsd_ok, "rg_ok": rg_ok, "rmsf_ok": rmsf_ok},
        })
    if not hbond_ok:
        warnings.append({
            "class": "io",
            "severity": "info",
            "message": "gmx hbond did not produce output (sometimes flaky on very short trajectories)",
        })

    return StepOutcome(
        outputs=outputs,
        executor_calls=executor_calls,
        warnings=warnings,
        extra={
            "rmsd_summary": analysis["rmsd"]["summary"],
            "rg_summary": analysis["radius_of_gyration"]["summary"],
            "rmsf_summary": analysis["rmsf"]["summary"],
            "hbond_summary": analysis["hbonds"]["summary"],
            "thermo_summary": {
                k: v["summary"] for k, v in analysis["thermodynamics"].items()
            },
        },
    )
