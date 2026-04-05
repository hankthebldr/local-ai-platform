#!/usr/bin/env python3
"""
Exports Router — Save, list, read, and delete chat session Markdown exports.

Exports are stored as .md files in data/exports/ on the server.
The frontend generates the Markdown and POSTs it here.
"""

import os
import re
from pathlib import Path
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from ..logging_config import logger

router = APIRouter(prefix="/api/exports", tags=["exports"])

EXPORTS_DIR = Path(__file__).parent.parent.parent / "data" / "exports"


def _ensure_dir():
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)


def _safe_filename(name: str) -> str:
    """Sanitize a filename to prevent path traversal."""
    name = os.path.basename(name)
    name = re.sub(r"[^\w\-.]", "_", name)
    if not name.endswith(".md"):
        name += ".md"
    return name


# ── Endpoints ──────────────────────────────────────────────────────────────


class SaveRequest(BaseModel):
    filename: str = Field(..., description="Filename for the export (e.g., 2026-03-30-1245-dolphin3.md)")
    content: str = Field(..., description="Markdown content of the chat session")


@router.post("/save")
async def save_export(req: SaveRequest):
    """Save a chat session Markdown export to disk."""
    _ensure_dir()
    filename = _safe_filename(req.filename)
    filepath = EXPORTS_DIR / filename

    filepath.write_text(req.content, encoding="utf-8")
    logger.info(f"Session exported: {filename} ({len(req.content)} chars)")

    return {
        "status": "saved",
        "filename": filename,
        "path": str(filepath),
        "size": len(req.content),
    }


@router.get("")
async def list_exports():
    """List all saved exports, newest first."""
    _ensure_dir()
    files = sorted(EXPORTS_DIR.glob("*.md"), key=lambda f: f.stat().st_mtime, reverse=True)

    exports = []
    for f in files:
        stat = f.stat()
        exports.append({
            "filename": f.name,
            "size": stat.st_size,
            "modified": stat.st_mtime,
            "preview": f.read_text(encoding="utf-8")[:200],
        })

    return {"exports": exports, "count": len(exports)}


@router.get("/{filename}")
async def read_export(filename: str):
    """Read a specific export file."""
    safe = _safe_filename(filename)
    filepath = EXPORTS_DIR / safe

    if not filepath.exists():
        return {"error": "not_found", "filename": safe}

    content = filepath.read_text(encoding="utf-8")
    return PlainTextResponse(content, media_type="text/markdown")


@router.delete("/{filename}")
async def delete_export(filename: str):
    """Delete an export file."""
    safe = _safe_filename(filename)
    filepath = EXPORTS_DIR / safe

    if not filepath.exists():
        return {"status": "not_found", "filename": safe}

    filepath.unlink()
    logger.info(f"Export deleted: {safe}")
    return {"status": "deleted", "filename": safe}
