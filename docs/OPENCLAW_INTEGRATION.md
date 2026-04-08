# OpenClaw Integration Guide

## Overview

The Local AI Platform now includes full **OpenClaw-compatible skill management** and agent execution capabilities. This integration allows you to browse, install, and execute over 13,000+ community-built AI agent skills.

## What is OpenClaw?

**OpenClaw** is an open-source AI agent framework where:
- **Tools** = Capabilities (what the agent CAN do: web_search, file I/O, exec, API calls)
- **Skills** = Knowledge (HOW to use tools to accomplish tasks)
- **ClawHub** = Public registry with 13,729+ community skills (as of Feb 2026)

### Architecture

```
┌─────────────────────────────────────────────────┐
│              User/Application                    │
└──────────────────┬──────────────────────────────┘
                   │
┌──────────────────▼──────────────────────────────┐
│          OpenClaw Agent (Claude-powered)         │
│  ┌────────────┐  ┌─────────────┐  ┌──────────┐ │
│  │  Thinking  │  │ Tool Calling│  │ Execution│ │
│  └────────────┘  └─────────────┘  └──────────┘ │
└──────────────────┬──────────────────────────────┘
                   │
┌──────────────────▼──────────────────────────────┐
│                Skills Layer                      │
│  ┌──────┐ ┌───────┐ ┌───────┐ ┌──────────────┐ │
│  │Gmail │ │ Slack │ │GitHub │ │ Web Scraper  │ │
│  └──────┘ └───────┘ └───────┘ └──────────────┘ │
└──────────────────┬──────────────────────────────┘
                   │
┌──────────────────▼──────────────────────────────┐
│                Tools Layer                       │
│  ┌──────┐ ┌──────┐ ┌────────┐ ┌─────────────┐  │
│  │ Read │ │Write │ │  Exec  │ │  API Call   │  │
│  └──────┘ └──────┘ └────────┘ └─────────────┘  │
└──────────────────────────────────────────────────┘
```

## Quick Start

### 1. Start the API Server

```bash
source venv/bin/activate
python api/main.py
```

The API will be available at http://localhost:8000

### 2. Browse Skills via Web UI

Open the skills browser:

```bash
# Open in browser
http://localhost:8000/../webui/skills.html
```

Or manually open: `/home/user/local-ai-platform/webui/skills.html`

### 3. Using the CLI

```bash
# List all available skills
python skills/registry.py --list

# Search for skills
python skills/registry.py --search "github"

# Get skill details
python skills/registry.py --info gmail

# Install a skill
python skills/registry.py --install slack

# Uninstall a skill
python skills/registry.py --uninstall slack

# List installed skills only
python skills/registry.py --list --installed
```

## API Endpoints

### Skills Management

**List all skills:**
```bash
curl http://localhost:8000/v1/skills/list
```

**Filter by category:**
```bash
curl "http://localhost:8000/v1/skills/list?category=productivity"
```

**Search skills:**
```bash
curl "http://localhost:8000/v1/skills/search?query=github"
```

**Get skill details:**
```bash
curl http://localhost:8000/v1/skills/gmail
```

**Install skill:**
```bash
curl -X POST http://localhost:8000/v1/skills/install \
  -H "Content-Type: application/json" \
  -d '{"skill_id": "gmail", "source": "clawhub"}'
```

**Uninstall skill:**
```bash
curl -X DELETE http://localhost:8000/v1/skills/gmail
```

**Get skill instructions:**
```bash
curl http://localhost:8000/v1/skills/gmail/instructions
```

**Get skill tools:**
```bash
curl http://localhost:8000/v1/skills/gmail/tools
```

**List all tools:**
```bash
curl http://localhost:8000/v1/skills/tools/list
```

**Get stats:**
```bash
curl http://localhost:8000/v1/skills/stats/overview
```

## Skill Categories

1. **Productivity** (35.5% of skills)
   - Email (Gmail, Outlook)
   - Calendar (Google Calendar)
   - Task management (Jira, Trello)
   - Note-taking (Notion, Obsidian)

2. **Development** (28.2% of skills)
   - Version control (GitHub, GitLab)
   - CI/CD (Jenkins, GitHub Actions)
   - Container management (Docker, Kubernetes)
   - Code review and analysis

3. **Search & Research** (18.4% of skills)
   - Web scraping
   - Data extraction
   - Research automation
   - Document analysis

4. **Communication** (12.6% of skills)
   - Slack
   - Discord
   - Microsoft Teams
   - Email automation

