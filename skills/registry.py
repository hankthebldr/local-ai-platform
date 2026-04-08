#!/usr/bin/env python3
"""
OpenClaw-Compatible Skill Registry System
Manages skill discovery, installation, and execution
Similar to the model registry but for agent skills
"""

import os
import json
import yaml
import requests
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from enum import Enum


class SkillCategory(str, Enum):
    """Skill categories based on OpenClaw taxonomy"""
    PRODUCTIVITY = "productivity"
    DEVELOPMENT = "development"
    SEARCH = "search"
    COMMUNICATION = "communication"
    IOT = "iot"
    DATA = "data"
    SECURITY = "security"
    CUSTOM = "custom"


class ToolPermission(str, Enum):
    """Tool permission levels"""
    ALWAYS_ALLOW = "always_allow"
    REQUIRE_APPROVAL = "require_approval"
    ALWAYS_DENY = "always_deny"


@dataclass
class SkillMetadata:
    """Metadata for a skill (from SKILL.md YAML frontmatter)"""
    id: str
    name: str
    version: str
    description: str
    author: str
    category: SkillCategory
    tags: List[str]
    tools_required: List[str]
    dependencies: List[str] = None
    homepage: str = None
    repository: str = None
    license: str = "MIT"
    rating: float = 0.0
    downloads: int = 0

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class Tool:
    """A tool that provides a capability to the agent"""
    name: str
    description: str
    permission: ToolPermission
    enabled: bool = True
    parameters: Dict[str, Any] = None

    def to_dict(self) -> Dict:
        return asdict(self)


# Built-in tools (core capabilities)
BUILTIN_TOOLS = {
    "read": Tool(
        name="read",
        description="Read files from the filesystem",
        permission=ToolPermission.ALWAYS_ALLOW
    ),
    "write": Tool(
        name="write",
        description="Write files to the filesystem",
        permission=ToolPermission.REQUIRE_APPROVAL
    ),
    "exec": Tool(
        name="exec",
        description="Execute shell commands",
        permission=ToolPermission.REQUIRE_APPROVAL
    ),
    "web_search": Tool(
        name="web_search",
        description="Search the web using search engines",
        permission=ToolPermission.ALWAYS_ALLOW
    ),
    "web_fetch": Tool(
        name="web_fetch",
        description="Fetch content from URLs",
        permission=ToolPermission.ALWAYS_ALLOW
    ),
    "llm_task": Tool(
        name="llm_task",
        description="Delegate subtasks to LLM",
        permission=ToolPermission.ALWAYS_ALLOW
    ),
    "python": Tool(
        name="python",
        description="Execute Python code",
        permission=ToolPermission.REQUIRE_APPROVAL
    ),
    "sql": Tool(
        name="sql",
        description="Execute SQL queries",
        permission=ToolPermission.REQUIRE_APPROVAL
    ),
    "api_call": Tool(
        name="api_call",
        description="Make HTTP API calls",
        permission=ToolPermission.REQUIRE_APPROVAL
    )
}


