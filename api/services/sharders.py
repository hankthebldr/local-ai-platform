"""
Sharders — split a large input into deterministic shards for kind=parallel
`mode: sharded`.

In sharded mode the workflow declares ONE persona (a single branch template)
and a shard strategy. The engine resolves the shard_input from the workflow
context, splits it into N shards here, then clones the persona once per shard
(seeding each clone with `seed.shard`). One persona × N shards = N branches at
runtime — the operator never enumerates them.

Strategies:

  by_file
      Input is a list. Each element becomes one shard verbatim. The canonical
      "one branch per source file / per document" split. shard_size is ignored.

  by_chunk
      Input is a list → grouped into sublists of `shard_size` elements
      (default 1, i.e. same as by_file). Input is a string → split into
      `shard_size`-character chunks (default 4000). Use when items are cheap
      and you want to batch several per LLM call.

  by_token_window
      Input is a string → split into windows of approximately `shard_size`
      tokens (default 2000), estimating ~4 chars/token. Windows break on
      whitespace so a token isn't split mid-word. Use for one long document
      that doesn't fit in context.

All strategies are deterministic and cap output at `max_shards` (the tail
beyond the cap is dropped with a warning — the caller decides whether that's
acceptable). Never raises on empty/None input — returns [].
"""

from __future__ import annotations

from typing import Any, List

from ..logging_config import logger

VALID_SHARDERS = ("by_file", "by_chunk", "by_token_window")

# Rough chars-per-token for the by_token_window estimate. Real tokenization is
# model-specific; 4 is the standard ballpark for English text and is plenty
# accurate for deciding window boundaries.
_CHARS_PER_TOKEN = 4

_DEFAULT_CHUNK_CHARS = 4000
_DEFAULT_WINDOW_TOKENS = 2000


def shard(
    strategy: str,
    data: Any,
    shard_size: int | None = None,
    max_shards: int = 32,
) -> List[Any]:
    """Split `data` into a list of shards per `strategy`.

    Returns at most `max_shards` shards. Each shard is whatever the persona
    will receive as `seed.shard` — a list element, a sublist, or a text window.
    """
    if strategy not in VALID_SHARDERS:
        raise ValueError(f"unknown sharder {strategy!r} (valid: {VALID_SHARDERS})")
    if data is None:
        return []

    if strategy == "by_file":
        shards = _by_file(data)
    elif strategy == "by_chunk":
        shards = _by_chunk(data, shard_size)
    else:  # by_token_window
        shards = _by_token_window(data, shard_size)

    if len(shards) > max_shards:
        logger.warning(
            "sharder %s produced %d shards; capping at max_shards=%d " "(tail dropped)",
            strategy,
            len(shards),
            max_shards,
        )
        shards = shards[:max_shards]
    return shards


def _by_file(data: Any) -> List[Any]:
    """One shard per list element. A non-list input is treated as a single
    shard (so a lone string/dict still works)."""
    if isinstance(data, list):
        return [d for d in data if d is not None]
    return [data]


def _by_chunk(data: Any, shard_size: int | None) -> List[Any]:
    """List → groups of `shard_size` elements. String → `shard_size`-char
    substrings."""
    if isinstance(data, list):
        n = shard_size if shard_size and shard_size > 0 else 1
        items = [d for d in data if d is not None]
        return [items[i : i + n] for i in range(0, len(items), n)]
    if isinstance(data, str):
        n = shard_size if shard_size and shard_size > 0 else _DEFAULT_CHUNK_CHARS
        text = data
        return [text[i : i + n] for i in range(0, len(text), n)] or (
            [""] if text == "" else []
        )
    # Anything else: a single shard.
    return [data]


def _by_token_window(data: Any, shard_size: int | None) -> List[Any]:
    """String → windows of ~`shard_size` tokens, breaking on whitespace so
    words aren't split. Non-string input falls back to a single shard."""
    if not isinstance(data, str):
        return [data]
    if data == "":
        return []
    tokens_per_window = (
        shard_size if shard_size and shard_size > 0 else _DEFAULT_WINDOW_TOKENS
    )
    target_chars = tokens_per_window * _CHARS_PER_TOKEN

    windows: List[str] = []
    words = data.split()
    if not words:
        return [data]

    current: List[str] = []
    current_len = 0
    for word in words:
        # +1 for the joining space.
        add_len = len(word) + (1 if current else 0)
        if current and current_len + add_len > target_chars:
            windows.append(" ".join(current))
            current = [word]
            current_len = len(word)
        else:
            current.append(word)
            current_len += add_len
    if current:
        windows.append(" ".join(current))
    return windows
