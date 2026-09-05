"""Theme B — curated seeds actually reach a container, and secrets never do.

`data/discovery/{mcp_catalog,skills_catalog,model_benchmarks}.json`,
`data/profiles/*.yaml` and `data/config/search_settings.json` are git-tracked
repo data read at runtime from CWD-relative paths. The Dockerfile never COPY'd
any of `data/`, so every built image shipped with EMPTY catalogs and no
profiles — the MCP marketplace, the Skills Lab and the model-benchmark panel
were all blank in Docker while working fine from a source checkout.

The fix is a NAMED seed subset rather than a blanket `COPY data/`, because the
build context's `data/config/` also holds live credentials in a developer tree
(`api_keys.yaml`, `first-run-key.txt`). These tests pin both halves: the seeds
are copied, and the secrets can't be.

Docker isn't required — the Dockerfile + .dockerignore are parsed as text, so
this runs anywhere. (A real `docker build` would take minutes and needs a
daemon; the contract worth regression-testing is the recipe.)
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "Dockerfile"
DOCKERIGNORE = ROOT / ".dockerignore"

# (source path in the build context, the module that reads it at runtime)
SEED_FILES = [
    ("data/discovery/skills_catalog.json", "api/routers/skills.py"),
    ("data/discovery/mcp_catalog.json", "api/routers/mcp.py"),
    ("data/discovery/model_benchmarks.json", "api/routers/inventory.py"),
    ("data/config/search_settings.json", "api/services/search_service.py"),
]

# Credentials that live under data/config/ in a developer tree.
SECRET_PATHS = ["data/config/api_keys.yaml", "data/config/first-run-key.txt", ".env"]


def _copy_sources(dockerfile: str) -> list[str]:
    """Every source argument of every COPY instruction."""
    out: list[str] = []
    for line in dockerfile.splitlines():
        line = line.strip()
        if not line.upper().startswith("COPY "):
            continue
        parts = [p for p in line.split()[1:] if not p.startswith("--")]
        out.extend(parts[:-1])  # last arg is the destination
    return out


@pytest.fixture(scope="module")
def dockerfile() -> str:
    return DOCKERFILE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def copy_sources(dockerfile: str) -> list[str]:
    return _copy_sources(dockerfile)


# ── the seeds are shipped ──────────────────────────────────────────────────


@pytest.mark.parametrize("seed,reader", SEED_FILES)
def test_seed_file_exists_and_parses(seed: str, reader: str):
    """A COPY of a file that doesn't parse ships a broken catalog."""
    path = ROOT / seed
    assert path.exists(), f"{seed} missing — {reader} reads it at runtime"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload, f"{seed} is empty"


@pytest.mark.parametrize("seed,reader", SEED_FILES)
def test_seed_is_copied_into_the_image(seed: str, reader: str, copy_sources: list[str]):
    """Either the file itself or a parent directory is COPY'd."""
    covered = any(
        seed == src or (src.endswith("/") and seed.startswith(src))
        for src in copy_sources
    )
    assert covered, (
        f"{seed} is never COPY'd into the image, so {reader} reads an empty "
        f"catalog in every container. COPY sources: {copy_sources}"
    )


def test_profiles_are_copied_and_parse(copy_sources: list[str]):
    """ProfileService scans data/profiles/ — without the COPY a container has
    zero profiles."""
    assert "data/profiles/" in copy_sources, "data/profiles/ is not COPY'd"
    profiles = sorted((ROOT / "data" / "profiles").glob("*.yaml"))
    assert profiles, "no profile YAML to ship"
    for p in profiles:
        assert yaml.safe_load(p.read_text(encoding="utf-8")), f"{p.name} is empty"


# ── secrets can never be shipped ───────────────────────────────────────────


def test_no_blanket_data_copy(copy_sources: list[str]):
    """`COPY data/` would sweep the developer tree's api_keys.yaml and
    first-run-key.txt into the image. The seed subset must stay named."""
    assert "data/" not in copy_sources and "data" not in copy_sources, (
        "blanket `COPY data/` would bake runtime credentials into the image — "
        "COPY the named seed subset instead"
    )


def test_config_copy_is_a_named_file_not_the_directory(copy_sources: list[str]):
    """data/config/ holds api_keys.yaml + first-run-key.txt. Only the single
    settings file may be copied out of it."""
    for src in copy_sources:
        if src.startswith("data/config"):
            assert src == "data/config/search_settings.json", (
                f"COPY {src} would pull credentials out of data/config/ — "
                "copy data/config/search_settings.json by name"
            )


@pytest.mark.parametrize("secret", SECRET_PATHS)
def test_dockerignore_excludes_secrets(secret: str):
    """Defence in depth: even a future blanket COPY can't pick these up."""
    assert DOCKERIGNORE.exists(), ".dockerignore is missing"
    patterns = {
        ln.strip()
        for ln in DOCKERIGNORE.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    }
    assert secret in patterns, f"{secret} is not excluded by .dockerignore"


def test_dockerignore_excludes_runtime_state_but_keeps_seeds():
    """Runtime output must not enter the build context; the seed dirs must."""
    patterns = {
        ln.strip()
        for ln in DOCKERIGNORE.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    }
    for runtime in ("data/workflows/", "data/logs/", "data/research/"):
        assert runtime in patterns, f"{runtime} should be build-context ignored"
    # An ignore of the seed dirs would silently defeat the COPYs above.
    for seed_dir in (
        "data/discovery/",
        "data/profiles/",
        "data/",
        "docs/",
        "docs/seed/",
    ):
        assert seed_dir not in patterns, (
            f"{seed_dir} is .dockerignore'd — the Dockerfile COPY of it would "
            "silently produce an empty directory"
        )


def test_dockerfile_still_creates_writable_runtime_dirs(dockerfile: str):
    """The runtime dirs are .dockerignore'd out of the context, so the image
    must still mkdir them or the app has nowhere to write."""
    assert re.search(
        r"mkdir\s+-p\s+data/logs\s+data/cache", dockerfile
    ), "runtime data dirs are no longer created in the image"
