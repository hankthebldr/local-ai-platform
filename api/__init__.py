"""Local AI Platform API"""

# Single source of truth for the API version. Surfaced via /health,
# /api/info, the root response, and FastAPI's auto-generated OpenAPI docs.
#
# Bump on every release. When you bump this, ALSO update:
#   1. CHANGELOG.md   — promote [Unreleased] to the new version section
#   2. CLAUDE.md      — "Current" line in the Release track section
#   3. api/static/index.html — search for the `Enclave v…` footer string
#                              (id="footer-version"). The static markup test
#                              tests/ui/test_static_markup.py asserts these
#                              stay in lockstep with this constant.
#
# (Templating the footer at serve-time would eliminate the drift class;
# tracked as a Phase 1.4 candidate.)
__version__ = "1.1.1"
