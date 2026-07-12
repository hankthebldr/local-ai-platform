"""
RAG ingest helper — the canonical shared seam for pushing captured markdown
artifacts into the document / RAG store so they become semantically searchable.

This is the ONE module every capture surface (research-artifact capture today,
RX-2 note/source saves + Operate promote later) calls to ingest markdown. It
imports the ``DocumentService`` singleton **function-locally** (from the
documents router, where the process-wide instance actually lives) so importing
this module never forces RAG initialization, and a disabled pipeline resolves to
``None`` rather than an ImportError. It is a graceful no-op when the backend is
unavailable and **never raises** — capture must always persist the artifact even
when the RAG store is down.

This replaces the dead best-effort block in ``feedback.py`` which did
``from ..services import document_service`` (the *module*, whose ``upload`` is a
method on the ``DocumentService`` class, not a module attribute) and gated on
``hasattr(module, "upload")`` — always ``False``, so nothing was ever ingested.
"""

from __future__ import annotations

from typing import List, Optional

from ..logging_config import logger

# Filename-safe cap for the derived document name (the title tail).
_TITLE_SLUG_MAX = 80
# Server-side clamp so a pathological body can't blow up the RAG store.
_BODY_MAX = 200_000


def _safe_slug(text: str) -> str:
    """Reduce a title to a filename-safe slug (alnum + space/dash/underscore)."""
    slug = "".join(
        c if (c.isalnum() or c in " -_") else "_" for c in (text or "")
    )
    return slug.strip()[:_TITLE_SLUG_MAX].strip() or "artifact"


def ingest_markdown(
    title: str,
    body: str,
    tags: Optional[List[str]] = None,
    doc_id: Optional[str] = None,
) -> bool:
    """Best-effort ingest of a markdown artifact into the RAG document store.

    Returns ``True`` when the artifact was handed to the document service,
    ``False`` when the RAG backend is unavailable or ingestion failed. Never
    raises — the caller has already persisted the durable artifact record and
    treats RAG indexing as an additive nicety.
    """
    try:
        # Function-local import + _ensure_rag() so a backend that came up after
        # boot heals here too. Keeps this module import-cheap and lets a
        # disabled pipeline be a plain ``None``.
        from ..routers.documents import _ensure_rag
        import api.routers.documents as _docs
        _ensure_rag()
        document_service = _docs.document_service
    except Exception as e:  # pragma: no cover - import guard
        logger.debug("RAG ingest skipped (documents router unavailable): %s", e)
        return False

    if document_service is None:
        return False

    try:
        slug = _safe_slug(title)
        prefix = f"{doc_id}-" if doc_id else ""
        filename = f"{prefix}{slug}.md"
        md = f"# {title}\n\n{(body or '')[:_BODY_MAX]}\n"
        if tags:
            md += "\n\n_tags: " + ", ".join(str(t) for t in tags) + "_\n"
        document_service.upload(filename, md.encode("utf-8"))
        return True
    except Exception as e:
        logger.debug("RAG ingest_markdown skipped: %s", e)
        return False
