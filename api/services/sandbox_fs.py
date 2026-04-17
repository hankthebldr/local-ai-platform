#!/usr/bin/env python3
"""
SandboxedFS — Per-conversation filesystem boundary

Tools opt in to sandboxing via a __sandbox kwarg. All paths are treated
as relative to the sandbox root and checked for traversal escape before
any filesystem operation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from ..logging_config import logger


class SandboxViolation(Exception):
    """Raised when a tool attempts to access outside the sandbox or violates a rule."""


class SandboxQuotaExceeded(Exception):
    """Raised when a tool exceeds size limits."""


class SandboxedFS:
    """Restricts filesystem access to a designated sandbox root directory."""

    def __init__(
        self,
        sandbox_root: str,
        max_file_size_mb: int = 10,
        allowed_extensions: Optional[list] = None,
    ):
        self.root = Path(sandbox_root).resolve()
        self.max_file_size = max_file_size_mb * 1024 * 1024
        self.allowed_extensions = allowed_extensions
        self.root.mkdir(parents=True, exist_ok=True)

    def get_absolute_path(self, relative_path: str) -> Path:
        """Resolve a relative path within the sandbox; raise SandboxViolation on escape."""
        # Reject absolute paths explicitly before any stripping
        if relative_path.startswith("/") or relative_path.startswith("\\"):
            raise SandboxViolation(
                f"Absolute path '{relative_path}' is not allowed in sandbox"
            )
        candidate = (self.root / relative_path).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError:
            raise SandboxViolation(
                f"Path '{relative_path}' escapes sandbox root"
            )
        return candidate

    def _check_extension(self, path: str) -> None:
        if self.allowed_extensions is None:
            return
        suffix = Path(path).suffix.lstrip(".").lower()
        allowed = [e.lower().lstrip(".") for e in self.allowed_extensions]
        if suffix not in allowed:
            raise SandboxViolation(
                f"Extension '.{suffix}' not in allowed list {allowed}"
            )

    def read(self, path: str, encoding: str = "utf-8") -> str:
        abs_path = self.get_absolute_path(path)
        if not abs_path.exists():
            raise FileNotFoundError(f"File not found in sandbox: {path}")
        return abs_path.read_text(encoding=encoding)

    def write(self, path: str, content: str, encoding: str = "utf-8") -> None:
        self._check_extension(path)
        abs_path = self.get_absolute_path(path)
        encoded = content.encode(encoding)
        if len(encoded) > self.max_file_size:
            raise SandboxQuotaExceeded(
                f"File size {len(encoded)} exceeds max {self.max_file_size}"
            )
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_bytes(encoded)

    def open(self, path: str, mode: str = "r", **kwargs):
        abs_path = self.get_absolute_path(path)
        if "w" in mode or "a" in mode:
            self._check_extension(path)
            abs_path.parent.mkdir(parents=True, exist_ok=True)
        return abs_path.open(mode, **kwargs)

    def exists(self, path: str) -> bool:
        try:
            abs_path = self.get_absolute_path(path)
        except SandboxViolation:
            return False
        return abs_path.exists()

    def listdir(self, path: str = "") -> list:
        abs_path = self.get_absolute_path(path) if path else self.root
        if not abs_path.exists():
            return []
        return [p.name for p in abs_path.iterdir()]

    def delete(self, path: str) -> None:
        abs_path = self.get_absolute_path(path)
        if abs_path.is_file():
            abs_path.unlink()
        elif abs_path.is_dir():
            import shutil
            shutil.rmtree(abs_path)

    def stats(self) -> dict:
        file_count = 0
        total_bytes = 0
        if self.root.exists():
            for p in self.root.rglob("*"):
                if p.is_file():
                    file_count += 1
                    total_bytes += p.stat().st_size
        return {
            "root": str(self.root),
            "file_count": file_count,
            "total_bytes": total_bytes,
            "max_file_size": self.max_file_size,
        }
