#!/usr/bin/env python3
"""
Chunker — Thin wrapper around LangChain's RecursiveCharacterTextSplitter
"""

from __future__ import annotations

from typing import Optional


class Chunker:
    """Splits text into overlapping chunks using recursive character splitting."""

    def __init__(self, chunk_size: int = 512, chunk_overlap: int = 50):
        from langchain.text_splitter import RecursiveCharacterTextSplitter
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", ". ", " ", ""],
        )

    def split(self, text: str) -> list:
        """Return a list of chunk strings. Empty text → empty list."""
        if not text or not text.strip():
            return []
        return self._splitter.split_text(text)
