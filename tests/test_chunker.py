#!/usr/bin/env python3
"""Tests for Chunker — LangChain RecursiveCharacterTextSplitter wrapper"""

import pytest

pytestmark = pytest.mark.rag


class TestChunker:
    def test_split_returns_list_of_strings(self):
        from api.services.chunker import Chunker
        c = Chunker(chunk_size=100, chunk_overlap=10)
        chunks = c.split("hello world")
        assert isinstance(chunks, list)
        assert all(isinstance(x, str) for x in chunks)

    def test_short_text_is_single_chunk(self):
        from api.services.chunker import Chunker
        c = Chunker(chunk_size=1000, chunk_overlap=50)
        chunks = c.split("Short text.")
        assert len(chunks) == 1
        assert chunks[0] == "Short text."

    def test_long_text_is_split(self):
        from api.services.chunker import Chunker
        c = Chunker(chunk_size=50, chunk_overlap=0)
        text = "Paragraph one.\n\n" + ("Sentence. " * 30)
        chunks = c.split(text)
        assert len(chunks) > 1

    def test_empty_text_returns_empty_list(self):
        from api.services.chunker import Chunker
        c = Chunker(chunk_size=100, chunk_overlap=10)
        assert c.split("") == []

    def test_chunks_respect_boundaries(self):
        from api.services.chunker import Chunker
        c = Chunker(chunk_size=80, chunk_overlap=10)
        text = "First paragraph about cats.\n\nSecond paragraph about dogs.\n\nThird paragraph about birds."
        chunks = c.split(text)
        for ch in chunks:
            assert len(ch) <= 120
