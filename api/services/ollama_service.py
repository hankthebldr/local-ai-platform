#!/usr/bin/env python3
"""
Ollama Service - Business logic for Ollama API interactions
"""

import os
import json
from typing import Dict, List, Optional, AsyncGenerator
import requests
from dotenv import load_dotenv

load_dotenv()

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")


class OllamaService:
    """Service for interacting with Ollama API"""

    def __init__(self, host: str = OLLAMA_HOST):
        self.host = host

    def list_models(self) -> List[Dict]:
        """
        List all available models from Ollama

        Returns:
            List of model dictionaries
        """
        try:
            response = requests.get(f"{self.host}/api/tags", timeout=10)
            response.raise_for_status()
            return response.json().get("models", [])
        except Exception as e:
            raise Exception(f"Failed to list models: {str(e)}")

    def generate(
        self,
        model: str,
        prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        stream: bool = False
    ) -> Dict:
        """
        Generate a completion using Ollama

        Args:
            model: Model name
            prompt: Input prompt
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            stream: Whether to stream the response

        Returns:
            Response dictionary from Ollama
        """
        request_data = {
            "model": model,
            "prompt": prompt,
            "temperature": temperature,
            "stream": stream,
            "options": {
                "num_predict": max_tokens
            }
        }

        try:
            response = requests.post(
                f"{self.host}/api/generate",
                json=request_data,
                timeout=300,
                stream=stream
            )
            response.raise_for_status()

            if stream:
                return response
            else:
                return response.json()
        except Exception as e:
            raise Exception(f"Failed to generate completion: {str(e)}")

    async def generate_stream(
        self,
        model: str,
        prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 2048
    ) -> AsyncGenerator[str, None]:
        """
        Generate a streaming completion using Ollama

        Args:
            model: Model name
            prompt: Input prompt
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate

        Yields:
            Chunks of the response
        """
        request_data = {
            "model": model,
            "prompt": prompt,
            "temperature": temperature,
            "stream": True,
            "options": {
                "num_predict": max_tokens
            }
        }

        try:
            response = requests.post(
                f"{self.host}/api/generate",
                json=request_data,
                timeout=300,
                stream=True
            )
            response.raise_for_status()

            for line in response.iter_lines():
                if line:
                    chunk = json.loads(line)
                    if "response" in chunk:
                        yield chunk["response"]
                    if chunk.get("done", False):
                        break
        except Exception as e:
            raise Exception(f"Failed to generate streaming completion: {str(e)}")

    def format_chat_prompt(self, messages: List[Dict]) -> str:
        """
        Format chat messages into a single prompt

        Args:
            messages: List of message dictionaries with 'role' and 'content'

        Returns:
            Formatted prompt string
        """
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

    def health_check(self) -> bool:
        """
        Check if Ollama service is healthy

        Returns:
            True if healthy, False otherwise
        """
        try:
            response = requests.get(f"{self.host}/api/tags", timeout=5)
            return response.status_code == 200
        except:
            return False
