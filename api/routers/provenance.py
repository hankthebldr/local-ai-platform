#!/usr/bin/env python3
"""
Provenance Router — response → source grounding chains.

GET /api/provenance/response/{response_id} → full chain (header + edges)
GET /api/provenance/responses              → enumerate recorded responses

The citation rail under each chat message reads the response chain; the
knowledge graph reads the enumeration to draw grounded_on / activated_skill /
invoked_tool edges. Provenance is observability — these endpoints never
mutate state.
"""

from fastapi import APIRouter, HTTPException

from ..services.provenance_store import get_provenance_store

router = APIRouter(prefix="/api/provenance", tags=["provenance"])


@router.get("/responses")
async def list_response_provenance():
    """Enumerate every recorded response (headers only, no edges loaded)."""
    store = get_provenance_store()
    rows = store.list_responses()
    return {
        "total": len(rows),
        "responses": [r.model_dump(mode="json") for r in rows],
    }


@router.get("/response/{response_id}")
async def get_response_provenance(response_id: str):
    """Return the full grounding chain for one response."""
    store = get_provenance_store()
    prov = store.get(response_id)
    if prov is None:
        raise HTTPException(
            status_code=404, detail=f"no provenance for response {response_id!r}"
        )
    return prov.model_dump(mode="json")