5. **Data** (5.3% of skills)
   - Database management (PostgreSQL, MySQL)
   - Analytics (Pandas, SQL)
   - Data pipelines

6. **IoT & Smart Home**
   - Home automation
   - Device control
   - Sensor integration

7. **Security**
   - Vulnerability scanning
   - Security auditing
   - Compliance checking

## Built-in Tools

The platform includes these built-in tools:

| Tool | Description | Permission |
|------|-------------|------------|
| `read` | Read files from filesystem | Always Allow |
| `write` | Write files to filesystem | Require Approval |
| `exec` | Execute shell commands | Require Approval |
| `web_search` | Search the web | Always Allow |
| `web_fetch` | Fetch content from URLs | Always Allow |
| `llm_task` | Delegate subtasks to LLM | Always Allow |
| `python` | Execute Python code | Require Approval |
| `sql` | Execute SQL queries | Require Approval |
| `api_call` | Make HTTP API calls | Require Approval |

### Tool Permissions

- **Always Allow**: Tool executes immediately
- **Require Approval**: User must approve before execution
- **Always Deny**: Tool is disabled

## Using the OpenClaw Agent

### Python API

```python
from skills.openclaw_agent import OpenClawAgent, AgentTask

# Create agent
agent = OpenClawAgent(
    model="claude-sonnet-4",
    api_key="your-api-key"
)

# Create a task
task = AgentTask(
    id="task-001",
    description="Search GitHub for popular Python AI libraries and create a summary",
    context={
        "language": "Python",
        "topic": "AI/ML"
    },
    skills=["github", "web-scraper"]
)

# Execute task
result = await agent.execute_task(task)

print(result["output"])
```

### Task Parameters

```python
AgentTask(
    id="unique-task-id",
    description="What you want the agent to do",
    context={
        "key": "value",  # Additional context
    },
    max_iterations=10,  # Max reasoning loops
    skills=["skill1", "skill2"]  # Specific skills to use
)
```

### Result Format

```python
{
    "status": "success",  # or "error"
    "output": "Agent's final response",
    "iterations": 5,  # Number of reasoning loops
    "tool_calls": 3,  # Number of tools used
    "error": None  # Error message if failed
}
```

## Creating Custom Skills

### 1. Create Skill Directory

```bash
mkdir -p data/skills/my-custom-skill
```

### 2. Create SKILL.md

```markdown
---
name: My Custom Skill
version: 1.0.0
description: Does something awesome
author: Your Name
tools: ["api_call", "read", "write"]
tags: ["custom", "automation"]
---

# My Custom Skill

This skill does something awesome.

## Usage

To use this skill:

1. Call the API endpoint
2. Parse the response
3. Save results to a file

## Example

```
Task: "Fetch data from API and save to CSV"

Steps:
1. Use api_call to fetch from https://api.example.com/data
2. Parse JSON response
3. Convert to CSV format
4. Use write to save to output.csv
```

## Tools Required

- `api_call`: Make HTTP requests
- `read`: Read existing data (if needed)
- `write`: Save results to file
```

### 3. Register in Registry

Edit `skills/registry.py` and add to `SKILL_REGISTRY`:

```python
"my-custom-skill": {
    "id": "my-custom-skill",
    "name": "My Custom Skill",
    "version": "1.0.0",
    "description": "Does something awesome",
    "author": "Your Name",
    "category": SkillCategory.CUSTOM,
    "tags": ["custom", "automation"],
    "tools_required": ["api_call", "read", "write"],
    "dependencies": [],
    "repository": None,
    "rating": 5.0,
    "downloads": 0,
    "local_path": "./data/skills/my-custom-skill",
    "installed": True
}
```

### 4. Install and Test

```bash
# The skill is now available
python skills/registry.py --info my-custom-skill

# Use it with the agent
python -c "
from skills.openclaw_agent import OpenClawAgent, AgentTask
import asyncio

async def test():
    agent = OpenClawAgent()
    task = AgentTask(
        id='test',
        description='Use my custom skill',
        skills=['my-custom-skill']
    )
    result = await agent.execute_task(task)
    print(result)

asyncio.run(test())
"
```

## Integration with Multi-Agent Workflows

OpenClaw skills can be used in the multi-agent workflow system (see `docs/MULTI_AGENT_WORKFLOW_ARCHITECTURE.md`):

