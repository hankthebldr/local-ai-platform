"""Local AI Platform API"""

# Single source of truth for the API version. Surfaced via /health,
# /api/info, the root response, and FastAPI's auto-generated OpenAPI docs.
# Bump on every release; cross-reference CHANGELOG.md and the git tag.
__version__ = "1.1.0"
