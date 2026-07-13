#!/usr/bin/env python3
"""Stub providers — registered + surfaced in the UI, ingestion not yet wired.

Each entry below documents one of the upstream sources the platform
should ultimately ingest from. Registering them as stubs lets the
Discover surface show the operator what's *possible* before the
pipelines are live — and turns the act of wiring a real ingestion
into a one-line swap (replace ``stub_fetch(...)`` with a real
``fetch()``).

Sources adapted from the user's ingestion-strategy notes
(2026-05-18): MCP servers, system prompts, plugins / tool ecosystems.
"""

from __future__ import annotations

from ..agentic_discovery import register_provider, stub_fetch


# ── MCP Servers ──────────────────────────────────────────────────────

register_provider(
    source="smithery",
    name="Smithery",
    description=(
        "Community MCP registry — discover, configure, install. "
        "Classifies servers by use case (DBs, browser automation, dev tools)."
    ),
    homepage="https://smithery.ai",
    kinds=["mcp"],
    fetch=stub_fetch(
        source="smithery",
        name="Smithery",
        description="community MCP registry",
        homepage="https://smithery.ai",
        kinds=["mcp"],
        note=(
            "Stub. Wire a fetch() against https://smithery.ai's listing API "
            "(or scrape the public catalog) to populate."
        ),
    ),
    implemented=False,
)

register_provider(
    source="mcp-servers-gh",
    name="modelcontextprotocol/servers",
    description=(
        "Official Anthropic reference repo — foundational tool schemas "
        "(Brave Search, PostgreSQL, Puppeteer, …)."
    ),
    homepage="https://github.com/modelcontextprotocol/servers",
    kinds=["mcp"],
    fetch=stub_fetch(
        source="mcp-servers-gh",
        name="modelcontextprotocol/servers",
        description="reference MCP servers on GitHub",
        homepage="https://github.com/modelcontextprotocol/servers",
        kinds=["mcp"],
        note=(
            "Stub. Wire via GitHub contents API: read each src/*/README.md "
            "for description + extract package.json for npm install spec."
        ),
    ),
    implemented=False,
)

register_provider(
    source="pulse-mcp",
    name="PulseMCP / Awesome-MCP",
    description=(
        "Curated community lists — deployment scripts and ratings for "
        "secondary MCP servers."
    ),
    homepage="https://www.pulsemcp.com",
    kinds=["mcp"],
    fetch=stub_fetch(
        source="pulse-mcp",
        name="PulseMCP / Awesome-MCP",
        description="curated MCP server lists",
        homepage="https://www.pulsemcp.com",
        kinds=["mcp"],
        note="Stub. Either scrape PulseMCP HTML or parse the awesome-mcp README.",
    ),
    implemented=False,
)


# ── System Prompts ───────────────────────────────────────────────────

register_provider(
    source="github-prompts",
    name="GitHub .prompt.yaml",
    description=(
        "GitHub's native prompt-template format. Search API targets "
        "**/*.prompt.yaml across public repos for production-ready "
        "system templates with runtime variables + eval params."
    ),
    homepage="https://docs.github.com/en/copilot/concepts/prompt-files",
    kinds=["prompt"],
    fetch=stub_fetch(
        source="github-prompts",
        name="GitHub .prompt.yaml",
        description=".prompt.yaml across public repos",
        homepage="https://docs.github.com/en/copilot/concepts/prompt-files",
        kinds=["prompt"],
        note=(
            "Stub. Wire GitHub Code Search API: "
            "GET /search/code?q=extension:prompt.yaml + a small allow-list "
            "of starred orgs to avoid spam."
        ),
    ),
    implemented=False,
)

register_provider(
    source="x1xhlol-prompts",
    name="x1xhlol/system-prompts-and-models-of-ai-tools",
    description=(
        "Community-maintained directory tracking raw system prompts + "
        "tool-calling schemas of major AI applications (Cursor, "
        "Windsurf, …)."
    ),
    homepage="https://github.com/x1xhlol/system-prompts-and-models-of-ai-tools",
    kinds=["prompt"],
    fetch=stub_fetch(
        source="x1xhlol-prompts",
        name="x1xhlol/system-prompts-and-models-of-ai-tools",
        description="raw system prompts of major AI tools",
        homepage="https://github.com/x1xhlol/system-prompts-and-models-of-ai-tools",
        kinds=["prompt"],
        note=(
            "Stub. Walk the repo via the GitHub contents API; each folder "
            "is a tool; folder/Prompt.txt is the prompt; folder/Tools.json "
            "is the tool-call schema."
        ),
    ),
    implemented=False,
)

register_provider(
    source="claude-code-prompts",
    name="Piebald-AI/claude-code-system-prompts",
    description=(
        "Auto-updating extraction of Claude Code's system prompts, "
        "sub-agent behaviors (Plan/Explore/Task), and utility prompts."
    ),
    homepage="https://github.com/Piebald-AI/claude-code-system-prompts",
    kinds=["prompt"],
    fetch=stub_fetch(
        source="claude-code-prompts",
        name="Piebald-AI/claude-code-system-prompts",
        description="extracted Claude Code prompts",
        homepage="https://github.com/Piebald-AI/claude-code-system-prompts",
        kinds=["prompt"],
        note=(
            "Stub. Fetch the latest commit's top-level .md files via "
            "raw.githubusercontent.com — each maps to one DiscoveryItem."
        ),
    ),
    implemented=False,
)


# ── Plugins / Tool Ecosystems ────────────────────────────────────────
#
# claude-marketplaces graduated to a real digest-backed provider
# (claude_marketplaces.py, LB5-U1) — its stub is gone.

register_provider(
    source="composio",
    name="Composio",
    description=(
        "Bridge between local AI and production apps. Open-source tool "
        "definitions (OpenAPI/Swagger) for hundreds of integrations."
    ),
    homepage="https://docs.composio.dev",
    kinds=["tool", "plugin"],
    fetch=stub_fetch(
        source="composio",
        name="Composio",
        description="OpenAPI/Swagger tool defs",
        homepage="https://docs.composio.dev",
        kinds=["tool", "plugin"],
        note=(
            "Stub. Pull from https://api.composio.dev (or the OSS repo's "
            "app catalog JSON) and project into MCP-tool shape."
        ),
    ),
    implemented=False,
)

register_provider(
    source="openai-archives",
    name="OpenAI Plugin Archives",
    description=(
        "Historical scrape of the ChatGPT plugin store — raw "
        "ai-plugin.json schemas (still widely consumed by local platforms)."
    ),
    homepage="https://github.com/topics/chatgpt-plugins",
    kinds=["plugin"],
    fetch=stub_fetch(
        source="openai-archives",
        name="OpenAI Plugin Archives",
        description="historical ai-plugin.json schemas",
        homepage="https://github.com/topics/chatgpt-plugins",
        kinds=["plugin"],
        note=(
            "Stub. Iterate a curated list of mirror repos and pull each "
            "/.well-known/ai-plugin.json."
        ),
    ),
    implemented=False,
)
