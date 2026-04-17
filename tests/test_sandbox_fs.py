#!/usr/bin/env python3
"""Tests for SandboxedFS — filesystem boundary enforcement"""

import os
import pytest
import tempfile
import shutil
from pathlib import Path


@pytest.fixture
def sandbox_dir():
    tmpdir = tempfile.mkdtemp()
    yield tmpdir
    shutil.rmtree(tmpdir)


class TestBasicIO:
    def test_write_and_read(self, sandbox_dir):
        from api.services.sandbox_fs import SandboxedFS
        sb = SandboxedFS(sandbox_root=sandbox_dir)
        sb.write("hello.txt", "world")
        assert sb.read("hello.txt") == "world"

    def test_exists(self, sandbox_dir):
        from api.services.sandbox_fs import SandboxedFS
        sb = SandboxedFS(sandbox_root=sandbox_dir)
        assert not sb.exists("missing.txt")
        sb.write("there.txt", "x")
        assert sb.exists("there.txt")

    def test_listdir(self, sandbox_dir):
        from api.services.sandbox_fs import SandboxedFS
        sb = SandboxedFS(sandbox_root=sandbox_dir)
        sb.write("a.txt", "1")
        sb.write("b.txt", "2")
        entries = sb.listdir()
        assert sorted(entries) == ["a.txt", "b.txt"]

    def test_delete(self, sandbox_dir):
        from api.services.sandbox_fs import SandboxedFS
        sb = SandboxedFS(sandbox_root=sandbox_dir)
        sb.write("doomed.txt", "bye")
        sb.delete("doomed.txt")
        assert not sb.exists("doomed.txt")

    def test_nested_directory_creation(self, sandbox_dir):
        from api.services.sandbox_fs import SandboxedFS
        sb = SandboxedFS(sandbox_root=sandbox_dir)
        sb.write("sub/dir/file.txt", "nested")
        assert sb.read("sub/dir/file.txt") == "nested"


class TestPathTraversal:
    def test_parent_dir_escape(self, sandbox_dir):
        from api.services.sandbox_fs import SandboxedFS, SandboxViolation
        sb = SandboxedFS(sandbox_root=sandbox_dir)
        with pytest.raises(SandboxViolation):
            sb.read("../../../etc/passwd")

    def test_absolute_path_blocked(self, sandbox_dir):
        from api.services.sandbox_fs import SandboxedFS, SandboxViolation
        sb = SandboxedFS(sandbox_root=sandbox_dir)
        with pytest.raises(SandboxViolation):
            sb.read("/etc/passwd")

    def test_symlink_escape_blocked(self, sandbox_dir):
        from api.services.sandbox_fs import SandboxedFS, SandboxViolation
        sb = SandboxedFS(sandbox_root=sandbox_dir)
        outside = tempfile.NamedTemporaryFile(delete=False, mode="w")
        outside.write("secret")
        outside.close()
        try:
            link_path = Path(sandbox_dir) / "evil_link"
            os.symlink(outside.name, link_path)
            with pytest.raises(SandboxViolation):
                sb.read("evil_link")
        finally:
            os.unlink(outside.name)

    def test_write_outside_blocked(self, sandbox_dir):
        from api.services.sandbox_fs import SandboxedFS, SandboxViolation
        sb = SandboxedFS(sandbox_root=sandbox_dir)
        with pytest.raises(SandboxViolation):
            sb.write("../escape.txt", "nope")


class TestQuotas:
    def test_size_limit_enforced(self, sandbox_dir):
        from api.services.sandbox_fs import SandboxedFS, SandboxQuotaExceeded
        sb = SandboxedFS(sandbox_root=sandbox_dir, max_file_size_mb=1)
        too_big = "x" * (2 * 1024 * 1024)
        with pytest.raises(SandboxQuotaExceeded):
            sb.write("huge.txt", too_big)

    def test_size_under_limit_ok(self, sandbox_dir):
        from api.services.sandbox_fs import SandboxedFS
        sb = SandboxedFS(sandbox_root=sandbox_dir, max_file_size_mb=1)
        small = "x" * 1024
        sb.write("small.txt", small)
        assert sb.read("small.txt") == small

    def test_extension_allowlist_enforced(self, sandbox_dir):
        from api.services.sandbox_fs import SandboxedFS, SandboxViolation
        sb = SandboxedFS(sandbox_root=sandbox_dir, allowed_extensions=["txt", "md"])
        sb.write("doc.txt", "ok")
        sb.write("notes.md", "ok")
        with pytest.raises(SandboxViolation):
            sb.write("script.sh", "bad")

    def test_extension_none_allows_all(self, sandbox_dir):
        from api.services.sandbox_fs import SandboxedFS
        sb = SandboxedFS(sandbox_root=sandbox_dir, allowed_extensions=None)
        sb.write("any.xyz", "ok")


class TestStats:
    def test_stats_empty(self, sandbox_dir):
        from api.services.sandbox_fs import SandboxedFS
        sb = SandboxedFS(sandbox_root=sandbox_dir)
        s = sb.stats()
        assert s["file_count"] == 0
        assert s["total_bytes"] == 0

    def test_stats_with_files(self, sandbox_dir):
        from api.services.sandbox_fs import SandboxedFS
        sb = SandboxedFS(sandbox_root=sandbox_dir)
        sb.write("a.txt", "hello")
        sb.write("sub/b.txt", "world")
        s = sb.stats()
        assert s["file_count"] == 2
        assert s["total_bytes"] == 10