```yaml
# workflow.yaml
steps:
  - id: "fetch-data"
    agent: "openclaw-agent"
    skills: ["web-scraper", "document-analyzer"]
    inputs:
      - type: "string"
        source: "workflow.input.url"
    outputs:
      - name: "extracted_data"
        type: "json"
```

## Security Considerations

1. **Tool Permissions**: Review tool permissions before enabling
2. **Code Execution**: `python` and `exec` tools can execute arbitrary code
3. **API Keys**: Store API keys securely (use environment variables)
4. **Skill Vetting**: Review skill code before installation
5. **Sandboxing**: Consider running in containers for production

### Production Security Checklist

- [ ] Enable authentication on API endpoints
- [ ] Set up rate limiting
- [ ] Review all tool permissions
- [ ] Audit installed skills
- [ ] Use secrets management (Vault, AWS Secrets Manager)
- [ ] Enable audit logging
- [ ] Run in containerized environment
- [ ] Implement approval workflows for sensitive tools

## Troubleshooting

### Skill Installation Fails

```bash
# Check Python dependencies
pip install -r setup/requirements.txt

# Verify skills directory
ls -la data/skills/

# Check permissions
chmod +x skills/registry.py
```

### Agent Execution Fails

```bash
# Verify Anthropic API key
echo $ANTHROPIC_API_KEY

# Check skill is installed
python skills/registry.py --list --installed

# Enable debug logging
export LOG_LEVEL=DEBUG
python skills/openclaw_agent.py
```

### Tool Permission Denied

Edit `skills/registry.py` and update tool permission:

```python
BUILTIN_TOOLS = {
    "exec": Tool(
        name="exec",
        description="Execute shell commands",
        permission=ToolPermission.ALWAYS_ALLOW  # Change permission
    ),
    # ...
}
```

## Performance Optimization

1. **Limit Max Iterations**: Set `max_iterations` to prevent infinite loops
2. **Cache Results**: Cache frequently used tool results
3. **Batch API Calls**: Use batch endpoints when available
4. **Prune Skills**: Uninstall unused skills to reduce context size
5. **Use Smaller Models**: Consider `claude-haiku-4-5` for simple tasks

## Monitoring

Monitor agent performance via Prometheus metrics:

```bash
# Agent task duration
openclaw_task_duration_seconds

# Tool call count
openclaw_tool_calls_total

# Tool execution time
openclaw_tool_duration_seconds

# Error rate
openclaw_errors_total
```

## Examples

### Example 1: GitHub Issue Automation

```python
task = AgentTask(
    id="github-001",
    description="Find all open issues labeled 'bug' in my repo and create a summary report",
    context={
        "repo": "username/repo-name",
        "label": "bug"
    },
    skills=["github"]
)
```

### Example 2: Email + Calendar Integration

```python
task = AgentTask(
    id="email-001",
    description="Check my Gmail for meeting requests today and add them to Google Calendar",
    context={
        "date": "2026-04-08"
    },
    skills=["gmail", "calendar"]
)
```

### Example 3: Web Research

```python
task = AgentTask(
    id="research-001",
    description="Research the latest developments in quantum computing and create a summary with sources",
    context={
        "topic": "quantum computing",
        "sources_count": 5
    },
    skills=["web-scraper", "document-analyzer"]
)
```

## Sources

- [OpenClaw Skills Framework Guide](https://skywork.ai/skypage/en/openclaw-skills-framework-guide/2038589913441320961)
- [Awesome OpenClaw Skills](https://github.com/VoltAgent/awesome-openclaw-skills)
- [OpenClaw Documentation](https://docs.openclaw.ai/tools/skills)
- [OpenClaw Tool Calling Explained](https://www.openclawplaybook.ai/guides/openclaw-tool-calling-explained/)
- [How OpenClaw Works](https://bibek-poudel.medium.com/how-openclaw-works-understanding-ai-agents-through-a-real-architecture-5d59cc7a4764)

## Next Steps

1. Explore the skill registry: `python skills/registry.py --list`
2. Install your first skill: `python skills/registry.py --install gmail`
3. Test the agent: See examples above
4. Create custom skills for your use case
5. Integrate with multi-agent workflows
6. Deploy to production with proper security

For more information, see:
- `docs/MULTI_AGENT_WORKFLOW_ARCHITECTURE.md` - Multi-agent workflow system
- `ENTERPRISE_DEPLOYMENT_GAPS.md` - Production deployment guide
- `api/routers/skills.py` - API implementation
- `skills/openclaw_agent.py` - Agent implementation
