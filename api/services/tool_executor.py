#!/usr/bin/env python3
"""
Tool Executor — Iterative tool-calling loop for agentic LLM interactions
"""

from __future__ import annotations

import json
from typing import List, Dict

from ..logging_config import logger
from .ollama_service import OllamaService
from .plugin_service import PluginService


class ToolExecutor:
    """Runs the iterative tool-calling loop between the LLM and plugin tools."""

    def __init__(self, ollama_service: OllamaService, plugin_service: PluginService):
        self.ollama = ollama_service
        self.plugins = plugin_service

    def execute(
        self,
        model: str,
        messages: List[Dict],
        temperature: float = 0.7,
        max_tokens: int = 2048,
        max_iterations: int = 10,
    ) -> Dict:
        ollama_tools = self.plugins.get_ollama_tools()
        tool_calls_made = []
        total_prompt_tokens = 0
        total_completion_tokens = 0
        working_messages = list(messages)
        result = {}

        for iteration in range(max_iterations):
            logger.info(f"Tool loop iteration {iteration + 1}/{max_iterations}")

            result = self.ollama.chat(
                model=model,
                messages=working_messages,
                temperature=temperature,
                max_tokens=max_tokens,
                tools=ollama_tools if ollama_tools else None,
            )

            total_prompt_tokens += result.get("prompt_eval_count", 0)
            total_completion_tokens += result.get("eval_count", 0)

            tool_calls = result.get("tool_calls")
            if not tool_calls:
                return {
                    "content": result["content"],
                    "tool_calls_made": tool_calls_made,
                    "stopped_reason": "complete",
                    "prompt_eval_count": total_prompt_tokens,
                    "eval_count": total_completion_tokens,
                }

            working_messages.append({
                "role": "assistant",
                "content": result.get("content", ""),
                "tool_calls": tool_calls,
            })

            for tc in tool_calls:
                func = tc.get("function", {})
                tool_name = func.get("name", "")
                arguments = func.get("arguments", {})
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except json.JSONDecodeError:
                        arguments = {}

                tool_result = self._execute_tool(tool_name, arguments)
                tool_calls_made.append({
                    "tool": tool_name,
                    "arguments": arguments,
                    "result": tool_result,
                    "iteration": iteration + 1,
                })
                working_messages.append({
                    "role": "tool",
                    "content": json.dumps(tool_result),
                })
                logger.info(f"Tool call: {tool_name}({json.dumps(arguments)[:100]}) -> {json.dumps(tool_result)[:100]}")

        logger.warning(f"Tool loop hit max iterations ({max_iterations})")
        return {
            "content": result.get("content", "Max tool iterations reached."),
            "tool_calls_made": tool_calls_made,
            "stopped_reason": "max_iterations",
            "prompt_eval_count": total_prompt_tokens,
            "eval_count": total_completion_tokens,
        }

    def _execute_tool(self, tool_name: str, arguments: dict) -> dict:
        parts = tool_name.split("__", 1)
        if len(parts) != 2:
            return {"error": f"Invalid tool name format: {tool_name}. Expected 'plugin_id__tool_id'."}
        plugin_id, tool_id = parts
        try:
            return self.plugins.call_tool(plugin_id, tool_id, arguments)
        except (ValueError, RuntimeError) as e:
            logger.error(f"Tool execution failed: {tool_name}: {e}")
            return {"error": str(e)}
        except Exception as e:
            logger.error(f"Unexpected tool error: {tool_name}: {e}")
            return {"error": f"Unexpected error: {e}"}
