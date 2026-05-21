"""RunIndex tests — atomic writes, invalidation walker, run-lock."""

from __future__ import annotations

import multiprocessing as mp
import os
import time
from pathlib import Path

import pytest

from mdagent import IndexStep, RunIndex, RunLockError, acquire_run_lock, recover_stale_running


def _initialized_index(tmp_path: Path) -> tuple[RunIndex, Path]:
    idx = RunIndex.initialize(run_id="test_run", run_config_hash="a" * 64)
    path = tmp_path / "index.json"
    idx.write(path)
    return idx, path


def test_initialize_uses_step_definitions(tmp_path: Path) -> None:
    idx, _ = _initialized_index(tmp_path)
    assert [s.step_id for s in idx.steps] == [
        "step_00_preflight_early",
        "step_01_structure_ingest",
        "step_02_classifier",
        "step_03_structure_prep",
        "step_04_topology",
        "step_05_solvation",
        "step_06_em",
        "step_07_nvt",
        "step_08_npt",
        "step_09_production",
        "step_10_analysis",
        "step_11_visualization",
        "step_12_report",
    ]
    assert all(s.status == "planned" for s in idx.steps)


def test_round_trip_through_disk(tmp_path: Path) -> None:
    idx, path = _initialized_index(tmp_path)
    loaded = RunIndex.read(path)
    assert loaded.run_id == "test_run"
    assert len(loaded.steps) == len(idx.steps)
    assert all(s.status == "planned" for s in loaded.steps)


def test_atomic_write_no_tempfile_leftover(tmp_path: Path) -> None:
    """Writing must clean up its temp file; only index.json should remain."""
    idx, path = _initialized_index(tmp_path)
    idx.set_status("step_00_preflight_early", "succeeded")
    idx.write(path)
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.startswith(".index-")]
    assert leftovers == [], f"temp files leaked: {leftovers}"


def test_set_status_validates_states(tmp_path: Path) -> None:
    idx, _ = _initialized_index(tmp_path)
    with pytest.raises(ValueError, match="invalid status"):
        idx.set_status("step_00_preflight_early", "nonsense")


def test_first_non_succeeded(tmp_path: Path) -> None:
    idx, _ = _initialized_index(tmp_path)
    idx.set_status("step_00_preflight_early", "succeeded")
    idx.set_status("step_01_structure_ingest", "succeeded")
    target = idx.first_non_succeeded()
    assert target is not None
    assert target.step_id == "step_02_classifier"


def test_first_non_succeeded_returns_none_when_done(tmp_path: Path) -> None:
    idx, _ = _initialized_index(tmp_path)
    for s in idx.steps:
        s.status = "succeeded"
    assert idx.first_non_succeeded() is None


def test_invalidate_from_marks_step_and_downstream(tmp_path: Path) -> None:
    idx, _ = _initialized_index(tmp_path)
    for s in idx.steps:
        s.status = "succeeded"
    changed = idx.invalidate_from("step_04_topology")
    expected_invalidated = [
        "step_04_topology",
        "step_05_solvation",
        "step_06_em",
        "step_07_nvt",
        "step_08_npt",
        "step_09_production",
        "step_10_analysis",
        "step_11_visualization",
        "step_12_report",
    ]
    assert changed == expected_invalidated
    for sid in expected_invalidated:
        assert idx.step(sid).status == "invalidated"
    # Upstream untouched
    assert idx.step("step_03_structure_prep").status == "succeeded"


def test_apply_fingerprint_check_invalidates_on_mismatch(tmp_path: Path) -> None:
    idx, _ = _initialized_index(tmp_path)
    for s in idx.steps:
        s.status = "succeeded"
        s.fingerprint_composite = "0" * 64
    invalidated = idx.apply_fingerprint_check("step_04_topology", recomputed_composite="9" * 64)
    assert invalidated is True
    assert idx.step("step_04_topology").status == "invalidated"
    assert idx.step("step_05_solvation").status == "invalidated"


def test_apply_fingerprint_check_skips_on_match(tmp_path: Path) -> None:
    idx, _ = _initialized_index(tmp_path)
    for s in idx.steps:
        s.status = "succeeded"
        s.fingerprint_composite = "0" * 64
    invalidated = idx.apply_fingerprint_check("step_04_topology", recomputed_composite="0" * 64)
    assert invalidated is False
    assert idx.step("step_04_topology").status == "succeeded"


def test_apply_fingerprint_check_skips_non_succeeded(tmp_path: Path) -> None:
    idx, _ = _initialized_index(tmp_path)
    # default is 'planned' — should never invalidate non-succeeded steps
    invalidated = idx.apply_fingerprint_check("step_04_topology", recomputed_composite="9" * 64)
    assert invalidated is False


# ---- run lock ----------------------------------------------------------


def test_acquire_run_lock_basic(tmp_path: Path) -> None:
    with acquire_run_lock(tmp_path):
        assert (tmp_path / ".lock").exists()
    assert not (tmp_path / ".lock").exists()  # cleaned up


def test_acquire_run_lock_conflict(tmp_path: Path) -> None:
    """Second acquisition from a child process must fail."""
    with acquire_run_lock(tmp_path):
        # Lock is held by this process; verify a child cannot acquire it.
        result = mp.get_context("spawn").Pool(1).apply(_try_acquire, (str(tmp_path),))
    assert result is False, "child should not have acquired the lock"


def _try_acquire(run_root_str: str) -> bool:
    try:
        with acquire_run_lock(run_root_str):
            return True
    except RunLockError:
        return False


def test_recover_stale_running_when_no_pid(tmp_path: Path) -> None:
    idx, _ = _initialized_index(tmp_path)
    idx.set_status("step_03_structure_prep", "running")
    idx.lock_holder_pid = None  # simulates crash with no lock holder recorded
    fixed = recover_stale_running(idx)
    assert fixed == ["step_03_structure_prep"]
    assert idx.step("step_03_structure_prep").status == "failed"


def test_recover_stale_running_with_dead_pid(tmp_path: Path) -> None:
    idx, _ = _initialized_index(tmp_path)
    idx.set_status("step_03_structure_prep", "running")
    idx.lock_holder_pid = _find_unused_pid()
    fixed = recover_stale_running(idx)
    assert fixed == ["step_03_structure_prep"]


def test_recover_stale_running_skips_live_pid(tmp_path: Path) -> None:
    idx, _ = _initialized_index(tmp_path)
    idx.set_status("step_03_structure_prep", "running")
    idx.lock_holder_pid = os.getpid()  # very much alive
    fixed = recover_stale_running(idx)
    assert fixed == [], "must not touch running step when PID is alive"
    assert idx.step("step_03_structure_prep").status == "running"


def _find_unused_pid() -> int:
    # Pick a high PID unlikely to be in use. Linear scan is fine here; tests are local.
    for pid in range(2**20, 2**20 + 100):
        try:
            os.kill(pid, 0)
        except (ProcessLookupError, PermissionError):
            return pid
        except OSError:
            continue
    pytest.skip("could not find an unused PID for the test environment")
    return 0  # unreachable; pytest.skip raises
