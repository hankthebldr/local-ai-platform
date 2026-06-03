from __future__ import annotations

from pathlib import Path

import pytest

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover - 3.9/3.10 local venv
    try:
        import tomli as tomllib  # type: ignore
    except ModuleNotFoundError:
        tomllib = None  # type: ignore

PYPROJECT = Path(__file__).parent.parent.parent / "pyproject.toml"


@pytest.mark.skipif(tomllib is None, reason="no TOML parser (py<3.11 without tomli)")
def test_triage_package_is_shipped_in_wheel_and_sdist():
    """The runtime error handler imports `triage` lazily (api/exceptions.py).
    If the package isn't shipped in the wheel/sdist, opt-in error reporting
    silently no-ops in installed (pip) deployments. Guard against that."""
    cfg = tomllib.loads(PYPROJECT.read_text())
    targets = cfg["tool"]["hatch"]["build"]["targets"]
    assert "triage" in targets["wheel"]["packages"]
    assert "triage/" in targets["sdist"]["include"]
