# In-App Licensing & Support Client Implementation Plan

> **Status (2026-04-22): Active — not yet started.** Queued behind Plan 1 (Worker), which is complete ([hankthebldr/license-service](https://github.com/hankthebldr/license-service)). Execute when ready to ship the in-app verification, feature gating, and support client.
>
> **Constraint:** no production signing-key material in this repo. The bundled
> public key at `api/keys/license_pubkey.pem` stays as `PLACEHOLDER` until
> production deploy; tests use the committable keypair at
> `tests/fixtures/test_license_*.pem`.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add offline license verification, feature gating (FastAPI dep + CLI dispatch + desktop banner), a redaction-hardened support client that submits issues through `license-service`, and user-facing docs — to the `local-ai-platform` repo.

**Architecture:** Single `LicenseService` loads a signed Ed25519 license from `~/.local-ai-platform/license.key`, verifies against a bundled public key, caches status in-process. A `PREMIUM_FEATURES` registry names gates; enforcement lives in three places only. Support submission redacts client-side, then POSTs to `license-service` with the license in the `X-Local-AI-License` header.

**Tech Stack:** Python 3.11+, FastAPI, Starlette middleware, argparse + Rich for CLI, `cryptography` library (already present via indirect deps) for Ed25519, `httpx` or `requests` (match existing pattern — `requests` is used throughout), pytest + hypothesis for tests.

**Spec:** `docs/superpowers/specs/2026-04-18-licensing-and-supportability-design.md`
**Depends on:** `docs/superpowers/plans/2026-04-19-license-service-worker.md` (for signing-key generation and deployed endpoint). The in-app tests use a parallel **test keypair** so development does not require the Worker.

---

## File Structure

```
api/
├── services/
│   ├── license_service.py              NEW  LicenseService class, load/verify/cache
│   ├── features.py                     NEW  PREMIUM_FEATURES registry
│   └── support_service.py              NEW  Submit + redact + queue
├── routers/
│   └── support.py                      NEW  POST /v1/support/issues
├── middleware.py                       EDIT Add LicenseHeaderMiddleware
├── dependencies.py                     NEW  require_license_feature() FastAPI dep
├── main.py                             EDIT Load license in lifespan
└── keys/
    └── license_pubkey.pem              NEW  Production public key (PEM SPKI)

cli/
├── license.py                          NEW  install, show, verify subcommands
├── support.py                          NEW  file-issue, retry-queued
├── support_redact.py                   NEW  Pure redaction functions
├── chat.py                             EDIT Nag footer (1-in-5) for unlicensed
└── workflow.py                         EDIT Gate at dispatch

desktop/
└── app.py                              EDIT desktop_gui feature check + banner

docs/
├── LICENSING.md                        NEW  User guide
└── SUPPORT.md                          NEW  How to file issues

tests/
├── conftest.py                         EDIT Add license fixtures
├── fixtures/
│   ├── test_license_privkey.pem        NEW  Committed (TEST only, never prod)
│   ├── test_license_pubkey.pem         NEW
│   ├── make_license.py                 NEW  Helper — generate signed license for tests
│   ├── valid_license.key               NEW  Generated from make_license.py
│   ├── tampered_license.key            NEW
│   └── wrong_product_license.key       NEW
├── test_license_service.py             NEW
├── test_features_gating.py             NEW
├── test_support_redaction.py           NEW  property-based
├── test_support_service.py             NEW
├── test_support_router.py              NEW
└── test_cli_license.py                 NEW
```

**Responsibility boundaries:**
- `services/license_service.py` — pure: load, verify, cache. No network.
- `services/support_service.py` — redact, serialize, POST. No crypto.
- `dependencies.py` — FastAPI-specific glue only.
- `cli/support_redact.py` — pure functions, no I/O.

---

## Task 1: Add cryptography dependency & generate test keypair

**Files:**
- Modify: `setup/requirements-core.txt`
- Create: `tests/fixtures/test_license_privkey.pem`
- Create: `tests/fixtures/test_license_pubkey.pem`
- Create: `tests/fixtures/make_license.py`

- [ ] **Step 1: Add cryptography to requirements**

Confirm `cryptography>=41` is listed in `setup/requirements-core.txt`. If missing, add:
```
cryptography>=41,<46
```
Run: `source venv/bin/activate && pip install 'cryptography>=41'`

- [ ] **Step 2: Generate a test Ed25519 keypair (one-time, committed)**

```bash
cd /Users/henry/Github/Github_desktop/local-ai-platform
python - <<'PY'
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
priv = Ed25519PrivateKey.generate()
pub = priv.public_key()
with open("tests/fixtures/test_license_privkey.pem", "wb") as f:
    f.write(priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ))
with open("tests/fixtures/test_license_pubkey.pem", "wb") as f:
    f.write(pub.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ))
print("Wrote tests/fixtures/test_license_{priv,pub}key.pem")
PY
```

**These files are test-only and safe to commit** — they are never deployed, and rotation is trivial (regenerate, re-run `make_license.py`).

- [ ] **Step 3: Write `tests/fixtures/make_license.py`**

```python
#!/usr/bin/env python3
"""
Generate signed license files for tests.
Uses tests/fixtures/test_license_privkey.pem — NEVER used in production.

Usage:
    python tests/fixtures/make_license.py
"""
import base64
import json
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


FIXTURES = Path(__file__).parent
PRIVKEY_PATH = FIXTURES / "test_license_privkey.pem"

BEGIN = "-----BEGIN LOCAL-AI-PLATFORM LICENSE-----"
END = "-----END LOCAL-AI-PLATFORM LICENSE-----"


def sign_payload(payload: dict) -> str:
    priv_bytes = PRIVKEY_PATH.read_bytes()
    priv = serialization.load_pem_private_key(priv_bytes, password=None)
    assert isinstance(priv, Ed25519PrivateKey)
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    sig = priv.sign(body)
    return (
        f"{BEGIN}\n"
        f"{wrap_b64(body)}\n"
        f".\n"
        f"{wrap_b64(sig)}\n"
        f"{END}\n"
    )


def wrap_b64(raw: bytes, width: int = 64) -> str:
    s = base64.b64encode(raw).decode()
    return "\n".join(s[i : i + width] for i in range(0, len(s), width))


def main() -> None:
    issued_at = datetime(2026, 4, 19, 12, 0, 0, tzinfo=timezone.utc).isoformat()
    valid_payload = {
        "license_id": "laip_01HXYZTEST0000000000000000",
        "email": "alice@example.com",
        "product": "local-ai-platform",
        "tier": "individual",
        "issued_at": issued_at,
        "version": 1,
        "features": ["workflow_engine", "rag", "multi_model", "desktop_gui", "github_support", "finetuning"],
    }
    (FIXTURES / "valid_license.key").write_text(sign_payload(valid_payload))

    # Tampered: valid signature on a different payload, but we swap the payload
    # in-file (corrupt last base64 char of payload block).
    valid = (FIXTURES / "valid_license.key").read_text()
    corrupted_payload = valid.replace("alice", "aliceX", 1) if "alice" in valid else valid[:-60] + "x" + valid[-59:]
    (FIXTURES / "tampered_license.key").write_text(corrupted_payload)

    # Wrong product
    wrong = dict(valid_payload, product="some-other-product")
    (FIXTURES / "wrong_product_license.key").write_text(sign_payload(wrong))

    print("Wrote valid_license.key, tampered_license.key, wrong_product_license.key")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Generate fixture licenses**

Run: `python tests/fixtures/make_license.py`
Expected: 3 files created under `tests/fixtures/`.

- [ ] **Step 5: Commit**

```bash
git add setup/requirements-core.txt tests/fixtures/
git commit -m "test: add ed25519 test keypair and fixture license generator"
```

---

## Task 2: License PEM parsing & models

**Files:**
- Create: `api/services/license_service.py` (first pass — pure parsing)
- Create: `tests/test_license_service.py`

- [ ] **Step 1: Write failing tests for PEM parsing**

```python
# tests/test_license_service.py
"""Tests for the license service — parse, verify, cache."""

import base64
import json
from pathlib import Path

import pytest

from api.services.license_service import (
    LicenseService,
    parse_license_pem,
    LicenseParseError,
    PRODUCT,
)


FIXTURES = Path(__file__).parent / "fixtures"
PUBKEY = (FIXTURES / "test_license_pubkey.pem").read_bytes()


class TestParsePem:
    def test_parses_valid_license(self):
        pem = (FIXTURES / "valid_license.key").read_text()
        payload, signature = parse_license_pem(pem)
        assert len(signature) == 64
        data = json.loads(payload)
        assert data["license_id"] == "laip_01HXYZTEST0000000000000000"
        assert data["product"] == PRODUCT
        assert data["tier"] == "individual"

    def test_rejects_missing_markers(self):
        with pytest.raises(LicenseParseError):
            parse_license_pem("not a license")

    def test_rejects_missing_separator(self):
        with pytest.raises(LicenseParseError):
            parse_license_pem(
                "-----BEGIN LOCAL-AI-PLATFORM LICENSE-----\n"
                "aaaa\n"
                "-----END LOCAL-AI-PLATFORM LICENSE-----\n"
            )

    def test_rejects_signature_wrong_length(self):
        bad_sig = base64.b64encode(b"\x00" * 32).decode()
        pem = (
            "-----BEGIN LOCAL-AI-PLATFORM LICENSE-----\n"
            f"{base64.b64encode(b'{}').decode()}\n"
            f".\n"
            f"{bad_sig}\n"
            "-----END LOCAL-AI-PLATFORM LICENSE-----\n"
        )
        with pytest.raises(LicenseParseError, match="signature"):
            parse_license_pem(pem)
```

- [ ] **Step 2: Run, fail**

Run: `source venv/bin/activate && pytest tests/test_license_service.py -v`
Expected: module not found.

- [ ] **Step 3: Write `api/services/license_service.py` first pass**

```python
#!/usr/bin/env python3
"""
License Service — load, verify, and cache a signed Ed25519 license file.

The license file is a PEM-style envelope containing a base64-encoded JSON
payload and a base64-encoded 64-byte Ed25519 signature, separated by a
line containing a single '.'.

Verification is offline: the public key is bundled at api/keys/license_pubkey.pem.
"""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from threading import Lock
from typing import Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


# ── Constants ──────────────────────────────────────────────────────────────

PRODUCT = "local-ai-platform"

BEGIN_MARKER = "-----BEGIN LOCAL-AI-PLATFORM LICENSE-----"
END_MARKER = "-----END LOCAL-AI-PLATFORM LICENSE-----"

DEFAULT_LICENSE_PATH = Path.home() / ".local-ai-platform" / "license.key"
DEFAULT_PUBKEY_PATH = Path(__file__).parent.parent / "keys" / "license_pubkey.pem"


# ── Errors ─────────────────────────────────────────────────────────────────

class LicenseParseError(ValueError):
    pass


class LicenseRequiredError(Exception):
    """Raised when a premium feature is accessed without a valid license."""

    def __init__(self, feature: str, purchase_url: str) -> None:
        super().__init__(f"Feature '{feature}' requires a license.")
        self.feature = feature
        self.purchase_url = purchase_url


# ── Models ─────────────────────────────────────────────────────────────────

class LicenseState(str, Enum):
    LICENSED = "licensed"
    UNLICENSED = "unlicensed"
    INVALID = "invalid"
    REVOKED = "revoked"


@dataclass(frozen=True)
class License:
    license_id: str
    email: str
    product: str
    tier: str
    issued_at: str
    version: int
    features: tuple[str, ...]
    test: bool = False

    @classmethod
    def from_payload(cls, data: dict) -> "License":
        return cls(
            license_id=data["license_id"],
            email=data["email"],
            product=data["product"],
            tier=data["tier"],
            issued_at=data["issued_at"],
            version=int(data["version"]),
            features=tuple(data.get("features", [])),
            test=bool(data.get("test", False)),
        )


@dataclass
class LicenseStatus:
    state: LicenseState
    license: Optional[License] = None
    source_path: Optional[Path] = None
    loaded_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    error: Optional[str] = None


# ── Parsing (pure) ─────────────────────────────────────────────────────────

def parse_license_pem(pem: str) -> tuple[bytes, bytes]:
    """Parse a license PEM string → (payload_bytes, signature_bytes)."""
    stripped = pem.strip()
    if not stripped.startswith(BEGIN_MARKER) or not stripped.endswith(END_MARKER):
        raise LicenseParseError("missing BEGIN/END markers")

    inner = stripped[len(BEGIN_MARKER) : -len(END_MARKER)].strip()
    # Separator line: '.'
    parts = inner.split("\n.\n")
    if len(parts) != 2:
        raise LicenseParseError("expected two base64 blocks separated by '.'")
    try:
        payload = base64.b64decode("".join(parts[0].split()))
        signature = base64.b64decode("".join(parts[1].split()))
    except Exception as e:
        raise LicenseParseError(f"base64 decode failed: {e}") from e
    if len(signature) != 64:
        raise LicenseParseError(f"signature must be 64 bytes, got {len(signature)}")
    return payload, signature


# ── Service (loaded later) ─────────────────────────────────────────────────

class LicenseService:
    """Loads, verifies, and caches a license. Thread-safe for read after load."""

    def __init__(
        self,
        license_path: Optional[Path] = None,
        pubkey_path: Optional[Path] = None,
        revocations: Optional[frozenset[str]] = None,
    ) -> None:
        self._license_path = Path(
            os.getenv("LICENSE_KEY_PATH") or license_path or DEFAULT_LICENSE_PATH
        )
        self._pubkey_path = Path(pubkey_path or DEFAULT_PUBKEY_PATH)
        self._revocations: frozenset[str] = revocations or frozenset()
        self._status: Optional[LicenseStatus] = None
        self._lock = Lock()

    def load(self) -> LicenseStatus:
        """Read + verify the license. Idempotent; safe to call multiple times."""
        with self._lock:
            self._status = self._read_and_verify()
            return self._status

    def status(self) -> LicenseStatus:
        if self._status is None:
            return self.load()
        return self._status

    def _read_and_verify(self) -> LicenseStatus:
        # Implemented in Task 3.
        raise NotImplementedError
```

- [ ] **Step 4: Run the parse tests**

Run: `pytest tests/test_license_service.py::TestParsePem -v`
Expected: 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add api/services/license_service.py tests/test_license_service.py
git commit -m "feat: license PEM parsing and model"
```

---

## Task 3: Signature verification & service load

**Files:**
- Modify: `api/services/license_service.py`
- Modify: `tests/test_license_service.py`

- [ ] **Step 1: Append failing tests**

```python
class TestLicenseServiceLoad:
    def test_unlicensed_when_file_missing(self, tmp_path):
        svc = LicenseService(license_path=tmp_path / "absent.key", pubkey_path=FIXTURES / "test_license_pubkey.pem")
        status = svc.load()
        assert status.state == LicenseState.UNLICENSED
        assert status.license is None

    def test_licensed_when_valid(self):
        svc = LicenseService(
            license_path=FIXTURES / "valid_license.key",
            pubkey_path=FIXTURES / "test_license_pubkey.pem",
        )
        status = svc.load()
        assert status.state == LicenseState.LICENSED
        assert status.license is not None
        assert status.license.license_id == "laip_01HXYZTEST0000000000000000"
        assert "workflow_engine" in status.license.features

    def test_invalid_on_tampered_signature(self):
        svc = LicenseService(
            license_path=FIXTURES / "tampered_license.key",
            pubkey_path=FIXTURES / "test_license_pubkey.pem",
        )
        status = svc.load()
        assert status.state == LicenseState.INVALID

    def test_invalid_on_wrong_product(self):
        svc = LicenseService(
            license_path=FIXTURES / "wrong_product_license.key",
            pubkey_path=FIXTURES / "test_license_pubkey.pem",
        )
        status = svc.load()
        assert status.state == LicenseState.INVALID
        assert "product" in (status.error or "").lower()

    def test_revoked_when_id_in_revocations(self):
        svc = LicenseService(
            license_path=FIXTURES / "valid_license.key",
            pubkey_path=FIXTURES / "test_license_pubkey.pem",
            revocations=frozenset(["laip_01HXYZTEST0000000000000000"]),
        )
        status = svc.load()
        assert status.state == LicenseState.REVOKED

    def test_env_var_overrides_path(self, monkeypatch):
        monkeypatch.setenv("LICENSE_KEY_PATH", str(FIXTURES / "valid_license.key"))
        svc = LicenseService(pubkey_path=FIXTURES / "test_license_pubkey.pem")
        assert svc.load().state == LicenseState.LICENSED

    def test_has_feature_true_when_licensed(self):
        svc = LicenseService(
            license_path=FIXTURES / "valid_license.key",
            pubkey_path=FIXTURES / "test_license_pubkey.pem",
        )
        svc.load()
        assert svc.has_feature("workflow_engine") is True
        assert svc.has_feature("nonexistent_feature") is False

    def test_has_feature_false_when_unlicensed(self, tmp_path):
        svc = LicenseService(license_path=tmp_path / "absent.key", pubkey_path=FIXTURES / "test_license_pubkey.pem")
        svc.load()
        assert svc.has_feature("workflow_engine") is False

    def test_require_feature_raises_when_unlicensed(self, tmp_path):
        svc = LicenseService(license_path=tmp_path / "absent.key", pubkey_path=FIXTURES / "test_license_pubkey.pem")
        svc.load()
        with pytest.raises(LicenseRequiredError):
            svc.require_feature("workflow_engine")

    def test_require_feature_quiet_when_licensed(self):
        svc = LicenseService(
            license_path=FIXTURES / "valid_license.key",
            pubkey_path=FIXTURES / "test_license_pubkey.pem",
        )
        svc.load()
        svc.require_feature("workflow_engine")  # no exception
```

- [ ] **Step 2: Run, fail (NotImplementedError)**

Run: `pytest tests/test_license_service.py::TestLicenseServiceLoad -v`
Expected: fails.

- [ ] **Step 3: Implement `_read_and_verify`, `has_feature`, `require_feature`**

Replace the `NotImplementedError` in `api/services/license_service.py` and add the new methods:

```python
    PURCHASE_URL_ENV = "LICENSE_PURCHASE_URL"
    DEFAULT_PURCHASE_URL = "https://ohno.lemonsqueezy.com/local-ai-platform"

    def has_feature(self, feature: str) -> bool:
        s = self.status()
        if s.state != LicenseState.LICENSED or s.license is None:
            return False
        return feature in s.license.features

    def require_feature(self, feature: str) -> None:
        if self.has_feature(feature):
            return
        raise LicenseRequiredError(
            feature=feature,
            purchase_url=os.getenv(self.PURCHASE_URL_ENV, self.DEFAULT_PURCHASE_URL),
        )

    def _read_and_verify(self) -> LicenseStatus:
        path = self._license_path
        if not path.exists():
            return LicenseStatus(state=LicenseState.UNLICENSED, source_path=path)

        try:
            pem = path.read_text()
        except OSError as e:
            return LicenseStatus(state=LicenseState.INVALID, source_path=path, error=f"read failed: {e}")

        try:
            payload, signature = parse_license_pem(pem)
        except LicenseParseError as e:
            return LicenseStatus(state=LicenseState.INVALID, source_path=path, error=str(e))

        try:
            pub = serialization.load_pem_public_key(self._pubkey_path.read_bytes())
        except Exception as e:
            return LicenseStatus(state=LicenseState.INVALID, source_path=path, error=f"pubkey load failed: {e}")

        if not isinstance(pub, Ed25519PublicKey):
            return LicenseStatus(state=LicenseState.INVALID, source_path=path, error="pubkey not Ed25519")

        try:
            pub.verify(signature, payload)
        except InvalidSignature:
            return LicenseStatus(state=LicenseState.INVALID, source_path=path, error="signature invalid")

        try:
            data = json.loads(payload)
        except json.JSONDecodeError as e:
            return LicenseStatus(state=LicenseState.INVALID, source_path=path, error=f"payload json: {e}")

        if data.get("product") != PRODUCT:
            return LicenseStatus(
                state=LicenseState.INVALID,
                source_path=path,
                error=f"wrong product: {data.get('product')!r}",
            )

        try:
            lic = License.from_payload(data)
        except (KeyError, ValueError) as e:
            return LicenseStatus(state=LicenseState.INVALID, source_path=path, error=f"payload: {e}")

        if lic.license_id in self._revocations:
            return LicenseStatus(state=LicenseState.REVOKED, license=lic, source_path=path)

        return LicenseStatus(state=LicenseState.LICENSED, license=lic, source_path=path)
```

- [ ] **Step 4: Run, pass**

Run: `pytest tests/test_license_service.py -v`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add api/services/license_service.py tests/test_license_service.py
git commit -m "feat: license signature verification and feature checks"
```

---

## Task 4: Features registry

**Files:**
- Create: `api/services/features.py`
- Create: `tests/test_features_gating.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_features_gating.py
from api.services.features import PREMIUM_FEATURES, describe_feature, is_premium


class TestFeatureRegistry:
    def test_contains_expected_features(self):
        expected = {
            "workflow_engine", "rag", "multi_model",
            "desktop_gui", "github_support", "finetuning",
        }
        assert set(PREMIUM_FEATURES.keys()) == expected

    def test_describe_returns_human_label(self):
        assert describe_feature("workflow_engine").startswith("Multi-agent")

    def test_describe_unknown_feature_raises(self):
        import pytest
        with pytest.raises(KeyError):
            describe_feature("nope")

    def test_is_premium_true_for_registry_entries(self):
        assert is_premium("workflow_engine")
        assert not is_premium("chat")
```

- [ ] **Step 2: Run, fail**

Run: `pytest tests/test_features_gating.py -v`
Expected: module missing.

- [ ] **Step 3: Write `api/services/features.py`**

```python
#!/usr/bin/env python3
"""
Premium feature registry — single source of truth for license-gated
functionality. Free-tier features are everything NOT in this dict.
"""
from __future__ import annotations

PREMIUM_FEATURES: dict[str, str] = {
    "workflow_engine": "Multi-agent workflow engine",
    "rag":             "RAG pipeline (ChromaDB + LangChain)",
    "multi_model":     "Multi-model orchestration",
    "desktop_gui":     "PyWebView desktop app",
    "github_support":  "Submit issues via GitHub bridge",
    "finetuning":      "Fine-tuning pipeline",
}


def describe_feature(feature: str) -> str:
    return PREMIUM_FEATURES[feature]


def is_premium(feature: str) -> bool:
    return feature in PREMIUM_FEATURES
```

- [ ] **Step 4: Run, pass**

Run: `pytest tests/test_features_gating.py -v`
Expected: 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add api/services/features.py tests/test_features_gating.py
git commit -m "feat: premium feature registry"
```

---

## Task 5: FastAPI dependency for feature gating

**Files:**
- Create: `api/dependencies.py`
- Modify: `api/main.py` (stash LicenseService on app.state in lifespan)
- Modify: `tests/test_features_gating.py` (append)

- [ ] **Step 1: Write failing FastAPI test**

Append to `tests/test_features_gating.py`:

```python
from pathlib import Path
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient

from api.dependencies import require_license_feature
from api.services.license_service import LicenseService


FIXTURES = Path(__file__).parent / "fixtures"


def _app_with_license(svc: LicenseService) -> FastAPI:
    app = FastAPI()
    app.state.license = svc

    @app.get("/premium", dependencies=[Depends(require_license_feature("workflow_engine"))])
    def premium():
        return {"ok": True}

    @app.get("/free")
    def free():
        return {"ok": True}

    return app


class TestRequireLicenseFeatureDep:
    def test_licensed_passes(self):
        svc = LicenseService(
            license_path=FIXTURES / "valid_license.key",
            pubkey_path=FIXTURES / "test_license_pubkey.pem",
        )
        svc.load()
        client = TestClient(_app_with_license(svc))
        assert client.get("/premium").status_code == 200

    def test_unlicensed_returns_402(self, tmp_path):
        svc = LicenseService(
            license_path=tmp_path / "absent.key",
            pubkey_path=FIXTURES / "test_license_pubkey.pem",
        )
        svc.load()
        client = TestClient(_app_with_license(svc))
        r = client.get("/premium")
        assert r.status_code == 402
        body = r.json()
        assert body["error"] == "license_required"
        assert body["feature"] == "workflow_engine"
        assert body["purchase_url"].startswith("http")

    def test_free_endpoint_always_works(self, tmp_path):
        svc = LicenseService(license_path=tmp_path / "absent.key", pubkey_path=FIXTURES / "test_license_pubkey.pem")
        svc.load()
        client = TestClient(_app_with_license(svc))
        assert client.get("/free").status_code == 200
```

- [ ] **Step 2: Run, fail**

Run: `pytest tests/test_features_gating.py::TestRequireLicenseFeatureDep -v`
Expected: module `api.dependencies` missing.

- [ ] **Step 3: Write `api/dependencies.py`**

```python
#!/usr/bin/env python3
"""FastAPI dependencies — license gating."""
from __future__ import annotations

from typing import Callable

from fastapi import HTTPException, Request

from api.services.license_service import LicenseRequiredError, LicenseService


def get_license_service(request: Request) -> LicenseService:
    svc: LicenseService | None = getattr(request.app.state, "license", None)
    if svc is None:
        raise RuntimeError("LicenseService not attached to app.state.license")
    return svc


def require_license_feature(feature: str) -> Callable:
    """FastAPI dependency factory — return 402 if the feature isn't licensed."""

    def _dep(request: Request) -> None:
        svc = get_license_service(request)
        try:
            svc.require_feature(feature)
        except LicenseRequiredError as e:
            raise HTTPException(
                status_code=402,
                detail={
                    "error": "license_required",
                    "feature": e.feature,
                    "purchase_url": e.purchase_url,
                },
            ) from e

    return _dep
```

- [ ] **Step 4: FastAPI 402 body fix**

FastAPI's `HTTPException` wraps `detail` in `{"detail": ...}`. We need it at the top level. Override with a custom exception handler, or use `JSONResponse`. Simpler — use a custom exception handler.

Add to `api/dependencies.py`:

```python
from fastapi.responses import JSONResponse


class LicenseRequiredHTTPException(HTTPException):
    def __init__(self, feature: str, purchase_url: str) -> None:
        super().__init__(status_code=402, detail=feature)
        self.feature = feature
        self.purchase_url = purchase_url


def license_required_handler(request: Request, exc: LicenseRequiredHTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=402,
        content={
            "error": "license_required",
            "feature": exc.feature,
            "purchase_url": exc.purchase_url,
        },
    )
```

Update `require_license_feature` to raise `LicenseRequiredHTTPException` instead.

Then, in the TestClient setup inside `_app_with_license`, register the handler:

```python
    app.add_exception_handler(LicenseRequiredHTTPException, license_required_handler)
```

Re-run the tests.

- [ ] **Step 5: Run, pass**

Run: `pytest tests/test_features_gating.py -v`
Expected: all pass.

- [ ] **Step 6: Wire into `api/main.py`**

In the lifespan function, after the existing startup log lines, add:

```python
from api.services.license_service import LicenseService
from api.dependencies import LicenseRequiredHTTPException, license_required_handler

# ... inside lifespan, after auth_status line:
license_svc = LicenseService()
license_svc.load()
app.state.license = license_svc
logger.info(f"  License: {license_svc.status().state.value}")
if license_svc.status().license:
    logger.info(f"  License ID: {license_svc.status().license.license_id}")
```

Register the exception handler right after the `app = FastAPI(...)` line:

```python
app.add_exception_handler(LicenseRequiredHTTPException, license_required_handler)
```

- [ ] **Step 7: Run full test suite to catch regressions**

Run: `pytest tests/ -v -x`
Expected: existing tests still pass; new license tests pass.

- [ ] **Step 8: Commit**

```bash
git add api/dependencies.py api/main.py tests/test_features_gating.py
git commit -m "feat: FastAPI require_license_feature dependency + startup load"
```

---

## Task 6: Gate the workflow router

**Files:**
- Modify: `api/routers/workflows.py`
- Create: `tests/test_workflow_gating.py`

- [ ] **Step 1: Identify the routes to gate**

Run: `grep -n "^@router" api/routers/workflows.py`
Note the route-definition lines; apply gating to all POST/PUT/DELETE routes that *execute* workflows (not GET list / GET status — those are safe to leave free so an unlicensed user's installed CLI doesn't 402 everywhere).

- [ ] **Step 2: Write failing test**

```python
# tests/test_workflow_gating.py
from pathlib import Path
from fastapi.testclient import TestClient

FIXTURES = Path(__file__).parent / "fixtures"


def _client_with(license_path: Path | None):
    # Build the full app but swap license path via env.
    import os
    os.environ["LICENSE_KEY_PATH"] = str(license_path) if license_path else str(FIXTURES / "absent.key")
    os.environ["LICENSE_PUBKEY_PATH"] = str(FIXTURES / "test_license_pubkey.pem")
    # Force a fresh import of main because it reads env at startup.
    import importlib
    import api.main as m
    importlib.reload(m)
    return TestClient(m.app)


def test_workflow_run_requires_license():
    client = _client_with(None)
    r = client.post("/api/workflows/run", json={"workflow_id": "x", "seed": {}})
    assert r.status_code == 402
    assert r.json()["feature"] == "workflow_engine"


def test_workflow_run_works_with_license():
    client = _client_with(FIXTURES / "valid_license.key")
    # This can still fail for a missing workflow (404), but it must NOT be 402.
    r = client.post("/api/workflows/run", json={"workflow_id": "nonexistent", "seed": {}})
    assert r.status_code != 402
```

Note: we also need `api/main.py`'s `LicenseService()` to honor `LICENSE_PUBKEY_PATH`. Add that env var:

```python
# api/services/license_service.py — __init__:
self._pubkey_path = Path(
    os.getenv("LICENSE_PUBKEY_PATH") or pubkey_path or DEFAULT_PUBKEY_PATH
)
```

- [ ] **Step 3: Run, fail**

Run: `pytest tests/test_workflow_gating.py -v`
Expected: first test returns 200 or 404, not 402.

- [ ] **Step 4: Apply gate**

Edit `api/routers/workflows.py`. Replace the existing POST-run decorator with:

```python
from api.dependencies import require_license_feature

@router.post("/run", dependencies=[Depends(require_license_feature("workflow_engine"))])
async def run_workflow(...):
    ...
```

Apply the same `dependencies=[...]` to any other execution endpoints (e.g., `/validate` is OK free; `/run`, `/cancel`, `/delete-run` should be gated).

- [ ] **Step 5: Run, pass**

Run: `pytest tests/test_workflow_gating.py -v`
Expected: both tests pass.

- [ ] **Step 6: Full regression**

Run: `pytest tests/ -v -x`
Expected: all prior workflow tests still pass (they use the direct engine, not the router — gate applies only at router level).

- [ ] **Step 7: Commit**

```bash
git add api/services/license_service.py api/routers/workflows.py tests/test_workflow_gating.py
git commit -m "feat: gate /api/workflows/run behind workflow_engine license"
```

---

## Task 7: CLI dispatch gate on `cli/workflow.py run`

**Files:**
- Modify: `cli/workflow.py`
- Create: `tests/test_cli_workflow_gating.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_cli_workflow_gating.py
import os
import subprocess
import sys
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
REPO = Path(__file__).parent.parent


def _run_cli(args: list[str], license_path: Path | None) -> subprocess.CompletedProcess:
    env = {**os.environ}
    env["LICENSE_KEY_PATH"] = str(license_path) if license_path else str(FIXTURES / "absent.key")
    env["LICENSE_PUBKEY_PATH"] = str(FIXTURES / "test_license_pubkey.pem")
    return subprocess.run(
        [sys.executable, str(REPO / "cli" / "workflow.py"), *args],
        capture_output=True, text=True, env=env, cwd=REPO,
    )


def test_run_without_license_exits_2():
    result = _run_cli(["run", "nonexistent.yaml"], license_path=None)
    assert result.returncode == 2
    assert "license" in (result.stdout + result.stderr).lower()
    assert "purchase" in (result.stdout + result.stderr).lower()


def test_list_without_license_works():
    result = _run_cli(["list"], license_path=None)
    # list is free; may exit 0 or 1 based on workflow dir, but NOT 2.
    assert result.returncode != 2
```

- [ ] **Step 2: Run, fail**

Run: `pytest tests/test_cli_workflow_gating.py -v`
Expected: exit code is 0 or 1, not 2.

- [ ] **Step 3: Add gate to `cli/workflow.py run` handler**

In `cli/workflow.py`, import the service at the top (after existing imports):

```python
from api.services.license_service import LicenseService, LicenseRequiredError
```

Find the `run` command handler (the function invoked for `args.command == "run"`). At the very start of that function, insert:

```python
    license_svc = LicenseService()
    license_svc.load()
    try:
        license_svc.require_feature("workflow_engine")
    except LicenseRequiredError as e:
        console.print()
        console.print("[bold yellow]⚠️  This feature requires a license.[/bold yellow]")
        console.print()
        console.print(f"  Feature:     Multi-agent workflow engine")
        console.print(f"  Tier:        Individual ($49, lifetime)")
        console.print(f"  Purchase:    {e.purchase_url}")
        console.print()
        console.print("Already purchased? Drop your license.key into ~/.local-ai-platform/")
        sys.exit(2)
```

- [ ] **Step 4: Run, pass**

Run: `pytest tests/test_cli_workflow_gating.py -v`
Expected: both pass.

- [ ] **Step 5: Commit**

```bash
git add cli/workflow.py tests/test_cli_workflow_gating.py
git commit -m "feat: CLI workflow run gate"
```

---

## Task 8: `cli/license.py` (show, verify, install)

**Files:**
- Create: `cli/license.py`
- Create: `tests/test_cli_license.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_cli_license.py
import os
import shutil
import subprocess
import sys
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
REPO = Path(__file__).parent.parent


def _run(args, env_extra=None, input_=None):
    env = {**os.environ}
    if env_extra: env.update(env_extra)
    return subprocess.run(
        [sys.executable, str(REPO / "cli" / "license.py"), *args],
        capture_output=True, text=True, env=env, input=input_, cwd=REPO,
    )


def test_show_unlicensed(tmp_path):
    absent = tmp_path / "absent.key"
    r = _run(["show"], env_extra={
        "LICENSE_KEY_PATH": str(absent),
        "LICENSE_PUBKEY_PATH": str(FIXTURES / "test_license_pubkey.pem"),
    })
    assert r.returncode == 0
    assert "unlicensed" in r.stdout.lower()


def test_show_licensed():
    r = _run(["show"], env_extra={
        "LICENSE_KEY_PATH": str(FIXTURES / "valid_license.key"),
        "LICENSE_PUBKEY_PATH": str(FIXTURES / "test_license_pubkey.pem"),
    })
    assert r.returncode == 0
    assert "licensed" in r.stdout.lower()
    assert "alice@example.com" in r.stdout


def test_verify_valid():
    r = _run(["verify"], env_extra={
        "LICENSE_KEY_PATH": str(FIXTURES / "valid_license.key"),
        "LICENSE_PUBKEY_PATH": str(FIXTURES / "test_license_pubkey.pem"),
    })
    assert r.returncode == 0


def test_verify_tampered():
    r = _run(["verify"], env_extra={
        "LICENSE_KEY_PATH": str(FIXTURES / "tampered_license.key"),
        "LICENSE_PUBKEY_PATH": str(FIXTURES / "test_license_pubkey.pem"),
    })
    assert r.returncode == 1
    assert "invalid" in r.stdout.lower() or "invalid" in r.stderr.lower()


def test_install_copies_file(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    src = FIXTURES / "valid_license.key"
    r = _run(["install", str(src)], env_extra={
        "HOME": str(home),
        "LICENSE_PUBKEY_PATH": str(FIXTURES / "test_license_pubkey.pem"),
    })
    assert r.returncode == 0
    assert (home / ".local-ai-platform" / "license.key").exists()
```

- [ ] **Step 2: Run, fail**

Run: `pytest tests/test_cli_license.py -v`
Expected: cli/license.py missing.

- [ ] **Step 3: Write `cli/license.py`**

```python
#!/usr/bin/env python3
"""
License management CLI.

Usage:
  python cli/license.py show
  python cli/license.py verify
  python cli/license.py install <path/to/license.key>
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

# Add repo root to path for imports.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rich.console import Console
from rich.panel import Panel

from api.services.license_service import (
    DEFAULT_LICENSE_PATH,
    LicenseService,
    LicenseState,
)

console = Console()


def cmd_show(_args) -> int:
    svc = LicenseService()
    status = svc.load()
    state = status.state.value
    lines = [f"State: [bold]{state}[/bold]"]
    if status.license:
        lic = status.license
        lines += [
            f"License ID: {lic.license_id}",
            f"Email:      {lic.email}",
            f"Tier:       {lic.tier}",
            f"Issued:     {lic.issued_at}",
            f"Features:   {', '.join(lic.features)}",
        ]
        if lic.test:
            lines.append("[yellow]⚠ Test license — not a real purchase[/yellow]")
    if status.error:
        lines.append(f"[red]Error:[/red] {status.error}")
    if status.source_path:
        lines.append(f"Path:       {status.source_path}")
    console.print(Panel("\n".join(lines), title="Local AI Platform License", border_style="cyan"))
    return 0


def cmd_verify(_args) -> int:
    svc = LicenseService()
    status = svc.load()
    if status.state == LicenseState.LICENSED:
        console.print("[green]✓ License valid.[/green]")
        return 0
    if status.state == LicenseState.UNLICENSED:
        console.print("[yellow]No license installed.[/yellow]")
        return 1
    console.print(f"[red]License {status.state.value}: {status.error or '(no detail)'}[/red]")
    return 1


def cmd_install(args) -> int:
    src = Path(args.source).expanduser()
    if not src.is_file():
        console.print(f"[red]Source not found: {src}[/red]")
        return 1
    dest = DEFAULT_LICENSE_PATH
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    console.print(f"Installed license → {dest}")
    # Verify
    svc = LicenseService()
    status = svc.load()
    if status.state == LicenseState.LICENSED:
        console.print("[green]✓ License valid.[/green]")
        return 0
    console.print(f"[yellow]Installed, but state is {status.state.value}: {status.error or ''}[/yellow]")
    return 1 if status.state != LicenseState.LICENSED else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="License management")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("show", help="Print current license status")
    sub.add_parser("verify", help="Exit 0 if licensed, 1 otherwise")
    install = sub.add_parser("install", help="Copy a license file into place")
    install.add_argument("source", help="Path to .license file received via email")

    args = parser.parse_args()
    return {
        "show": cmd_show,
        "verify": cmd_verify,
        "install": cmd_install,
    }[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run, pass**

Run: `pytest tests/test_cli_license.py -v`
Expected: 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add cli/license.py tests/test_cli_license.py
git commit -m "feat: cli/license.py show/verify/install"
```

---

## Task 9: X-LocalAI-License-Status header middleware

**Files:**
- Modify: `api/middleware.py`
- Modify: `api/main.py` (add middleware)
- Create: `tests/test_license_header.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_license_header.py
import os
from pathlib import Path
from fastapi.testclient import TestClient

FIXTURES = Path(__file__).parent / "fixtures"


def _client(license_path: Path):
    os.environ["LICENSE_KEY_PATH"] = str(license_path)
    os.environ["LICENSE_PUBKEY_PATH"] = str(FIXTURES / "test_license_pubkey.pem")
    import importlib
    import api.main as m
    importlib.reload(m)
    return TestClient(m.app)


def test_header_unlicensed(tmp_path):
    client = _client(tmp_path / "absent.key")
    r = client.get("/health")
    assert r.headers.get("X-LocalAI-License-Status") == "unlicensed"


def test_header_licensed():
    client = _client(FIXTURES / "valid_license.key")
    r = client.get("/health")
    assert r.headers.get("X-LocalAI-License-Status") == "licensed"
```

- [ ] **Step 2: Run, fail**

Run: `pytest tests/test_license_header.py -v`
Expected: header missing.

- [ ] **Step 3: Add middleware in `api/middleware.py`**

Append:

```python
from starlette.middleware.base import BaseHTTPMiddleware


class LicenseHeaderMiddleware(BaseHTTPMiddleware):
    """Attaches X-LocalAI-License-Status to every response."""

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        svc = getattr(request.app.state, "license", None)
        if svc is not None:
            response.headers["X-LocalAI-License-Status"] = svc.status().state.value
        return response
```

- [ ] **Step 4: Register in `api/main.py`**

After existing `app.add_middleware(...)` calls add:

```python
from api.middleware import LicenseHeaderMiddleware
app.add_middleware(LicenseHeaderMiddleware)
```

- [ ] **Step 5: Run, pass**

Run: `pytest tests/test_license_header.py -v`
Expected: both pass.

- [ ] **Step 6: Commit**

```bash
git add api/middleware.py api/main.py tests/test_license_header.py
git commit -m "feat: X-LocalAI-License-Status response header"
```

---

## Task 10: 1-in-5 CLI chat nag footer

**Files:**
- Modify: `cli/chat.py`
- Create: `tests/test_cli_chat_nag.py`

- [ ] **Step 1: Write failing test — deterministic RNG injection**

```python
# tests/test_cli_chat_nag.py
import os
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


def test_should_show_nag_probability(monkeypatch):
    from cli.chat import should_show_license_nag

    # Deterministic: 0.0 < 0.2 → show; 0.5 > 0.2 → don't show.
    monkeypatch.setattr("cli.chat.random.random", lambda: 0.05)
    assert should_show_license_nag(is_licensed=False) is True

    monkeypatch.setattr("cli.chat.random.random", lambda: 0.5)
    assert should_show_license_nag(is_licensed=False) is False


def test_nag_never_when_licensed(monkeypatch):
    from cli.chat import should_show_license_nag
    monkeypatch.setattr("cli.chat.random.random", lambda: 0.0)
    assert should_show_license_nag(is_licensed=True) is False
```

- [ ] **Step 2: Run, fail**

Run: `pytest tests/test_cli_chat_nag.py -v`
Expected: import error.

- [ ] **Step 3: Add `should_show_license_nag` + wire into chat loop**

In `cli/chat.py`, add near the top (after imports):

```python
import random

NAG_PROBABILITY = 0.2  # 1-in-5


def should_show_license_nag(is_licensed: bool) -> bool:
    if is_licensed:
        return False
    return random.random() < NAG_PROBABILITY


def render_license_nag(purchase_url: str) -> str:
    return f"💡 Support development — license $49 — {purchase_url}"
```

At the end of the chat's response loop (wherever the AI response is printed), add:

```python
from api.services.license_service import LicenseService, LicenseState
# (at module scope)
_license_svc = LicenseService()
_license_svc.load()
# ... inside the loop, after the AI response renders:
status = _license_svc.status()
if should_show_license_nag(status.state == LicenseState.LICENSED):
    purchase_url = os.getenv("LICENSE_PURCHASE_URL", "https://ohno.lemonsqueezy.com/local-ai-platform")
    console.print(f"[dim]{render_license_nag(purchase_url)}[/dim]")
```

- [ ] **Step 4: Run, pass**

Run: `pytest tests/test_cli_chat_nag.py -v`
Expected: 2 tests pass.

- [ ] **Step 5: Commit**

```bash
git add cli/chat.py tests/test_cli_chat_nag.py
git commit -m "feat: 1-in-5 license nag footer in cli/chat.py"
```

---

## Task 11: Desktop app banner

**Files:**
- Modify: `desktop/app.py`

Note: PyWebView banners are best implemented by injecting an HTML banner into the served index page. Since `desktop/app.py` spawns the API server and loads a URL, we add the banner as a `<div>` overlay via PyWebView's `evaluate_js` after page load.

- [ ] **Step 1: Add license check at desktop startup**

Edit `desktop/app.py`. After the FastAPI server is confirmed up and before `webview.create_window(...)`:

```python
from api.services.license_service import LicenseService, LicenseState

license_svc = LicenseService()
license_svc.load()
_LICENSE_STATE = license_svc.status().state.value
```

Then after `webview.create_window(...)`, add a small helper that injects the banner:

```python
import webview

def _inject_banner(window):
    if _LICENSE_STATE == "licensed":
        return
    purchase_url = os.getenv("LICENSE_PURCHASE_URL", "https://ohno.lemonsqueezy.com/local-ai-platform")
    msg = {
        "unlicensed": "Unlicensed — premium features disabled.",
        "invalid":   "License invalid — please re-install your license.",
        "revoked":   "License revoked — contact support.",
    }.get(_LICENSE_STATE, "License state unknown.")
    js = f"""
    (function() {{
      if (document.getElementById('laip-license-banner')) return;
      var d = document.createElement('div');
      d.id = 'laip-license-banner';
      d.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:9999;background:#f0ad4e;color:#222;padding:8px 12px;font:13px system-ui;text-align:center;';
      d.innerHTML = '⚠ {msg} <a href="{purchase_url}" target="_blank" style="color:#111;text-decoration:underline;">Purchase a license</a>';
      document.body.appendChild(d);
      document.body.style.paddingTop = (d.offsetHeight + 2) + 'px';
    }})();
    """
    try:
        window.evaluate_js(js)
    except Exception:
        pass  # window may not be ready; next load will retry


webview.start(lambda w: _inject_banner(w), window)
```

Existing `webview.start(...)` call should be replaced with this lambda form.

- [ ] **Step 2: Manual smoke test**

```bash
source venv/bin/activate
rm -f ~/.local-ai-platform/license.key   # force unlicensed
python desktop/app.py
```
Expected: window opens, banner visible at top.

Then:
```bash
cp tests/fixtures/valid_license.key ~/.local-ai-platform/license.key
# relaunch desktop/app.py
```
Expected: no banner (licensed).

- [ ] **Step 3: Commit**

```bash
git add desktop/app.py
git commit -m "feat: desktop license banner for unlicensed/invalid/revoked"
```

---

## Task 12: Redaction module (property-based tests)

**Files:**
- Create: `cli/support_redact.py`
- Create: `tests/test_support_redaction.py`
- Modify: `setup/requirements-dev.txt` (add hypothesis)

- [ ] **Step 1: Ensure `hypothesis` available**

Confirm `hypothesis` is in `setup/requirements-dev.txt`. If missing, add `hypothesis>=6`. Run:
```bash
pip install hypothesis
```

- [ ] **Step 2: Write failing tests**

```python
# tests/test_support_redaction.py
import re

import pytest
from hypothesis import given, strategies as st

from cli.support_redact import redact


class TestRedactUserPaths:
    def test_redacts_user_home_on_darwin(self):
        text = "Error in /Users/alice/projects/secret/file.py"
        assert redact(text, own_email="x@y.com") == "Error in /Users/<user>/projects/secret/file.py"

    def test_redacts_user_home_on_linux(self):
        text = "Error in /home/alice/projects/file.py"
        assert "/home/<user>/" in redact(text, own_email="x@y.com")


class TestRedactApiKeys:
    @pytest.mark.parametrize("key", [
        "sk-abcdef0123456789abcdef0123456789",
        "sk_live_abcdef0123456789abcdef0123",
        "ghp_0123456789abcdefABCDEFghijklmn0123",
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIn0.tokenpart",
    ])
    def test_redacts_common_key_shapes(self, key):
        out = redact(f"token: {key}", own_email="x@y.com")
        assert "[REDACTED]" in out
        assert key not in out


class TestRedactLicenseBlob:
    def test_redacts_full_license_pem(self):
        pem = (
            "-----BEGIN LOCAL-AI-PLATFORM LICENSE-----\n"
            "abc123\n.\nxyz789\n"
            "-----END LOCAL-AI-PLATFORM LICENSE-----"
        )
        out = redact(f"config:\n{pem}\nother", own_email="x@y.com")
        assert "LOCAL-AI-PLATFORM LICENSE" not in out
        assert "abc123" not in out
        assert "[REDACTED_LICENSE]" in out


class TestRedactEmails:
    def test_preserves_own_email(self):
        out = redact("Mine: alice@example.com, Not: bob@example.com", own_email="alice@example.com")
        assert "alice@example.com" in out
        assert "bob@example.com" not in out
        assert "[email]" in out


SECRETS = [
    "sk-verysecretverysecretverysecret0123",
    "ghp_topsecretTOKENtopsecretTOKEN0123",
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJhbGljZSJ9.sig",
]


class TestRedactionPropertyBased:
    @given(st.text(min_size=0, max_size=500))
    def test_never_leaks_known_secrets(self, noise):
        # Inject each known secret somewhere in the noise.
        for secret in SECRETS:
            text = noise + " " + secret + " " + noise
            out = redact(text, own_email="x@y.com")
            assert secret not in out, f"Leaked secret {secret!r} through redaction"
```

- [ ] **Step 3: Run, fail**

Run: `pytest tests/test_support_redaction.py -v`
Expected: module missing.

- [ ] **Step 4: Write `cli/support_redact.py`**

```python
#!/usr/bin/env python3
"""
Client-side redaction for support submissions.

Redaction is a SECURITY BOUNDARY — issues land on a public GitHub repo.
These patterns are intentionally conservative (false positives are fine;
false negatives are not).
"""
from __future__ import annotations

import re

# Token-shaped secrets. Each pattern matches a broad shape but resists
# matching ordinary prose.
_TOKEN_PATTERNS = [
    re.compile(r"sk[-_][A-Za-z0-9_\-]{20,}"),                        # sk-..., sk_live_...
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),                             # GitHub PAT classic
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),                     # GitHub PAT fine-grained
    re.compile(r"(?:gho|ghs|ghu|ghr)_[A-Za-z0-9]{20,}"),             # Other GitHub tokens
    re.compile(r"eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+"),  # JWT
    re.compile(r"AKIA[0-9A-Z]{16}"),                                 # AWS access key
    re.compile(r"laip_[A-Z0-9]{26}"),                                # Our own license IDs
    re.compile(r"[A-Fa-f0-9]{64}"),                                  # Generic 64-hex (HMAC, digest)
    re.compile(r"[A-Za-z0-9+/]{44,}={0,2}"),                         # Long base64 (catch-all; false-positive-prone)
]

_LICENSE_BLOCK = re.compile(
    r"-----BEGIN LOCAL-AI-PLATFORM LICENSE-----.*?-----END LOCAL-AI-PLATFORM LICENSE-----",
    re.DOTALL,
)

_PATH_RE = re.compile(r"(/Users|/home|/Users/home)/([^/\s]+)/")

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


def redact(text: str, *, own_email: str) -> str:
    """Return a redacted copy of text.

    Rules:
      1. License PEM blocks → [REDACTED_LICENSE]
      2. Token shapes (JWT, sk-, ghp_, AWS AKIA, license IDs, 64-hex, long base64) → [REDACTED]
      3. Third-party emails → [email]; own_email preserved verbatim
      4. /Users/<name>/ and /home/<name>/ → /<origin>/<user>/
    """
    # 1. License blocks first (because step 2's catch-all base64 would hit their body).
    text = _LICENSE_BLOCK.sub("[REDACTED_LICENSE]", text)

    # 2. Tokens.
    for pat in _TOKEN_PATTERNS:
        text = pat.sub("[REDACTED]", text)

    # 3. Emails. Preserve own_email.
    own = own_email.lower()
    def _sub_email(m: re.Match) -> str:
        return m.group(0) if m.group(0).lower() == own else "[email]"
    text = _EMAIL_RE.sub(_sub_email, text)

    # 4. Paths.
    text = _PATH_RE.sub(lambda m: f"{m.group(1)}/<user>/", text)

    return text
```

- [ ] **Step 5: Run, pass**

Run: `pytest tests/test_support_redaction.py -v`
Expected: all tests pass (including property-based).

- [ ] **Step 6: Commit**

```bash
git add cli/support_redact.py tests/test_support_redaction.py
git commit -m "feat: redaction module with property-based secret-leak tests"
```

---

## Task 13: Support client service

**Files:**
- Create: `api/services/support_service.py`
- Create: `tests/test_support_service.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_support_service.py
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from api.services.license_service import LicenseService
from api.services.support_service import (
    SupportSubmission,
    SupportService,
    SupportQueuedError,
    SupportRateLimitError,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def licensed_svc():
    svc = LicenseService(
        license_path=FIXTURES / "valid_license.key",
        pubkey_path=FIXTURES / "test_license_pubkey.pem",
    )
    svc.load()
    return svc


def _submission() -> SupportSubmission:
    return SupportSubmission(
        title="Workflow hangs",
        body="Step 3 stalls after 30 seconds. Full log attached.",
        severity="bug",
        app_version="0.4.2",
        os="macOS 15.3 arm64",
        python="3.12.7",
        installed_models=["mistral", "dolphin-mixtral"],
        attachments=[],
    )


class TestSubmitHappyPath:
    def test_posts_with_license_header(self, licensed_svc, tmp_path):
        svc = SupportService(
            license_svc=licensed_svc,
            endpoint="https://license.test/support/issues",
            queue_dir=tmp_path / "queue",
        )
        mock_resp = MagicMock(status_code=201)
        mock_resp.json.return_value = {"number": 42, "html_url": "https://gh/42"}
        with patch("api.services.support_service.requests.post", return_value=mock_resp) as m:
            result = svc.submit(_submission())
        assert result["number"] == 42
        call = m.call_args
        assert call.kwargs["headers"]["X-Local-AI-License"]
        body = call.kwargs["json"]
        assert body["title"] == "Workflow hangs"
        assert body["metadata"]["app_version"] == "0.4.2"


class TestRedactionIsApplied:
    def test_redacts_before_sending(self, licensed_svc, tmp_path):
        submission = _submission()
        submission.body = "Failed on /Users/alice/foo and token ghp_1234567890abcdefABCDEF1234"
        svc = SupportService(
            license_svc=licensed_svc,
            endpoint="https://license.test/support/issues",
            queue_dir=tmp_path / "queue",
        )
        mock_resp = MagicMock(status_code=201)
        mock_resp.json.return_value = {"number": 1, "html_url": ""}
        with patch("api.services.support_service.requests.post", return_value=mock_resp) as m:
            svc.submit(submission)
        sent = m.call_args.kwargs["json"]["body"]
        assert "/Users/<user>/" in sent
        assert "[REDACTED]" in sent
        assert "ghp_" not in sent


class TestQueueOnNetworkFailure:
    def test_queues_when_endpoint_unreachable(self, licensed_svc, tmp_path):
        svc = SupportService(
            license_svc=licensed_svc,
            endpoint="https://license.test/support/issues",
            queue_dir=tmp_path / "queue",
        )
        with patch("api.services.support_service.requests.post", side_effect=ConnectionError("offline")):
            with pytest.raises(SupportQueuedError):
                svc.submit(_submission())
        assert any((tmp_path / "queue").glob("*.json"))


class TestRateLimit:
    def test_raises_on_429(self, licensed_svc, tmp_path):
        svc = SupportService(
            license_svc=licensed_svc,
            endpoint="https://license.test/support/issues",
            queue_dir=tmp_path / "queue",
        )
        mock_resp = MagicMock(status_code=429, text="rate limit exceeded (daily)")
        with patch("api.services.support_service.requests.post", return_value=mock_resp):
            with pytest.raises(SupportRateLimitError):
                svc.submit(_submission())
        # Should NOT have been queued (rate-limit is permanent for the window).
        assert not any((tmp_path / "queue").glob("*.json"))


class TestRetryQueued:
    def test_sends_all_queued_items(self, licensed_svc, tmp_path):
        svc = SupportService(
            license_svc=licensed_svc,
            endpoint="https://license.test/support/issues",
            queue_dir=tmp_path / "queue",
        )
        (tmp_path / "queue").mkdir()
        # Seed a queued submission.
        import json
        qpath = tmp_path / "queue" / "abc.json"
        qpath.write_text(json.dumps({
            "title": "t", "body": "b", "severity": "bug",
            "metadata": {"app_version": "0", "os": "o", "python": "p", "models": []},
            "attachments": [],
        }))
        mock_resp = MagicMock(status_code=201)
        mock_resp.json.return_value = {"number": 7, "html_url": ""}
        with patch("api.services.support_service.requests.post", return_value=mock_resp):
            sent = svc.retry_queued()
        assert sent == 1
        assert not qpath.exists()
```

- [ ] **Step 2: Run, fail**

Run: `pytest tests/test_support_service.py -v`
Expected: module missing.

- [ ] **Step 3: Write `api/services/support_service.py`**

```python
#!/usr/bin/env python3
"""
Support service — redact, package, and submit an issue to license-service.
Queues on transient failures (network / 5xx). Does NOT queue on 401/403/429.
"""
from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Literal, Optional

import requests

from api.services.license_service import LicenseService, LicenseState
from cli.support_redact import redact


DEFAULT_ENDPOINT = os.getenv("LICENSE_SERVICE_URL", "https://license.ohno.dev") + "/support/issues"
DEFAULT_QUEUE_DIR = Path.home() / ".local-ai-platform" / "support" / "queued"
TIMEOUT_SECONDS = 20


class SupportError(Exception):
    pass


class SupportUnlicensedError(SupportError):
    pass


class SupportRateLimitError(SupportError):
    pass


class SupportQueuedError(SupportError):
    """Raised when the submission was saved locally instead of sent."""
    def __init__(self, path: Path):
        super().__init__(f"network error; queued to {path}")
        self.path = path


@dataclass
class SupportAttachment:
    name: str
    content_base64: str


@dataclass
class SupportSubmission:
    title: str
    body: str
    severity: Literal["bug", "question", "feature_request"]
    app_version: str
    os: str
    python: str
    installed_models: list[str] = field(default_factory=list)
    attachments: list[SupportAttachment] = field(default_factory=list)

    def to_wire(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "body": self.body,
            "severity": self.severity,
            "metadata": {
                "app_version": self.app_version,
                "os": self.os,
                "python": self.python,
                "models": self.installed_models,
            },
            "attachments": [asdict(a) for a in self.attachments],
        }


class SupportService:
    def __init__(
        self,
        license_svc: LicenseService,
        endpoint: str = DEFAULT_ENDPOINT,
        queue_dir: Path = DEFAULT_QUEUE_DIR,
    ) -> None:
        self._license_svc = license_svc
        self._endpoint = endpoint
        self._queue_dir = Path(queue_dir)

    def submit(self, submission: SupportSubmission) -> dict[str, Any]:
        status = self._license_svc.status()
        if status.state != LicenseState.LICENSED or status.license is None:
            raise SupportUnlicensedError("a valid license is required to submit support issues")

        lic = status.license
        submission.body = redact(submission.body, own_email=lic.email)
        submission.title = redact(submission.title, own_email=lic.email)

        license_pem = status.source_path.read_text() if status.source_path else ""
        headers = {
            "Content-Type": "application/json",
            "X-Local-AI-License": base64.b64encode(license_pem.encode()).decode(),
        }

        try:
            resp = requests.post(
                self._endpoint,
                json=submission.to_wire(),
                headers=headers,
                timeout=TIMEOUT_SECONDS,
            )
        except (requests.ConnectionError, requests.Timeout, ConnectionError, TimeoutError):
            path = self._queue(submission)
            raise SupportQueuedError(path)

        if resp.status_code == 429:
            raise SupportRateLimitError(resp.text)
        if resp.status_code in (401, 403):
            raise SupportError(f"authorization failed: {resp.status_code} {resp.text}")
        if 500 <= resp.status_code < 600:
            path = self._queue(submission)
            raise SupportQueuedError(path)
        if not resp.ok:
            raise SupportError(f"unexpected response: {resp.status_code} {resp.text}")
        return resp.json()

    def retry_queued(self) -> int:
        if not self._queue_dir.exists():
            return 0
        sent = 0
        for path in sorted(self._queue_dir.glob("*.json")):
            data = json.loads(path.read_text())
            submission = SupportSubmission(
                title=data["title"],
                body=data["body"],
                severity=data["severity"],
                app_version=data["metadata"]["app_version"],
                os=data["metadata"]["os"],
                python=data["metadata"]["python"],
                installed_models=data["metadata"].get("models", []),
                attachments=[SupportAttachment(**a) for a in data.get("attachments", [])],
            )
            try:
                self.submit(submission)
                path.unlink()
                sent += 1
            except SupportQueuedError:
                # Still offline; stop trying, preserve existing queue order.
                break
            except SupportError:
                # Don't lose the file on unexpected errors; let the user inspect.
                break
        return sent

    def _queue(self, submission: SupportSubmission) -> Path:
        self._queue_dir.mkdir(parents=True, exist_ok=True)
        fname = f"{int(time.time() * 1000)}.json"
        path = self._queue_dir / fname
        path.write_text(json.dumps(submission.to_wire(), indent=2))
        return path
```

- [ ] **Step 4: Run, pass**

Run: `pytest tests/test_support_service.py -v`
Expected: 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add api/services/support_service.py tests/test_support_service.py
git commit -m "feat: support submission service with redaction + queue"
```

---

## Task 14: cli/support.py (file-issue, retry-queued)

**Files:**
- Create: `cli/support.py`

- [ ] **Step 1: Write `cli/support.py`**

```python
#!/usr/bin/env python3
"""
Support CLI — submit structured issues to GitHub via license-service.

Usage:
  python cli/support.py file-issue
  python cli/support.py file-issue --title "..." --body-file bug.md
  python cli/support.py file-issue --attach-logs --attach-config
  python cli/support.py retry-queued
"""
from __future__ import annotations

import argparse
import base64
import getpass
import os
import platform
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm

from api.services.license_service import LicenseService, LicenseState
from api.services.support_service import (
    SupportAttachment,
    SupportService,
    SupportSubmission,
    SupportUnlicensedError,
    SupportQueuedError,
    SupportRateLimitError,
)


console = Console()


def _gather_models() -> list[str]:
    try:
        r = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            # "NAME       ID   SIZE   MODIFIED"
            lines = r.stdout.strip().splitlines()[1:]
            return [ln.split()[0] for ln in lines if ln.strip()]
    except (OSError, subprocess.TimeoutExpired):
        pass
    return []


def _read_logs(limit_bytes: int = 64 * 1024) -> Optional[str]:
    log_dir = Path.home() / ".local-ai-platform" / "logs"
    if not log_dir.exists():
        log_dir = Path("data/logs")
    if not log_dir.exists():
        return None
    logs = sorted(log_dir.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not logs:
        return None
    data = logs[0].read_bytes()[-limit_bytes:]
    return data.decode(errors="replace")


def _read_config_redacted() -> Optional[str]:
    dotenv = Path(".env")
    if not dotenv.exists():
        return None
    lines = []
    for ln in dotenv.read_text().splitlines():
        if "=" not in ln or ln.strip().startswith("#"):
            lines.append(ln)
            continue
        key, _ = ln.split("=", 1)
        lines.append(f"{key}=***")
    return "\n".join(lines)


def _prompt_editor(initial: str) -> str:
    editor = os.environ.get("EDITOR", "vi")
    with tempfile.NamedTemporaryFile("w+", suffix=".md", delete=False) as f:
        f.write(initial)
        path = f.name
    try:
        subprocess.run([editor, path], check=False)
        return Path(path).read_text()
    finally:
        try: os.unlink(path)
        except OSError: pass


def cmd_file_issue(args) -> int:
    license_svc = LicenseService()
    license_svc.load()
    status = license_svc.status()
    if status.state != LicenseState.LICENSED:
        console.print("[yellow]GitHub support requires a license.[/yellow]")
        console.print(f"Purchase: {os.getenv('LICENSE_PURCHASE_URL', 'https://ohno.lemonsqueezy.com/local-ai-platform')}")
        return 2

    title = args.title
    body = ""
    if args.body_file:
        body = Path(args.body_file).read_text()
    elif not args.title:
        template = (
            "# Title (edit me)\n\n"
            "## What happened\n\n"
            "## Steps to reproduce\n\n"
            "## Expected\n\n"
            "## Actual\n"
        )
        raw = _prompt_editor(template)
        lines = raw.splitlines()
        title = next((l[2:].strip() for l in lines if l.startswith("# ")), "Untitled")
        body = "\n".join(l for l in lines if not l.startswith("# "))

    if not title or not body.strip():
        console.print("[red]Empty title or body.[/red]")
        return 1

    # Attachments
    attachments: list[SupportAttachment] = []
    if args.attach_logs:
        logs = _read_logs()
        if logs:
            attachments.append(SupportAttachment(
                name="logs.txt",
                content_base64=base64.b64encode(logs.encode()).decode(),
            ))
    if args.attach_config:
        cfg = _read_config_redacted()
        if cfg:
            attachments.append(SupportAttachment(
                name="config.txt",
                content_base64=base64.b64encode(cfg.encode()).decode(),
            ))

    submission = SupportSubmission(
        title=title,
        body=body,
        severity=args.severity,
        app_version=os.getenv("LAIP_VERSION", "0.1.0"),
        os=f"{platform.system()} {platform.release()} {platform.machine()}",
        python=platform.python_version(),
        installed_models=_gather_models(),
        attachments=attachments,
    )

    # Review screen
    preview_lines = [
        f"[bold]Title:[/bold] {submission.title}",
        f"[bold]Severity:[/bold] {submission.severity}",
        f"[bold]Version:[/bold] {submission.app_version}",
        f"[bold]OS:[/bold] {submission.os}",
        f"[bold]Python:[/bold] {submission.python}",
        f"[bold]Models:[/bold] {', '.join(submission.installed_models) or '(none)'}",
        f"[bold]Attachments:[/bold] {', '.join(a.name for a in submission.attachments) or '(none)'}",
        "",
        "[bold]Body (after redaction):[/bold]",
        "",
        body[:2000] + ("..." if len(body) > 2000 else ""),
    ]
    console.print(Panel("\n".join(preview_lines), title="Support issue — review", border_style="cyan"))
    if not args.yes and not Confirm.ask("Submit?", default=False):
        console.print("[yellow]Cancelled.[/yellow]")
        return 1

    svc = SupportService(license_svc=license_svc)
    try:
        result = svc.submit(submission)
    except SupportUnlicensedError:
        console.print("[red]License no longer valid.[/red]"); return 1
    except SupportRateLimitError as e:
        console.print(f"[red]Rate limit exceeded: {e}[/red]"); return 1
    except SupportQueuedError as e:
        console.print(f"[yellow]Offline — queued locally at {e.path}. Re-run with 'retry-queued' later.[/yellow]")
        return 0
    console.print(f"[green]Issue created:[/green] {result.get('html_url') or f'#{result.get(\"number\")}'}")
    return 0


def cmd_retry_queued(_args) -> int:
    svc = LicenseService(); svc.load()
    if svc.status().state != LicenseState.LICENSED:
        console.print("[yellow]Not licensed.[/yellow]"); return 2
    support = SupportService(license_svc=svc)
    sent = support.retry_queued()
    console.print(f"Sent {sent} queued submission(s).")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Support CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    fi = sub.add_parser("file-issue", help="Submit a new support issue")
    fi.add_argument("--title")
    fi.add_argument("--body-file")
    fi.add_argument("--severity", default="bug", choices=["bug", "question", "feature_request"])
    fi.add_argument("--attach-logs", action="store_true")
    fi.add_argument("--attach-config", action="store_true")
    fi.add_argument("--yes", "-y", action="store_true", help="Skip confirmation")

    sub.add_parser("retry-queued", help="Retry any queued submissions")

    args = p.parse_args()
    if args.cmd == "file-issue":
        return cmd_file_issue(args)
    if args.cmd == "retry-queued":
        return cmd_retry_queued(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Smoke test with a fixture license**

```bash
cp tests/fixtures/valid_license.key /tmp/fixture_license.key
LICENSE_KEY_PATH=/tmp/fixture_license.key \
LICENSE_PUBKEY_PATH=tests/fixtures/test_license_pubkey.pem \
LICENSE_SERVICE_URL=http://localhost:12345 \
python cli/support.py file-issue --title "smoke" --body-file README.md --yes
```
Expected: attempts POST to http://localhost:12345/support/issues → connection refused → queued message + exit 0.

- [ ] **Step 3: Commit**

```bash
git add cli/support.py
git commit -m "feat: cli/support.py file-issue + retry-queued"
```

---

## Task 15: API /v1/support/issues router

**Files:**
- Create: `api/routers/support.py`
- Modify: `api/main.py` (register router)
- Create: `tests/test_support_router.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_support_router.py
import os
from pathlib import Path
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

FIXTURES = Path(__file__).parent / "fixtures"


def _client(license_path: Path):
    os.environ["LICENSE_KEY_PATH"] = str(license_path)
    os.environ["LICENSE_PUBKEY_PATH"] = str(FIXTURES / "test_license_pubkey.pem")
    import importlib
    import api.main as m
    importlib.reload(m)
    return TestClient(m.app)


def test_unlicensed_returns_402(tmp_path):
    client = _client(tmp_path / "absent.key")
    r = client.post(
        "/v1/support/issues",
        json={"title": "t", "body": "body of issue", "severity": "bug"},
    )
    assert r.status_code == 402


def test_licensed_forwards_to_service():
    client = _client(FIXTURES / "valid_license.key")
    mock_resp = MagicMock(status_code=201)
    mock_resp.json.return_value = {"number": 1, "html_url": "https://gh/1"}
    with patch("api.services.support_service.requests.post", return_value=mock_resp):
        r = client.post(
            "/v1/support/issues",
            json={"title": "bug", "body": "repro: /Users/a/b", "severity": "bug"},
        )
    assert r.status_code == 201
    assert r.json()["number"] == 1
```

- [ ] **Step 2: Run, fail**

Run: `pytest tests/test_support_router.py -v`
Expected: 404.

- [ ] **Step 3: Write `api/routers/support.py`**

```python
#!/usr/bin/env python3
"""POST /v1/support/issues — local API for support submission."""
from __future__ import annotations

import platform
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from api.dependencies import get_license_service, require_license_feature
from api.services.support_service import (
    SupportAttachment,
    SupportService,
    SupportSubmission,
    SupportQueuedError,
    SupportRateLimitError,
)


router = APIRouter(prefix="/v1/support", tags=["support"])


class SupportIssueBody(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    body: str = Field(min_length=10, max_length=50_000)
    severity: Literal["bug", "question", "feature_request"] = "bug"
    installed_models: list[str] = Field(default_factory=list)
    attachments: list[dict] = Field(default_factory=list)


@router.post(
    "/issues",
    status_code=201,
    dependencies=[Depends(require_license_feature("github_support"))],
)
async def file_issue(payload: SupportIssueBody, request: Request):
    license_svc = get_license_service(request)
    submission = SupportSubmission(
        title=payload.title,
        body=payload.body,
        severity=payload.severity,
        app_version="0.1.0",
        os=f"{platform.system()} {platform.release()} {platform.machine()}",
        python=platform.python_version(),
        installed_models=payload.installed_models,
        attachments=[SupportAttachment(**a) for a in payload.attachments],
    )
    svc = SupportService(license_svc=license_svc)
    try:
        return svc.submit(submission)
    except SupportRateLimitError as e:
        raise HTTPException(status_code=429, detail=str(e))
    except SupportQueuedError as e:
        raise HTTPException(status_code=503, detail=f"queued to {e.path}")
```

- [ ] **Step 4: Register in `api/main.py`**

```python
from api.routers import support  # top of file, with other router imports
# ... after existing include_router lines:
app.include_router(support.router)
```

- [ ] **Step 5: Run, pass**

Run: `pytest tests/test_support_router.py -v`
Expected: 2 tests pass.

- [ ] **Step 6: Commit**

```bash
git add api/routers/support.py api/main.py tests/test_support_router.py
git commit -m "feat: POST /v1/support/issues router"
```

---

## Task 16: Revocation list fetcher

**Files:**
- Create: `api/services/revocation_fetcher.py`
- Modify: `api/services/license_service.py` (accept dynamic revocations)
- Modify: `api/main.py` (async fetch on startup)
- Create: `tests/test_revocation_fetcher.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_revocation_fetcher.py
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

from api.services.revocation_fetcher import fetch_revocations, load_cached_revocations


class TestFetchRevocations:
    def test_returns_list_on_success(self, tmp_path):
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {"revoked": ["laip_a", "laip_b"], "updated_at": "2026-04-19T00:00:00Z"}
        with patch("api.services.revocation_fetcher.requests.get", return_value=mock_resp):
            revs = fetch_revocations(url="https://x", cache_path=tmp_path / "revs.json", ttl_seconds=3600)
        assert revs == frozenset(["laip_a", "laip_b"])
        cached = json.loads((tmp_path / "revs.json").read_text())
        assert cached["revoked"] == ["laip_a", "laip_b"]

    def test_returns_cached_on_network_failure(self, tmp_path):
        (tmp_path / "revs.json").write_text(json.dumps({
            "revoked": ["laip_cached"], "fetched_at": 0,
        }))
        with patch("api.services.revocation_fetcher.requests.get", side_effect=ConnectionError()):
            revs = fetch_revocations(url="https://x", cache_path=tmp_path / "revs.json", ttl_seconds=3600)
        assert revs == frozenset(["laip_cached"])

    def test_returns_empty_when_no_cache_and_network_fails(self, tmp_path):
        with patch("api.services.revocation_fetcher.requests.get", side_effect=ConnectionError()):
            revs = fetch_revocations(url="https://x", cache_path=tmp_path / "revs.json", ttl_seconds=3600)
        assert revs == frozenset()

    def test_uses_cache_inside_ttl(self, tmp_path):
        import time
        (tmp_path / "revs.json").write_text(json.dumps({
            "revoked": ["laip_cached"],
            "fetched_at": time.time(),
        }))
        # Network should NOT be called.
        with patch("api.services.revocation_fetcher.requests.get") as m:
            revs = fetch_revocations(url="https://x", cache_path=tmp_path / "revs.json", ttl_seconds=3600)
            assert not m.called
        assert revs == frozenset(["laip_cached"])
```

- [ ] **Step 2: Run, fail**

Run: `pytest tests/test_revocation_fetcher.py -v`
Expected: module missing.

- [ ] **Step 3: Write `api/services/revocation_fetcher.py`**

```python
#!/usr/bin/env python3
"""
Revocation list fetcher — optional, advisory.

Silent on any failure. The license signature is the primary trust anchor;
the revocation list is a secondary defense for chargebacks.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import FrozenSet

import requests


DEFAULT_TTL = 7 * 24 * 3600
DEFAULT_CACHE = Path.home() / ".local-ai-platform" / "revocations.json"


def fetch_revocations(
    url: str,
    cache_path: Path = DEFAULT_CACHE,
    ttl_seconds: int = DEFAULT_TTL,
    timeout: int = 5,
) -> FrozenSet[str]:
    cached = load_cached_revocations(cache_path)
    if _is_fresh(cache_path, ttl_seconds):
        return cached

    try:
        resp = requests.get(url, timeout=timeout)
        if resp.status_code == 200:
            data = resp.json()
            revoked = list(data.get("revoked", []))
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps({"revoked": revoked, "fetched_at": time.time()}))
            return frozenset(revoked)
    except (requests.RequestException, ConnectionError, ValueError):
        pass
    return cached


def load_cached_revocations(cache_path: Path) -> FrozenSet[str]:
    if not cache_path.exists():
        return frozenset()
    try:
        data = json.loads(cache_path.read_text())
        return frozenset(data.get("revoked", []))
    except (OSError, json.JSONDecodeError):
        return frozenset()


def _is_fresh(cache_path: Path, ttl_seconds: int) -> bool:
    if not cache_path.exists():
        return False
    try:
        data = json.loads(cache_path.read_text())
        fetched_at = float(data.get("fetched_at", 0))
        return (time.time() - fetched_at) < ttl_seconds
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return False
```

- [ ] **Step 4: Wire into startup**

Edit `api/main.py` lifespan. Add before `license_svc = LicenseService()`:

```python
from api.services.revocation_fetcher import fetch_revocations

revocations_url = os.getenv("LICENSE_SERVICE_URL", "https://license.ohno.dev") + "/revocations.json"
try:
    revocations = fetch_revocations(url=revocations_url)
except Exception as e:
    logger.warning(f"  Revocation fetch failed: {e}")
    revocations = frozenset()

license_svc = LicenseService(revocations=revocations)
```

- [ ] **Step 5: Run, pass**

Run: `pytest tests/test_revocation_fetcher.py tests/test_license_service.py -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add api/services/revocation_fetcher.py api/main.py tests/test_revocation_fetcher.py
git commit -m "feat: revocation list fetcher with offline-first cache"
```

---

## Task 17: User documentation

**Files:**
- Create: `docs/LICENSING.md`
- Create: `docs/SUPPORT.md`

- [ ] **Step 1: Write `docs/LICENSING.md`**

```markdown
# Licensing

Local AI Platform is free for basic use. A one-time **$49 lifetime license** unlocks premium features.

## What the license unlocks

| Feature | Free | Licensed |
|---|:-:|:-:|
| Chat & completions (single model) | ✓ | ✓ |
| Model download & registry | ✓ | ✓ |
| OpenAI-compatible API | ✓ | ✓ |
| Multi-agent workflow engine |   | ✓ |
| RAG pipeline (ChromaDB) |   | ✓ |
| Multi-model orchestration |   | ✓ |
| Desktop GUI |   | ✓ |
| GitHub support bridge |   | ✓ |
| Fine-tuning pipeline |   | ✓ |

## Purchase

[ohno.lemonsqueezy.com/local-ai-platform](https://ohno.lemonsqueezy.com/local-ai-platform) — $49 USD, one-time.

We use Lemon Squeezy as our Merchant of Record, so VAT and sales tax
are handled automatically regardless of your country.

## Install

After purchase you'll receive an email with `license.key` attached. Install it:

```bash
python cli/license.py install ~/Downloads/license.key
python cli/license.py show   # confirm: State: licensed
```

Or manually: move `license.key` into `~/.local-ai-platform/license.key` and restart the app.

## Lost the email?

Three recovery options, in order of effort:

1. The original email contains a **re-send link** — click it.
2. Visit [license.ohno.dev/recover](https://license.ohno.dev/recover) and enter your order number + email.
3. Email `support@ohno.dev` with your order number.

## Multiple machines

The license has no hardware binding — install it on as many of your own
machines as you like.

## Refunds

30-day refund policy, no questions asked. Refunds revoke the license
automatically; it stops working on next app startup.

## Privacy

- License verification is fully offline. The app does **not** phone home at launch.
- A revocation-list fetch happens opportunistically on startup (cached 7 days). It's anonymous — no license ID is sent, we just download the list.
- No usage analytics.
```

- [ ] **Step 2: Write `docs/SUPPORT.md`**

```markdown
# Support

Licensed users can file structured issues that land directly on our public GitHub repo with a `supported` label, triaged with priority.

## How to file an issue

### CLI (recommended)

```bash
python cli/support.py file-issue
```

Opens your `$EDITOR` with a template. Fill it out, save, and review the preview before it's sent.

Flags:
- `--title "short summary"` — skip the editor, provide title directly
- `--body-file bug.md` — use the contents of a file as the body
- `--severity bug|question|feature_request` — defaults to `bug`
- `--attach-logs` — include last 64KB of the newest log file (redacted)
- `--attach-config` — include `.env` with secret values stripped
- `--yes` / `-y` — skip the final confirmation prompt

### Desktop app

**Help → Report an Issue** opens a form within the app.

### API

`POST /v1/support/issues` — licensed local API:

```bash
curl -X POST http://localhost:8000/v1/support/issues \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Workflow hangs on step 3",
    "body": "The workflow engine stalls after the summarize step.",
    "severity": "bug",
    "installed_models": ["dolphin-mixtral"]
  }'
```

## What we redact before sending

Your submission is scrubbed **client-side** before it leaves your machine:
- API keys, license keys, tokens (sk-*, ghp_*, JWTs, AWS keys) → `[REDACTED]`
- Your license PEM block if it appears in logs → `[REDACTED_LICENSE]`
- Absolute user paths (`/Users/you/...`, `/home/you/...`) → `/Users/<user>/...`
- Emails other than your license email → `[email]`

You can inspect the exact payload before confirming. A copy is always saved
to `~/.local-ai-platform/support/last-submission.json`.

## What maintainers see

The public issue body shows your redacted description, environment, and attachments. Your **license ID and email** are posted as a separate comment that is visible only to repo maintainers, never in the public thread. We reply via the issue — GitHub will email you notifications.

## Limits

Rate limits per license:
- **10 issues / day**
- **50 issues / month**

Attachment limit: 256 KB inline. For larger log bundles, ask the CLI for a
signed upload URL: `python cli/support.py file-issue --large-bundle` (planned).

## Offline

If the support endpoint is unreachable when you file an issue, the CLI
saves the submission locally and exits successfully. Run
`python cli/support.py retry-queued` when you're back online.

## Unlicensed?

The GitHub support bridge is a licensed feature. You can still file issues
directly on the public repo manually — we just triage licensed issues first.

[Purchase a license](https://ohno.lemonsqueezy.com/local-ai-platform) · $49 · lifetime
```

- [ ] **Step 3: Commit**

```bash
git add docs/LICENSING.md docs/SUPPORT.md
git commit -m "docs: user-facing licensing and support guides"
```

---

## Task 18: Production public key placeholder + final regression

**Files:**
- Create: `api/keys/license_pubkey.pem` (placeholder until Worker is deployed)
- Create: `api/keys/.gitkeep`
- Create: `api/keys/README.md`

- [ ] **Step 1: Create placeholder & README**

Write `api/keys/README.md`:

```markdown
# License public key

`license_pubkey.pem` is the Ed25519 public key used to verify license files.

**Generation:** run `npm run generate-keypair` inside the `license-service` repo.
The script prints the PEM; copy it here. The matching private key is stored as
a Cloudflare Worker Secret (`LICENSE_SIGNING_KEY`) and must never be checked in.

**Rotation:** if the private key is ever compromised:
1. Generate a new keypair in `license-service`.
2. Re-sign all existing active licenses with the new key (admin reissue flow).
3. Ship a release of this repo with the new public key.

Until the production key is generated, this file contains a placeholder;
tests use `tests/fixtures/test_license_pubkey.pem`.
```

Write `api/keys/license_pubkey.pem`:

```
-----BEGIN PUBLIC KEY-----
PLACEHOLDER_REPLACE_WITH_PRODUCTION_ED25519_PUBLIC_KEY
-----END PUBLIC KEY-----
```

This file intentionally does **not** validate. The app's `LicenseService`
logs a clear error if the production key is still the placeholder.

- [ ] **Step 2: Add placeholder detection in `license_service.py`**

In `_read_and_verify`, after reading the pubkey bytes:

```python
        if b"PLACEHOLDER" in self._pubkey_path.read_bytes():
            return LicenseStatus(
                state=LicenseState.INVALID,
                source_path=path,
                error="production public key not installed — see api/keys/README.md",
            )
```

- [ ] **Step 3: Full regression**

Run: `source venv/bin/activate && pytest tests/ -v`
Expected: all tests green. Count the new tests created in this plan — should be roughly 40+ new tests passing.

- [ ] **Step 4: Commit**

```bash
git add api/keys/
git commit -m "chore: license public-key placeholder + rotation docs"
```

---

## Task 19: Release behind a feature flag

**Files:**
- Modify: `api/main.py` (respect `LICENSING_ENABLED` env)
- Modify: `.env.example`

- [ ] **Step 1: Add LICENSING_ENABLED flag**

Edit `api/main.py` lifespan so the license load + enforcement is skipped when `LICENSING_ENABLED=false`:

```python
if os.getenv("LICENSING_ENABLED", "false").lower() == "true":
    revocations_url = os.getenv("LICENSE_SERVICE_URL", "https://license.ohno.dev") + "/revocations.json"
    try:
        revocations = fetch_revocations(url=revocations_url)
    except Exception as e:
        logger.warning(f"  Revocation fetch failed: {e}")
        revocations = frozenset()
    license_svc = LicenseService(revocations=revocations)
    license_svc.load()
    app.state.license = license_svc
    logger.info(f"  License: {license_svc.status().state.value}")
else:
    # Flag off — attach a permissive stand-in so the dep still imports.
    from api.services.license_service import License, LicenseStatus, LicenseState
    class _AllowAllLicenseService:
        def status(self): return LicenseStatus(state=LicenseState.LICENSED)
        def has_feature(self, f): return True
        def require_feature(self, f): return None
    app.state.license = _AllowAllLicenseService()
    logger.info("  License: DISABLED (LICENSING_ENABLED=false)")
```

- [ ] **Step 2: Add env var to `.env.example`**

```
# Licensing (default off until launch)
LICENSING_ENABLED=false
LICENSE_KEY_PATH=
LICENSE_PUBKEY_PATH=
LICENSE_SERVICE_URL=https://license.ohno.dev
LICENSE_PURCHASE_URL=https://ohno.lemonsqueezy.com/local-ai-platform
LICENSE_ENFORCEMENT=strict
```

- [ ] **Step 3: Regression**

Run: `pytest tests/ -v`
Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add api/main.py .env.example
git commit -m "feat: LICENSING_ENABLED feature flag for staged rollout"
```

---

## Self-Review Checklist (completed during plan authoring)

**1. Spec coverage:**
- Spec §3 architecture (in-app half) → Tasks 2–9, 11, 16.
- Spec §4 license file format → Tasks 2–3.
- Spec §5 enforcement (three points) → Tasks 5 (FastAPI), 6 (workflow router), 7 (CLI), 11 (desktop). Nag & header → Tasks 9, 10.
- Spec §6 support flow → Tasks 12 (redaction), 13 (service), 14 (CLI), 15 (router).
- Spec §8 repo structure → matches file list above.
- Spec §9 error handling matrix → covered in tests for `LicenseService` (Task 3), `SupportService` (Task 13), revocation fetcher (Task 16).
- Spec §10 testing strategy → property-based (Task 12), fixture-based integration (Tasks 3, 5, 6).
- Spec §11 release sequence → Task 19 flag.

**2. Placeholder scan:**
- `api/keys/license_pubkey.pem` contains an intentional `PLACEHOLDER` sentinel (Task 18) — this is explicit, detected at runtime, and documented. Not a plan failure.
- No `TODO`, `TBD`, or vague "add validation" left in any step.

**3. Type consistency:**
- `LicenseService` / `License` / `LicenseStatus` / `LicenseState` defined in Task 2, used consistently thereafter.
- `SupportSubmission` / `SupportAttachment` / `SupportService` signatures stable between Tasks 13, 14, 15.
- `PREMIUM_FEATURES` keys (`workflow_engine`, etc.) match the `features` list in `make_license.py` (Task 1) and the gating calls in Tasks 5–7.

**4. Scope check:**
- Plan focused on in-app code; Worker is a separate plan (`2026-04-19-license-service-worker.md`).
- Team tier, AI PR automation, web portal — explicitly out of scope per spec §12.

## Out of Scope (confirmed)

- Team-tier seat management.
- AI-assisted PR generation.
- Customer web portal.
- Cross-platform desktop UI tests (manual smoke in Task 11 is sufficient).