# Skill Registry (similar to MODEL_REGISTRY)
# This will be populated from ClawHub and custom sources
SKILL_REGISTRY = {
    # Productivity & Automation (35.5%)
    "gmail": {
        "id": "gmail",
        "name": "Gmail Integration",
        "version": "1.2.0",
        "description": "Send, read, and manage Gmail messages",
        "author": "OpenClaw Community",
        "category": SkillCategory.PRODUCTIVITY,
        "tags": ["email", "google", "productivity"],
        "tools_required": ["api_call", "llm_task"],
        "dependencies": ["google-auth", "google-api-python-client"],
        "repository": "https://clawhub.ai/skills/gmail",
        "rating": 4.8,
        "downloads": 45230,
        "local_path": None,
        "installed": False
    },

    "slack": {
        "id": "slack",
        "name": "Slack Integration",
        "version": "2.0.1",
        "description": "Send messages, manage channels, and interact with Slack",
        "author": "OpenClaw Community",
        "category": SkillCategory.COMMUNICATION,
        "tags": ["messaging", "collaboration", "slack"],
        "tools_required": ["api_call", "web_fetch"],
        "dependencies": ["slack-sdk"],
        "repository": "https://clawhub.ai/skills/slack",
        "rating": 4.9,
        "downloads": 52100,
        "local_path": None,
        "installed": False
    },

    "github": {
        "id": "github",
        "name": "GitHub Automation",
        "version": "1.5.0",
        "description": "Manage repos, issues, PRs, and GitHub actions",
        "author": "OpenClaw Community",
        "category": SkillCategory.DEVELOPMENT,
        "tags": ["git", "github", "devops"],
        "tools_required": ["api_call", "exec", "read", "write"],
        "dependencies": ["PyGithub"],
        "repository": "https://clawhub.ai/skills/github",
        "rating": 4.7,
        "downloads": 38900,
        "local_path": None,
        "installed": False
    },

    "web-scraper": {
        "id": "web-scraper",
        "name": "Advanced Web Scraper",
        "version": "1.8.2",
        "description": "Extract structured data from websites using CSS selectors and XPath",
        "author": "OpenClaw Community",
        "category": SkillCategory.SEARCH,
        "tags": ["scraping", "data-extraction", "web"],
        "tools_required": ["web_fetch", "python"],
        "dependencies": ["beautifulsoup4", "lxml", "selenium"],
        "repository": "https://clawhub.ai/skills/web-scraper",
        "rating": 4.6,
        "downloads": 29400,
        "local_path": None,
        "installed": False
    },

    "postgres": {
        "id": "postgres",
        "name": "PostgreSQL Database Manager",
        "version": "1.3.0",
        "description": "Query, manage, and analyze PostgreSQL databases",
        "author": "OpenClaw Community",
        "category": SkillCategory.DATA,
        "tags": ["database", "sql", "postgresql"],
        "tools_required": ["sql", "python"],
        "dependencies": ["psycopg2-binary", "sqlalchemy"],
        "repository": "https://clawhub.ai/skills/postgres",
        "rating": 4.5,
        "downloads": 18200,
        "local_path": None,
        "installed": False
    },

    "document-analyzer": {
        "id": "document-analyzer",
        "name": "Document Analyzer",
        "version": "2.1.0",
        "description": "Extract text, tables, and metadata from PDF/DOCX/TXT files",
        "author": "OpenClaw Community",
        "category": SkillCategory.PRODUCTIVITY,
        "tags": ["pdf", "documents", "extraction"],
        "tools_required": ["read", "python", "llm_task"],
        "dependencies": ["pypdf2", "python-docx", "pdfplumber"],
        "repository": "https://clawhub.ai/skills/document-analyzer",
        "rating": 4.7,
        "downloads": 31500,
        "local_path": None,
        "installed": False
    },

    "code-reviewer": {
        "id": "code-reviewer",
        "name": "Code Reviewer",
        "version": "1.4.0",
        "description": "Automated code review with best practices and security checks",
        "author": "OpenClaw Community",
        "category": SkillCategory.DEVELOPMENT,
        "tags": ["code-review", "security", "quality"],
        "tools_required": ["read", "exec", "llm_task"],
        "dependencies": ["pylint", "bandit", "radon"],
        "repository": "https://clawhub.ai/skills/code-reviewer",
        "rating": 4.8,
        "downloads": 22700,
        "local_path": None,
        "installed": False
    },

    "jira": {
        "id": "jira",
        "name": "Jira Integration",
        "version": "1.6.0",
        "description": "Create, update, and manage Jira issues and projects",
        "author": "OpenClaw Community",
        "category": SkillCategory.PRODUCTIVITY,
        "tags": ["project-management", "jira", "atlassian"],
        "tools_required": ["api_call"],
        "dependencies": ["jira"],
        "repository": "https://clawhub.ai/skills/jira",
        "rating": 4.4,
        "downloads": 15800,
        "local_path": None,
        "installed": False
    },

    "docker": {
        "id": "docker",
        "name": "Docker Manager",
        "version": "1.7.0",
        "description": "Build, run, and manage Docker containers and images",
        "author": "OpenClaw Community",
        "category": SkillCategory.DEVELOPMENT,
        "tags": ["docker", "containers", "devops"],
        "tools_required": ["exec", "read"],
        "dependencies": ["docker"],
        "repository": "https://clawhub.ai/skills/docker",
        "rating": 4.6,
        "downloads": 19500,
        "local_path": None,
        "installed": False
    },

    "calendar": {
        "id": "calendar",
        "name": "Google Calendar",
        "version": "1.3.0",
        "description": "Schedule events, check availability, and manage Google Calendar",
        "author": "OpenClaw Community",
        "category": SkillCategory.PRODUCTIVITY,
        "tags": ["calendar", "scheduling", "google"],
        "tools_required": ["api_call"],
        "dependencies": ["google-api-python-client"],
        "repository": "https://clawhub.ai/skills/calendar",
        "rating": 4.5,
        "downloads": 16200,
        "local_path": None,
        "installed": False
    }
}


