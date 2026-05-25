"""Packaged resources (schemas, skills) shipped inside the wheel.

Resolved at runtime via importlib.resources.files() so an installed wheel
works without the repo checkout on disk.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path


def _filesystem_path(pkg: str) -> Path:
    """Return a real on-disk Path for `pkg`.

    v0 only supports filesystem-backed installs (editable + standard wheel).
    Zipapp / archive installs would return a non-Path Traversable and are
    not supported.
    """
    res = resources.files(pkg)
    if isinstance(res, Path):
        return res
    # importlib.resources may return MultiplexedPath or PosixPath subclasses;
    # for filesystem-backed resources `__fspath__` resolves to a real path.
    try:
        return Path(res.__fspath__())  # type: ignore[attr-defined]
    except (AttributeError, TypeError) as e:
        raise UnsupportedResourceInstall(
            f"mdagent resources at {pkg!r} are not filesystem-backed "
            "(zipapp / archive installs are unsupported in v0). "
            "Reinstall via `uv tool install --force git+https://github.com/FidhaNazreen/MDSimulationAgent@<tag>`."
        ) from e


class UnsupportedResourceInstall(RuntimeError):
    """Resources aren't available as a filesystem directory (e.g. zipapp install)."""


def schemas_dir(version: str = "0.1.0") -> Path:
    """Return the on-disk path to the bundled schemas/<version>/ dir."""
    return _filesystem_path("mdagent._resources.schemas") / f"v{version}"


def skills_dir() -> Path:
    """Return the on-disk path to the bundled skills/ dir."""
    return _filesystem_path("mdagent._resources.skills")
