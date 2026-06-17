"""Provenance store — durable response→source grounding chains.

Mirrors the storage idioms already used by ``workflow_engine`` (atomic
tmp+os.replace for the header JSON) and ``a2a_service`` / ``memory_store``
(append-only JSONL for the edge log). No external dependencies, no lock
files — the header write is atomic and the edge log is append-only, which
is sufficient for a single-operator appliance.

Layout::

    {PROVENANCE_DATA_DIR}/
      responses/{response_id}.json     # ResponseProvenance header (no edges)
      edges/{response_id}.jsonl        # one ProvenanceEdge per line

Splitting header from edges keeps appends cheap (no read-modify-write) while
still letting the graph builder enumerate every response by scanning
``responses/``.
"""

import json
import os
from pathlib import Path
from typing import List, Optional

from ..logging_config import logger
from ..models.provenance_models import ProvenanceEdge, ResponseProvenance

PROVENANCE_DATA_DIR = os.getenv("PROVENANCE_DATA_DIR", "./data/provenance")

# A response_id becomes a filename; reject anything that isn't a safe slug so
# a hostile X-Conversation-ID-derived id can't escape the store directory.
_SAFE_ID_CHARS = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_."
)


def _safe_id(response_id: str) -> str:
    rid = (response_id or "").strip()
    if not rid or not all(c in _SAFE_ID_CHARS for c in rid) or rid in (".", ".."):
        raise ValueError(f"unsafe response_id: {response_id!r}")
    return rid


class ProvenanceStore:
    """Persist and retrieve response grounding chains."""

    def __init__(self, base_dir: Optional[str] = None):
        self.base = Path(base_dir or PROVENANCE_DATA_DIR)
        self.responses_dir = self.base / "responses"
        self.edges_dir = self.base / "edges"

    # ── Write ────────────────────────────────────────────────────────────

    def record(self, prov: ResponseProvenance) -> None:
        """Persist a full grounding chain in one shot (header + all edges).

        Best-effort: provenance is observability, never on the critical path
        of answering the user, so a write failure is logged and swallowed.
        """
        try:
            rid = _safe_id(prov.response_id)
            self.responses_dir.mkdir(parents=True, exist_ok=True)
            self.edges_dir.mkdir(parents=True, exist_ok=True)

            header = prov.model_dump(mode="json")
            header.pop("edges", None)  # edges live in the jsonl sidecar
            path = self.responses_dir / f"{rid}.json"
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(header, indent=2, default=str), encoding="utf-8")
            os.replace(tmp, path)

            if prov.edges:
                epath = self.edges_dir / f"{rid}.jsonl"
                with open(epath, "w", encoding="utf-8") as f:
                    for e in prov.edges:
                        f.write(
                            json.dumps(e.model_dump(mode="json"), default=str) + "\n"
                        )
        except Exception as exc:  # noqa: BLE001 — never break the response
            logger.warning(f"provenance: failed to record {prov.response_id!r}: {exc}")

    # ── Read ─────────────────────────────────────────────────────────────

    def get_edges(self, response_id: str) -> List[ProvenanceEdge]:
        try:
            rid = _safe_id(response_id)
        except ValueError:
            return []
        path = self.edges_dir / f"{rid}.jsonl"
        if not path.exists():
            return []
        out: List[ProvenanceEdge] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(ProvenanceEdge.model_validate_json(line))
            except Exception:  # noqa: BLE001 — skip a torn/old line, keep the rest
                continue
        return out

    def get(self, response_id: str) -> Optional[ResponseProvenance]:
        """Return the full chain (header + edges) for one response."""
        try:
            rid = _safe_id(response_id)
        except ValueError:
            return None
        path = self.responses_dir / f"{rid}.json"
        if not path.exists():
            return None
        try:
            header = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"provenance: failed to read {rid!r}: {exc}")
            return None
        header["edges"] = [e.model_dump(mode="json") for e in self.get_edges(rid)]
        try:
            return ResponseProvenance.model_validate(header)
        except Exception:  # noqa: BLE001
            return None

    def list_responses(self) -> List[ResponseProvenance]:
        """Enumerate every recorded response (header only, no edges loaded).

        Used by the graph builder. Edge counts are read lazily by callers via
        ``get_edges`` to keep this scan cheap.
        """
        out: List[ResponseProvenance] = []
        if not self.responses_dir.exists():
            return out
        for f in sorted(self.responses_dir.glob("*.json")):
            try:
                header = json.loads(f.read_text(encoding="utf-8"))
                header.setdefault("edges", [])
                out.append(ResponseProvenance.model_validate(header))
            except Exception:  # noqa: BLE001
                continue
        return out


# Module-level singleton, matching the other services' access pattern.
_store: Optional[ProvenanceStore] = None


def get_provenance_store() -> ProvenanceStore:
    global _store
    if _store is None:
        _store = ProvenanceStore()
    return _store