class SkillRegistry:
    """
    Manages skill discovery, installation, and execution
    Similar to model download.py but for OpenClaw skills
    """

    def __init__(self, skills_dir: str = "./data/skills"):
        self.skills_dir = Path(skills_dir)
        self.skills_dir.mkdir(parents=True, exist_ok=True)

        self.registry = SKILL_REGISTRY.copy()
        self.tools = BUILTIN_TOOLS.copy()

        # Load installed skills from disk
        self._load_installed_skills()

    def list_skills(self, category: Optional[SkillCategory] = None,
                   installed_only: bool = False) -> List[Dict]:
        """List all available skills"""
        skills = []

        for skill_id, skill_data in self.registry.items():
            if category and skill_data["category"] != category:
                continue
            if installed_only and not skill_data.get("installed", False):
                continue

            skills.append(skill_data)

        # Sort by downloads (popularity)
        return sorted(skills, key=lambda x: x.get("downloads", 0), reverse=True)

    def get_skill(self, skill_id: str) -> Optional[Dict]:
        """Get details about a specific skill"""
        return self.registry.get(skill_id)

    def search_skills(self, query: str) -> List[Dict]:
        """Search skills by name, description, or tags"""
        query_lower = query.lower()
        results = []

        for skill_id, skill_data in self.registry.items():
            if (query_lower in skill_data["name"].lower() or
                query_lower in skill_data["description"].lower() or
                any(query_lower in tag.lower() for tag in skill_data["tags"])):
                results.append(skill_data)

        return sorted(results, key=lambda x: x.get("rating", 0), reverse=True)

    def install_skill(self, skill_id: str, source: str = "clawhub") -> bool:
        """
        Install a skill from a source (ClawHub, GitHub, local)

        Args:
            skill_id: ID of the skill to install
            source: Source to install from (clawhub, github, local)

        Returns:
            True if installation successful
        """
        skill_data = self.registry.get(skill_id)
        if not skill_data:
            raise ValueError(f"Skill '{skill_id}' not found in registry")

        skill_path = self.skills_dir / skill_id
        skill_path.mkdir(exist_ok=True)

        if source == "clawhub":
            # Download from ClawHub
            repo_url = skill_data["repository"]
            self._download_from_clawhub(skill_id, repo_url, skill_path)

        elif source == "github":
            # Clone from GitHub
            repo_url = skill_data["repository"]
            self._clone_from_github(repo_url, skill_path)

        elif source == "local":
            # Copy from local path
            print(f"Skill directory should be at: {skill_path}")

        # Install Python dependencies
        if skill_data.get("dependencies"):
            self._install_dependencies(skill_data["dependencies"])

        # Mark as installed
        self.registry[skill_id]["installed"] = True
        self.registry[skill_id]["local_path"] = str(skill_path)

        print(f"✓ Skill '{skill_data['name']}' installed successfully")
        return True

    def uninstall_skill(self, skill_id: str) -> bool:
        """Uninstall a skill"""
        skill_data = self.registry.get(skill_id)
        if not skill_data or not skill_data.get("installed"):
            print(f"Skill '{skill_id}' is not installed")
            return False

        import shutil
        skill_path = Path(skill_data["local_path"])
        if skill_path.exists():
            shutil.rmtree(skill_path)

        self.registry[skill_id]["installed"] = False
        self.registry[skill_id]["local_path"] = None

        print(f"✓ Skill '{skill_data['name']}' uninstalled")
        return True

    def load_skill_instructions(self, skill_id: str) -> Optional[str]:
        """Load SKILL.md instructions for a skill"""
        skill_data = self.registry.get(skill_id)
        if not skill_data or not skill_data.get("installed"):
            return None

        skill_path = Path(skill_data["local_path"])
        skill_md = skill_path / "SKILL.md"

        if not skill_md.exists():
            return None

        with open(skill_md, 'r') as f:
            return f.read()

    def parse_skill_md(self, skill_md_content: str) -> Dict[str, Any]:
        """
        Parse SKILL.md file (YAML frontmatter + instructions)

        Format:
        ---
        name: Skill Name
        version: 1.0.0
        tools: [web_fetch, python]
        ---

        # Instructions
        Use this skill to...
        """
        parts = skill_md_content.split("---")

        if len(parts) < 3:
            return {"metadata": {}, "instructions": skill_md_content}

        # Parse YAML frontmatter
        metadata = yaml.safe_load(parts[1])

        # Get instructions (everything after second ---)
        instructions = "---".join(parts[2:]).strip()

        return {
            "metadata": metadata,
            "instructions": instructions
        }

    def get_tools_for_skill(self, skill_id: str) -> List[Tool]:
        """Get list of tools required by a skill"""
        skill_data = self.registry.get(skill_id)
        if not skill_data:
            return []

        tools = []
        for tool_name in skill_data.get("tools_required", []):
            if tool_name in self.tools:
                tools.append(self.tools[tool_name])

        return tools

    def check_tool_permissions(self, tool_name: str) -> ToolPermission:
        """Check permission level for a tool"""
        tool = self.tools.get(tool_name)
        return tool.permission if tool else ToolPermission.ALWAYS_DENY

    def _load_installed_skills(self):
        """Load metadata for already installed skills"""
        if not self.skills_dir.exists():
            return

        for skill_dir in self.skills_dir.iterdir():
            if not skill_dir.is_dir():
                continue

            skill_md = skill_dir / "SKILL.md"
            if skill_md.exists():
                skill_id = skill_dir.name
                if skill_id in self.registry:
                    self.registry[skill_id]["installed"] = True
                    self.registry[skill_id]["local_path"] = str(skill_dir)

    def _download_from_clawhub(self, skill_id: str, repo_url: str, dest_path: Path):
        """Download skill from ClawHub"""
        # In production, this would use the ClawHub API
        print(f"Downloading {skill_id} from ClawHub...")
        # For now, create a placeholder SKILL.md
        skill_data = self.registry[skill_id]
        self._create_skill_template(skill_data, dest_path)

    def _clone_from_github(self, repo_url: str, dest_path: Path):
        """Clone skill from GitHub"""
        import subprocess
        subprocess.run(["git", "clone", repo_url, str(dest_path)], check=True)

    def _install_dependencies(self, dependencies: List[str]):
        """Install Python dependencies for a skill"""
        import subprocess
        print(f"Installing dependencies: {', '.join(dependencies)}")
        subprocess.run(
            ["pip", "install"] + dependencies,
            check=True,
            capture_output=True
        )

    def _create_skill_template(self, skill_data: Dict, dest_path: Path):
        """Create a template SKILL.md file"""
        skill_md = f"""---
name: {skill_data['name']}
version: {skill_data['version']}
description: {skill_data['description']}
author: {skill_data['author']}
tools: {json.dumps(skill_data['tools_required'])}
tags: {json.dumps(skill_data['tags'])}
---

# {skill_data['name']}

{skill_data['description']}

## Usage

This skill requires the following tools:
{chr(10).join(f"- {tool}" for tool in skill_data['tools_required'])}

## Instructions

Use this skill to accomplish tasks related to {skill_data['category']}.

## Examples

```
Example usage instructions here
```
"""

        skill_md_path = dest_path / "SKILL.md"
        with open(skill_md_path, 'w') as f:
            f.write(skill_md)


