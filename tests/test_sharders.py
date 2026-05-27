"""Unit tests for the sharder framework (kind=parallel mode=sharded)."""

import pytest

from api.services.sharders import shard, VALID_SHARDERS


class TestByFile:
    def test_list_one_shard_per_element(self):
        assert shard("by_file", ["a.py", "b.py", "c.py"]) == ["a.py", "b.py", "c.py"]

    def test_scalar_becomes_single_shard(self):
        assert shard("by_file", "lonely") == ["lonely"]

    def test_drops_none_elements(self):
        assert shard("by_file", ["a", None, "b"]) == ["a", "b"]

    def test_none_input_empty(self):
        assert shard("by_file", None) == []


class TestByChunk:
    def test_list_grouped_by_size(self):
        assert shard("by_chunk", [1, 2, 3, 4, 5], shard_size=2) == [
            [1, 2],
            [3, 4],
            [5],
        ]

    def test_list_default_size_one(self):
        assert shard("by_chunk", [1, 2, 3]) == [[1], [2], [3]]

    def test_string_split_by_chars(self):
        assert shard("by_chunk", "abcdefghij", shard_size=4) == ["abcd", "efgh", "ij"]


class TestByTokenWindow:
    def test_splits_on_whitespace_no_midword(self):
        text = " ".join(f"w{i}" for i in range(30))  # 30 short words
        windows = shard("by_token_window", text, shard_size=5)  # ~5 tok ≈ 20 chars
        assert len(windows) > 1
        # No window splits a word — rejoining reproduces the input word list.
        rejoined = " ".join(windows).split()
        assert rejoined == text.split()

    def test_short_text_single_window(self):
        assert shard("by_token_window", "just a few words", shard_size=2000) == [
            "just a few words"
        ]

    def test_empty_string(self):
        assert shard("by_token_window", "") == []

    def test_non_string_single_shard(self):
        assert shard("by_token_window", {"a": 1}) == [{"a": 1}]


class TestCapAndValidation:
    def test_max_shards_caps(self):
        out = shard("by_file", list(range(100)), max_shards=10)
        assert len(out) == 10
        assert out == list(range(10))

    def test_invalid_strategy_raises(self):
        with pytest.raises(ValueError, match="unknown sharder"):
            shard("by_nonsense", [1, 2])

    def test_valid_sharders_constant(self):
        assert set(VALID_SHARDERS) == {"by_file", "by_chunk", "by_token_window"}
