"""External-discovery provider modules.

Importing this package registers every provider with the central
agentic_discovery service. Each module under this package calls
``register_provider(...)`` at import time.

Wired providers (real ingestion):
  - mcp_registry  : Official MCP Registry (modelcontextprotocol.io/registry)

Stub providers (registered, surfaced in UI, not yet wired):
  - smithery        : community MCP registry (smithery.ai)
  - mcp_servers_gh  : modelcontextprotocol/servers GitHub reference repo
  - pulse_mcp       : Awesome-MCP / PulseMCP lists
  - github_prompts  : GitHub .prompt.yaml / .prompt.yml ingestion
  - x1xhlol_prompts : x1xhlol/system-prompts-and-models-of-ai-tools
  - claude_code_prompts : Piebald-AI/claude-code-system-prompts
  - claude_marketplaces : claudemarketplaces.com aggregator
  - composio        : Composio tool definitions (OpenAPI/Swagger)
  - openai_archives : historical ai-plugin.json scrape

Each stub registers with implemented=False; the UI shows it with a
"coming soon" affordance. Adding a real pipeline = swap the stub
import for a module that defines ``fetch()`` returning a populated
DiscoveryFeed.
"""

from . import mcp_registry  # noqa: F401  (real, registers on import)
from . import stubs  # noqa: F401  (all stubs in one file, registers on import)