# CLI Interface
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="OpenClaw Skill Registry Manager")
    parser.add_argument("--list", action="store_true", help="List all skills")
    parser.add_argument("--category", type=str, help="Filter by category")
    parser.add_argument("--installed", action="store_true", help="Show only installed skills")
    parser.add_argument("--search", type=str, help="Search skills")
    parser.add_argument("--info", type=str, help="Show skill details")
    parser.add_argument("--install", type=str, help="Install a skill")
    parser.add_argument("--uninstall", type=str, help="Uninstall a skill")
    parser.add_argument("--source", type=str, default="clawhub",
                       choices=["clawhub", "github", "local"],
                       help="Source to install from")

    args = parser.parse_args()

    registry = SkillRegistry()

    if args.list or (not any(vars(args).values())):
        # List skills
        category = SkillCategory(args.category) if args.category else None
        skills = registry.list_skills(category=category, installed_only=args.installed)

        print("\n" + "=" * 80)
        print("OPENCLAW SKILL REGISTRY")
        print("=" * 80)

        for skill in skills:
            status = "✓ INSTALLED" if skill.get("installed") else "  AVAILABLE"
            print(f"\n{status} | {skill['id']}")
            print(f"  Name: {skill['name']} v{skill['version']}")
            print(f"  Description: {skill['description']}")
            print(f"  Category: {skill['category']}")
            print(f"  Rating: {'★' * int(skill['rating'])}  ({skill['rating']}/5.0)")
            print(f"  Downloads: {skill['downloads']:,}")
            print(f"  Tools: {', '.join(skill['tools_required'])}")

        print("\n" + "=" * 80)
        print(f"Total: {len(skills)} skills")
        print("=" * 80 + "\n")

    elif args.search:
        # Search skills
        results = registry.search_skills(args.search)
        print(f"\nSearch results for '{args.search}':")
        print("=" * 80)
        for skill in results:
            print(f"\n{skill['id']} - {skill['name']}")
            print(f"  {skill['description']}")
            print(f"  Tags: {', '.join(skill['tags'])}")

    elif args.info:
        # Show skill info
        skill = registry.get_skill(args.info)
        if skill:
            print("\n" + "=" * 80)
            print(f"SKILL: {skill['name']}")
            print("=" * 80)
            print(f"ID: {skill['id']}")
            print(f"Version: {skill['version']}")
            print(f"Author: {skill['author']}")
            print(f"Category: {skill['category']}")
            print(f"Description: {skill['description']}")
            print(f"Tags: {', '.join(skill['tags'])}")
            print(f"Tools Required: {', '.join(skill['tools_required'])}")
            print(f"Dependencies: {', '.join(skill.get('dependencies', []))}")
            print(f"Repository: {skill.get('repository', 'N/A')}")
            print(f"Rating: {skill['rating']}/5.0")
            print(f"Downloads: {skill['downloads']:,}")
            print(f"Installed: {'Yes' if skill.get('installed') else 'No'}")
            print("=" * 80 + "\n")
        else:
            print(f"Skill '{args.info}' not found")

    elif args.install:
        # Install skill
        try:
            registry.install_skill(args.install, source=args.source)
        except Exception as e:
            print(f"Error installing skill: {e}")

    elif args.uninstall:
        # Uninstall skill
        registry.uninstall_skill(args.uninstall)
