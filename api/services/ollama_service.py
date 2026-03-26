#!/usr/bin/env python3
"""
Ollama Service - Business logic for Ollama API interactions

Uses /api/chat for chat completions (proper template handling for thinking models)
Uses /api/generate for raw text completions
"""

import os
import re
import json
from typing import Dict, List, AsyncGenerator

import requests
from dotenv import load_dotenv

from ..logging_config import logger
from ..exceptions import OllamaConnectionError, GenerationError, ModelNotFoundError

load_dotenv()

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "300"))

# Regex to strip <think>...</think> blocks from reasoning models
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def strip_think_tags(text: str) -> str:
    """Remove <think>...</think> blocks from model output (reasoning models)."""
    cleaned = _THINK_RE.sub("", text).strip()
    return cleaned if cleaned else text  # Fall back to original if entirely think block


def _format_chat_prompt(messages: List[Dict]) -> str:
    """Format chat messages into a plain-text prompt (fallback for models without chat templates)."""
    prompt = ""
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role == "system":
            prompt += f"System: {content}\n\n"
        elif role == "user":
            prompt += f"User: {content}\n\n"
        elif role == "assistant":
            prompt += f"Assistant: {content}\n\n"
    prompt += "Assistant:"
    return prompt


class OllamaService:
    """Service for interacting with Ollama API"""

    def __init__(self, host: str = OLLAMA_HOST):
        self.host = host

    # ── Model Management ───────────────────────────────────────────────

    def list_models(self) -> List[Dict]:
        """List all available models from Ollama"""
        try:
            response = requests.get(f"{self.host}/api/tags", timeout=10)
            response.raise_for_status()
            return response.json().get("models", [])
        except requests.ConnectionError:
            raise OllamaConnectionError(f"Cannot connect to {self.host}")
        except Exception as e:
            logger.error(f"Failed to list models: {e}")
            raise OllamaConnectionError(str(e))

    def get_model_info(self, model: str) -> Dict:
        """Get detailed info about a specific model"""
        try:
            response = requests.post(
                f"{self.host}/api/show",
                json={"name": model},
                timeout=10,
            )
            response.raise_for_status()
            return response.json()
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                raise ModelNotFoundError(model)
            raise OllamaConnectionError(str(e))
        except requests.ConnectionError:
            raise OllamaConnectionError(f"Cannot connect to {self.host}")

    # ── Chat Completions (uses /api/chat) ──────────────────────────────

    def chat(
        self,
        model: str,
        messages: List[Dict],
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> Dict:
        """
        Chat completion using Ollama's native /api/chat endpoint.

        Falls back to /api/generate with manual prompt formatting if /api/chat
        returns empty content (happens with models that lack chat templates,
        e.g. some uncensored/thinking models).
        """
        request_data = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        logger.info(f"Chat request: model={model}, messages={len(messages)}, temp={temperature}")

        try:
            response = requests.post(
                f"{self.host}/api/chat",
                json=request_data,
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            result = response.json()

            # Strip thinking tags from response content
            content = result.get("message", {}).get("content", "")
            content = strip_think_tags(content)

            # Fallback: if /api/chat returned empty, use /api/generate
            if not content.strip():
                logger.info(f"Chat returned empty for {model}, falling back to /api/generate")
                prompt = _format_chat_prompt(messages)
                gen_result = self.generate(model=model, prompt=prompt, temperature=temperature, max_tokens=max_tokens)
                content = gen_result.get("response", "")
                result["prompt_eval_count"] = gen_result.get("prompt_eval_count", 0)
                result["eval_count"] = gen_result.get("eval_count", 0)

            logger.info(
                f"Chat complete: model={model}, "
                f"prompt_tokens={result.get('prompt_eval_count', 0)}, "
                f"completion_tokens={result.get('eval_count', 0)}"
            )

            return {
                "content": content,
                "prompt_eval_count": result.get("prompt_eval_count", 0),
                "eval_count": result.get("eval_count", 0),
            }
        except requests.ConnectionError:
            raise OllamaConnectionError(f"Cannot connect to {self.host}")
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                raise ModelNotFoundError(model)
            raise GenerationError(str(e))
        except (OllamaConnectionError, ModelNotFoundError, GenerationError):
            raise
        except Exception as e:
            logger.error(f"Chat failed: {e}")
            raise GenerationError(str(e))

    async def chat_stream(
        self,
        model: str,
        messages: List[Dict],
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> AsyncGenerator[str, None]:
        """
        Streaming chat completion using Ollama's /api/chat endpoint.
        Filters out <think> blocks from streaming output.
        """
        request_data = {
            "model": model,
            "messages": messages,
            "stream": True,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        logger.info(f"Chat stream: model={model}, messages={len(messages)}")

        try:
            response = requests.post(
                f"{self.host}/api/chat",
                json=request_data,
                timeout=REQUEST_TIMEOUT,
                stream=True,
            )
            response.raise_for_status()

            in_think_block = False
            for line in response.iter_lines():
                if line:
                    chunk = json.loads(line)
                    content = chunk.get("message", {}).get("content", "")

                    # Track think blocks in streaming mode
                    if "<think>" in content:
                        in_think_block = True
                        # Emit any text before the tag
                        before = content.split("<think>")[0]
                        if before:
                            yield before
                        continue
                    if "</think>" in content:
                        in_think_block = False
                        # Emit any text after the closing tag
                        after = content.split("</think>")[-1]
                        if after:
                            yield after
                        continue
                    if in_think_block:
                        continue

                    if content:
                        yield content
                    if chunk.get("done", False):
                        break
        except requests.ConnectionError:
            raise OllamaConnectionError(f"Cannot connect to {self.host}")
        except Exception as e:
            logger.error(f"Chat stream failed: {e}")
            raise GenerationError(str(e))

    # ── Text Completions (uses /api/generate) ──────────────────────────

    def generate(
        self,
        model: str,
        prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> Dict:
        """Generate a raw text completion using Ollama /api/generate"""
        request_data = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        logger.info(f"Generate request: model={model}, temp={temperature}")

        try:
            response = requests.post(
                f"{self.host}/api/generate",
                json=request_data,
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            result = response.json()

            # Strip thinking tags
            result["response"] = strip_think_tags(result.get("response", ""))

            logger.info(
                f"Generate complete: model={model}, "
                f"prompt_tokens={result.get('prompt_eval_count', 0)}, "
                f"completion_tokens={result.get('eval_count', 0)}"
            )
            return result
        except requests.ConnectionError:
            raise OllamaConnectionError(f"Cannot connect to {self.host}")
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                raise ModelNotFoundError(model)
            raise GenerationError(str(e))
        except Exception as e:
            logger.error(f"Generation failed: {e}")
            raise GenerationError(str(e))

    async def generate_stream(
        self,
        model: str,
        prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> AsyncGenerator[str, None]:
        """Streaming text completion using Ollama /api/generate"""
        request_data = {
            "model": model,
            "prompt": prompt,
            "stream": True,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        logger.info(f"Generate stream: model={model}")

        try:
            response = requests.post(
                f"{self.host}/api/generate",
                json=request_data,
                timeout=REQUEST_TIMEOUT,
                stream=True,
            )
            response.raise_for_status()

            in_think_block = False
            for line in response.iter_lines():
                if line:
                    chunk = json.loads(line)
                    content = chunk.get("response", "")

                    if "<think>" in content:
                        in_think_block = True
                        before = content.split("<think>")[0]
                        if before:
                            yield before
                        continue
                    if "</think>" in content:
                        in_think_block = False
                        after = content.split("</think>")[-1]
                        if after:
                            yield after
                        continue
                    if in_think_block:
                        continue

                    if content:
                        yield content
                    if chunk.get("done", False):
                        break
        except requests.ConnectionError:
            raise OllamaConnectionError(f"Cannot connect to {self.host}")
        except Exception as e:
            logger.error(f"Generate stream failed: {e}")
            raise GenerationError(str(e))

    # ── Utilities ──────────────────────────────────────────────────────

    def health_check(self) -> bool:
        """Check if Ollama service is healthy"""
        try:
            response = requests.get(f"{self.host}/api/tags", timeout=5)
            return response.status_code == 200
        except Exception:
            return False
