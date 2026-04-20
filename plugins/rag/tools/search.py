"""RAG search tool — agent-callable retrieval over indexed documents."""


def execute(query: str, top_k: int = 5) -> dict:
    """Search indexed documents and return top-k relevant chunks."""
    from api.routers.documents import rag_service
    if rag_service is None:
        return {"error": "RAG pipeline unavailable"}
    return rag_service.search(query=query, top_k=top_k)
