"""Example web search tool for the plugin system"""


def execute(query: str, max_results: int = 5) -> dict:
    """
    Search the web and return results.

    This is a placeholder implementation. Replace with actual search
    logic (e.g., calling the platform's search_service).
    """
    return {
        "results": [
            {
                "title": f"Result for: {query}",
                "url": f"https://example.com/search?q={query}",
                "snippet": f"This is a placeholder result for '{query}'. "
                "Replace this tool with a real search implementation.",
            }
        ],
        "query": query,
        "total": 1,
    }
