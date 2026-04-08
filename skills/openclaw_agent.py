#!/usr/bin/env python3
"""
OpenClaw Agent Execution Engine
Executes agent tasks using installed skills and tools
Integrates with Anthropic Claude for LLM reasoning
"""

import os
import json
import asyncio
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum
import anthropic
from pathlib import Path

from skills.registry import SkillRegistry, ToolPermission


class AgentStatus(str, Enum):
    """Status of agent execution"""
    IDLE = "idle"
    THINKING = "thinking"
    USING_TOOL = "using_tool"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class ToolCall:
    """Represents a tool call made by the agent"""
    tool_name: str
    parameters: Dict[str, Any]
    requires_approval: bool = False
    approved: bool = False
    result: Optional[Any] = None
    error: Optional[str] = None


@dataclass
class AgentTask:
    """Represents a task for the agent to execute"""
    id: str
    description: str
    context: Dict[str, Any]
    max_iterations: int = 10
    skills: List[str] = None  # Specific skills to use


class OpenClawAgent:
    """
    OpenClaw-compatible agent that uses Claude + installed skills
    Similar to the actual OpenClaw agent architecture
    """

    def __init__(self,
                 model: str = "claude-sonnet-4",
                 api_key: Optional[str] = None,
                 skills_dir: str = "./data/skills"):
        """
        Initialize OpenClaw agent

        Args:
            model: Claude model to use
            api_key: Anthropic API key (or from env)
            skills_dir: Directory containing installed skills
        """
        self.model = model
        self.client = anthropic.Anthropic(
            api_key=api_key or os.environ.get("ANTHROPIC_API_KEY")
        )
        self.skill_registry = SkillRegistry(skills_dir=skills_dir)

        self.status = AgentStatus.IDLE
        self.conversation_history = []
        self.tool_calls = []

    async def execute_task(self, task: AgentTask) -> Dict[str, Any]:
        """
        Execute a task using available skills and tools

        Args:
            task: The task to execute

        Returns:
            Result dictionary with status, output, and metadata
        """
        self.status = AgentStatus.THINKING
        self.conversation_history = []
        self.tool_calls = []

        # Load skill instructions for requested skills
        skill_instructions = self._load_skill_instructions(task.skills)

        # Build system prompt with skills
        system_prompt = self._build_system_prompt(skill_instructions)

        # Build user message with task
        user_message = self._build_task_message(task)

        # Execute agentic loop
        iteration = 0
        while iteration < task.max_iterations:
            iteration += 1

            # Call Claude with tool use
            response = await self._call_claude(
                system_prompt=system_prompt,
                messages=self.conversation_history + [{"role": "user", "content": user_message}],
                tools=self._get_available_tools()
            )

            # Process response
            if response.stop_reason == "end_turn":
                # Agent finished
                final_output = self._extract_text_from_response(response)
                self.status = AgentStatus.COMPLETED
                return {
                    "status": "success",
                    "output": final_output,
                    "iterations": iteration,
                    "tool_calls": len(self.tool_calls)
                }

            elif response.stop_reason == "tool_use":
                # Agent wants to use a tool
                self.status = AgentStatus.USING_TOOL

                # Extract tool calls
                tool_calls = self._extract_tool_calls(response)

                # Execute tools
                tool_results = []
                for tool_call in tool_calls:
                    result = await self._execute_tool(tool_call)
                    tool_results.append(result)
                    self.tool_calls.append(tool_call)

                # Add to conversation history
                self.conversation_history.append({
                    "role": "assistant",
                    "content": response.content
                })
                self.conversation_history.append({
                    "role": "user",
                    "content": tool_results
                })

                # Continue loop
                user_message = ""  # No new user input, just tool results

            else:
                # Unexpected stop reason
                self.status = AgentStatus.FAILED
                return {
                    "status": "error",
                    "error": f"Unexpected stop reason: {response.stop_reason}",
                    "iterations": iteration
                }

        # Max iterations reached
        self.status = AgentStatus.FAILED
        return {
            "status": "error",
            "error": "Max iterations reached without completion",
            "iterations": iteration
        }

    def _load_skill_instructions(self, skill_ids: Optional[List[str]]) -> Dict[str, str]:
        """Load instructions for specified skills"""
        if not skill_ids:
            # Load all installed skills
            installed = self.skill_registry.list_skills(installed_only=True)
            skill_ids = [s["id"] for s in installed]

        instructions = {}
        for skill_id in skill_ids:
            skill_instructions = self.skill_registry.load_skill_instructions(skill_id)
            if skill_instructions:
                parsed = self.skill_registry.parse_skill_md(skill_instructions)
                instructions[skill_id] = parsed["instructions"]

        return instructions

    def _build_system_prompt(self, skill_instructions: Dict[str, str]) -> str:
        """Build system prompt with skill instructions"""
        prompt = """You are an AI agent with access to various tools and skills.

Your capabilities:
- You can use tools to accomplish tasks
- You have access to skills that teach you how to use tools effectively
- You should think step-by-step and use tools as needed
- Always explain what you're doing before using a tool

Available skills:
"""

        for skill_id, instructions in skill_instructions.items():
            prompt += f"\n## {skill_id}\n{instructions}\n"

        prompt += """

Important:
- Use tools only when necessary
- Explain your reasoning before each tool call
- If a tool fails, try an alternative approach
- When the task is complete, provide a clear summary
"""

        return prompt

    def _build_task_message(self, task: AgentTask) -> str:
        """Build user message for the task"""
        message = f"Task: {task.description}\n\n"

        if task.context:
            message += "Context:\n"
            for key, value in task.context.items():
                message += f"- {key}: {value}\n"

        return message

    def _get_available_tools(self) -> List[Dict]:
        """Get list of available tools in Claude tool format"""
        tools = []

        # Add built-in tools
        for tool_name, tool in self.skill_registry.tools.items():
            if not tool.enabled:
                continue

            tools.append({
                "name": tool_name,
                "description": tool.description,
                "input_schema": {
                    "type": "object",
                    "properties": self._get_tool_parameters(tool_name),
                    "required": []
                }
            })

        return tools

    def _get_tool_parameters(self, tool_name: str) -> Dict:
        """Get parameter schema for a tool"""
        # Define parameter schemas for each tool
        schemas = {
            "read": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file to read"
                }
            },
            "write": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file to write"
                },
                "content": {
                    "type": "string",
                    "description": "Content to write to the file"
                }
            },
            "exec": {
                "command": {
                    "type": "string",
                    "description": "Shell command to execute"
                }
            },
            "web_search": {
                "query": {
                    "type": "string",
                    "description": "Search query"
                },
                "num_results": {
                    "type": "integer",
                    "description": "Number of results to return"
                }
            },
            "web_fetch": {
                "url": {
                    "type": "string",
                    "description": "URL to fetch"
                }
            },
            "llm_task": {
                "task": {
                    "type": "string",
                    "description": "Subtask for the LLM to complete"
                }
            },
            "python": {
                "code": {
                    "type": "string",
                    "description": "Python code to execute"
                }
            },
            "sql": {
                "query": {
                    "type": "string",
                    "description": "SQL query to execute"
                },
                "connection_string": {
                    "type": "string",
                    "description": "Database connection string"
                }
            },
            "api_call": {
                "method": {
                    "type": "string",
                    "description": "HTTP method (GET, POST, etc.)"
                },
                "url": {
                    "type": "string",
                    "description": "API endpoint URL"
                },
                "headers": {
                    "type": "object",
                    "description": "HTTP headers"
                },
                "body": {
                    "type": "object",
                    "description": "Request body"
                }
            }
        }

        return schemas.get(tool_name, {})

    async def _call_claude(self,
                          system_prompt: str,
                          messages: List[Dict],
                          tools: List[Dict]) -> anthropic.types.Message:
        """Call Claude API with tool use"""
        response = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=system_prompt,
            messages=messages,
            tools=tools
        )

        return response

    def _extract_tool_calls(self, response: anthropic.types.Message) -> List[ToolCall]:
        """Extract tool calls from Claude response"""
        tool_calls = []

        for block in response.content:
            if block.type == "tool_use":
                tool_name = block.name
                parameters = block.input

                # Check if tool requires approval
                permission = self.skill_registry.check_tool_permissions(tool_name)
                requires_approval = (permission == ToolPermission.REQUIRE_APPROVAL)

                tool_calls.append(ToolCall(
                    tool_name=tool_name,
                    parameters=parameters,
                    requires_approval=requires_approval,
                    approved=not requires_approval  # Auto-approve if not required
                ))

        return tool_calls

    async def _execute_tool(self, tool_call: ToolCall) -> Dict:
        """Execute a tool call"""
        # Check if approval required
        if tool_call.requires_approval and not tool_call.approved:
            self.status = AgentStatus.WAITING_APPROVAL
            # In a real implementation, this would wait for user approval
            print(f"Tool '{tool_call.tool_name}' requires approval: {tool_call.parameters}")
            # For now, auto-approve for demo purposes
            tool_call.approved = True

        # Execute tool based on type
        try:
            if tool_call.tool_name == "read":
                result = await self._tool_read(tool_call.parameters)
            elif tool_call.tool_name == "write":
                result = await self._tool_write(tool_call.parameters)
            elif tool_call.tool_name == "exec":
                result = await self._tool_exec(tool_call.parameters)
            elif tool_call.tool_name == "web_search":
                result = await self._tool_web_search(tool_call.parameters)
            elif tool_call.tool_name == "web_fetch":
                result = await self._tool_web_fetch(tool_call.parameters)
            elif tool_call.tool_name == "llm_task":
                result = await self._tool_llm_task(tool_call.parameters)
            elif tool_call.tool_name == "python":
                result = await self._tool_python(tool_call.parameters)
            elif tool_call.tool_name == "api_call":
                result = await self._tool_api_call(tool_call.parameters)
            else:
                result = {"error": f"Unknown tool: {tool_call.tool_name}"}

            tool_call.result = result
            return {
                "type": "tool_result",
                "tool_use_id": tool_call.tool_name,
                "content": json.dumps(result)
            }

        except Exception as e:
            tool_call.error = str(e)
            return {
                "type": "tool_result",
                "tool_use_id": tool_call.tool_name,
                "content": json.dumps({"error": str(e)}),
                "is_error": True
            }

    def _extract_text_from_response(self, response: anthropic.types.Message) -> str:
        """Extract text content from Claude response"""
        text_parts = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
        return "\n".join(text_parts)

    # Tool implementations
    async def _tool_read(self, params: Dict) -> Dict:
        """Read file tool"""
        file_path = params.get("file_path")
        try:
            with open(file_path, 'r') as f:
                content = f.read()
            return {"success": True, "content": content}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _tool_write(self, params: Dict) -> Dict:
        """Write file tool"""
        file_path = params.get("file_path")
        content = params.get("content")
        try:
            Path(file_path).parent.mkdir(parents=True, exist_ok=True)
            with open(file_path, 'w') as f:
                f.write(content)
            return {"success": True, "message": f"Wrote to {file_path}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _tool_exec(self, params: Dict) -> Dict:
        """Execute shell command tool"""
        import subprocess
        command = params.get("command")
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30
            )
            return {
                "success": True,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _tool_web_search(self, params: Dict) -> Dict:
        """Web search tool (placeholder)"""
        # In production, integrate with actual search API
        return {
            "success": True,
            "results": [
                {"title": "Example Result", "url": "https://example.com", "snippet": "Example snippet"}
            ],
            "note": "This is a placeholder. Integrate with actual search API."
        }

    async def _tool_web_fetch(self, params: Dict) -> Dict:
        """Web fetch tool"""
        import httpx
        url = params.get("url")
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, timeout=30)
                return {
                    "success": True,
                    "content": response.text[:10000],  # Limit to 10KB
                    "status_code": response.status_code
                }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _tool_llm_task(self, params: Dict) -> Dict:
        """Delegate subtask to LLM"""
        task = params.get("task")
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=2048,
                messages=[{"role": "user", "content": task}]
            )
            return {
                "success": True,
                "result": response.content[0].text
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _tool_python(self, params: Dict) -> Dict:
        """Execute Python code (sandboxed)"""
        # WARNING: This is dangerous in production!
        # Should use a proper sandbox like RestrictedPython
        code = params.get("code")
        try:
            # Very limited execution
            exec_globals = {"__builtins__": {}}
            exec_locals = {}
            exec(code, exec_globals, exec_locals)
            return {
                "success": True,
                "result": str(exec_locals),
                "warning": "Sandboxing not implemented - use with caution!"
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _tool_api_call(self, params: Dict) -> Dict:
        """Make HTTP API call"""
        import httpx
        method = params.get("method", "GET")
        url = params.get("url")
        headers = params.get("headers", {})
        body = params.get("body")

        try:
            async with httpx.AsyncClient() as client:
                response = await client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=body,
                    timeout=30
                )
                return {
                    "success": True,
                    "status_code": response.status_code,
                    "headers": dict(response.headers),
                    "body": response.text[:5000]  # Limit to 5KB
                }
        except Exception as e:
            return {"success": False, "error": str(e)}


# Example usage
if __name__ == "__main__":
    import asyncio

    async def main():
        # Create agent
        agent = OpenClawAgent()

        # Create a task
        task = AgentTask(
            id="test-001",
            description="Search the web for 'OpenClaw AI' and summarize the top result",
            context={},
            skills=["web-scraper"]  # Use web scraper skill
        )

        # Execute task
        result = await agent.execute_task(task)

        print("=== Task Result ===")
        print(json.dumps(result, indent=2))

    asyncio.run(main())
