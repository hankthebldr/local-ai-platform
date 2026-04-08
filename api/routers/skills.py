#!/usr/bin/env python3
"""
FastAPI Router for OpenClaw Skills Management
Provides REST API for skill discovery, installation, and execution
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from enum import Enum
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent.parent))

from skills.registry import SkillRegistry, SkillCategory, ToolPermission


router = APIRouter(prefix="/v1/skills", tags=["skills"])

# Initialize skill registry
skill_registry = SkillRegistry()


# Pydantic Models
class SkillResponse(BaseModel):
    id: str
    name: str
    version: str
    description: str
    author: str
    category: str
    tags: List[str]
    tools_required: List[str]
    dependencies: Optional[List[str]] = []
    repository: Optional[str] = None
    rating: float
    downloads: int
    installed: bool
    local_path: Optional[str] = None


class SkillListResponse(BaseModel):
    skills: List[SkillResponse]
    total: int
    category: Optional[str] = None


class SkillInstallRequest(BaseModel):
    skill_id: str
    source: str = Field(default="clawhub", pattern="^(clawhub|github|local)$")


class SkillSearchRequest(BaseModel):
    query: str
    limit: int = Field(default=10, ge=1, le=100)


class ToolResponse(BaseModel):
    name: str
    description: str
    permission: str
    enabled: bool


# Endpoints

@router.get("/list", response_model=SkillListResponse)
async def list_skills(
    category: Optional[str] = Query(None, description="Filter by category"),
    installed_only: bool = Query(False, description="Show only installed skills")
):
    """
    List all available skills from the registry

    Categories:
    - productivity: Email, calendar, automation
    - development: GitHub, Docker, code tools
    - search: Web scraping, research
    - communication: Slack, messaging
    - data: Database, analytics
    - iot: Smart home, IoT devices
    - security: Security scanning, auditing
    """
    try:
        cat = SkillCategory(category) if category else None
        skills = skill_registry.list_skills(category=cat, installed_only=installed_only)

        skill_responses = [
            SkillResponse(**skill) for skill in skills
        ]

        return SkillListResponse(
            skills=skill_responses,
            total=len(skill_responses),
            category=category
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid category: {category}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/search")
async def search_skills(query: str = Query(..., min_length=1)):
    """Search skills by name, description, or tags"""
    try:
        results = skill_registry.search_skills(query)

        skill_responses = [
            SkillResponse(**skill) for skill in results
        ]

        return {
            "query": query,
            "results": skill_responses,
            "total": len(skill_responses)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/categories")
async def list_categories():
    """List all available skill categories"""
    return {
        "categories": [
            {
                "id": cat.value,
                "name": cat.value.title(),
                "description": _get_category_description(cat)
            }
            for cat in SkillCategory
        ]
    }


@router.get("/{skill_id}", response_model=SkillResponse)
async def get_skill(skill_id: str):
    """Get detailed information about a specific skill"""
    skill = skill_registry.get_skill(skill_id)

    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_id}' not found")

    return SkillResponse(**skill)


@router.post("/install")
async def install_skill(request: SkillInstallRequest):
    """
    Install a skill from a source

    Sources:
    - clawhub: Official ClawHub registry
    - github: Clone from GitHub repository
    - local: Use local skill directory
    """
    try:
        success = skill_registry.install_skill(request.skill_id, source=request.source)

        if success:
            skill = skill_registry.get_skill(request.skill_id)
            return {
                "status": "success",
                "message": f"Skill '{skill['name']}' installed successfully",
                "skill": SkillResponse(**skill)
            }
        else:
            raise HTTPException(status_code=500, detail="Installation failed")

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Installation error: {str(e)}")


@router.delete("/{skill_id}")
async def uninstall_skill(skill_id: str):
    """Uninstall a skill"""
    try:
        success = skill_registry.uninstall_skill(skill_id)

        if success:
            return {
                "status": "success",
                "message": f"Skill '{skill_id}' uninstalled successfully"
            }
        else:
            raise HTTPException(status_code=404, detail="Skill not installed or not found")

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{skill_id}/instructions")
async def get_skill_instructions(skill_id: str):
    """Get SKILL.md instructions for a skill"""
    instructions = skill_registry.load_skill_instructions(skill_id)

    if not instructions:
        raise HTTPException(
            status_code=404,
            detail=f"Instructions not found for skill '{skill_id}' (not installed?)"
        )

    parsed = skill_registry.parse_skill_md(instructions)

    return {
        "skill_id": skill_id,
        "metadata": parsed["metadata"],
        "instructions": parsed["instructions"]
    }


@router.get("/{skill_id}/tools", response_model=List[ToolResponse])
async def get_skill_tools(skill_id: str):
    """Get list of tools required by a skill"""
    tools = skill_registry.get_tools_for_skill(skill_id)

    if not tools:
        raise HTTPException(
            status_code=404,
            detail=f"Skill '{skill_id}' not found or has no tools"
        )

    return [
        ToolResponse(
            name=tool.name,
            description=tool.description,
            permission=tool.permission.value,
            enabled=tool.enabled
        )
        for tool in tools
    ]


@router.get("/tools/list", response_model=List[ToolResponse])
async def list_tools():
    """List all available built-in tools"""
    tools = skill_registry.tools.values()

    return [
        ToolResponse(
            name=tool.name,
            description=tool.description,
            permission=tool.permission.value,
            enabled=tool.enabled
        )
        for tool in tools
    ]


@router.get("/stats/overview")
async def get_stats():
    """Get overall statistics about the skill registry"""
    all_skills = skill_registry.list_skills()
    installed_skills = skill_registry.list_skills(installed_only=True)

    # Category breakdown
    category_counts = {}
    for skill in all_skills:
        cat = skill["category"]
        category_counts[cat] = category_counts.get(cat, 0) + 1

    return {
        "total_skills": len(all_skills),
        "installed_skills": len(installed_skills),
        "available_skills": len(all_skills) - len(installed_skills),
        "categories": len(SkillCategory),
        "tools": len(skill_registry.tools),
        "category_breakdown": category_counts,
        "top_skills": [
            {
                "id": skill["id"],
                "name": skill["name"],
                "downloads": skill["downloads"],
                "rating": skill["rating"]
            }
            for skill in sorted(all_skills, key=lambda x: x["downloads"], reverse=True)[:5]
        ]
    }


# Helper functions

def _get_category_description(category: SkillCategory) -> str:
    """Get description for a category"""
    descriptions = {
        SkillCategory.PRODUCTIVITY: "Email, calendar, automation, and productivity tools",
        SkillCategory.DEVELOPMENT: "GitHub, Docker, CI/CD, and development tools",
        SkillCategory.SEARCH: "Web scraping, research, and data extraction",
        SkillCategory.COMMUNICATION: "Slack, messaging, and collaboration tools",
        SkillCategory.DATA: "Database management, analytics, and data processing",
        SkillCategory.IOT: "Smart home, IoT devices, and hardware control",
        SkillCategory.SECURITY: "Security scanning, auditing, and compliance",
        SkillCategory.CUSTOM: "Custom and user-created skills"
    }
    return descriptions.get(category, "")
