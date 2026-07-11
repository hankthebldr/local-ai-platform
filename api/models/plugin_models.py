"""
Plugin Models — schemas for the plugin management plane and creation forge.

LB5-U2 gave plugins a file-management plane (PluginFileWrite rode inline in
the router; it lives here now). LB5-U3 adds the creation forge: an operator
description is drafted into a PluginSpecDraft by a LOCAL model (deterministic
fallback when the model is unavailable), materialized into a PluginFileSet by
a constrained template, reviewed file-by-file in the wizard, and only then
installed. Tool code runs in-process, so tools are an explicit opt-in and
every generated/edited tools/*.py passes a denylisted-imports lint at install.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class PluginSkillDraft(BaseModel):
    """One skill in a drafted plugin spec (maps to skills/<id>.md)."""

    id: str
    name: str = ""
    description: str = ""
    triggers: List[str] = Field(default_factory=list)
    inject: str = "system"  # system | user | none
    body: str = ""


class PluginToolDraft(BaseModel):
    """One tool in a drafted plugin spec (maps to tools/<id>.py).

    ``parameters`` follows the plugin.yaml tool-parameter convention:
    {name: {type, description, required, default}}. The forge never emits
    model-written tool code — only a constrained stub template."""

    id: str
    description: str = ""
    parameters: Dict[str, Any] = Field(default_factory=dict)


class PluginSpecDraft(BaseModel):
    """Editable draft spec: NL description → this → file set → install.

    ``source`` is honest provenance for the wizard chip: 'model' when the
    local model produced a usable draft, 'fallback' when the deterministic
    one-skill/zero-tools path filled in (model down, malformed JSON, …)."""

    id: str
    name: str = ""
    description: str = ""
    version: str = "0.1.0"
    skills: List[PluginSkillDraft] = Field(default_factory=list)
    tools: List[PluginToolDraft] = Field(default_factory=list)
    model: Optional[str] = None
    source: str = "model"  # model | fallback


class PluginFile(BaseModel):
    """One generated (or wizard-edited) file, path relative to the plugin dir."""

    path: str
    content: str


class PluginFileSet(BaseModel):
    """The reviewable output of /scaffold/generate — nothing is written yet."""

    plugin_id: str
    files: List[PluginFile] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    tools_included: bool = False


class PluginFileWrite(BaseModel):
    """One file save from the Files tab editor (LB5-U2). ``version``
    (optional) is honored verbatim as the new plugin.yaml version; when
    absent the first save since the last reload patch-bumps it (dirty
    flag)."""

    content: str
    version: Optional[str] = None
