import pytest
from api.services.sandbox_fs import SandboxedFS, SandboxViolation


def test_write_bytes_mkdir_walk(tmp_path):
    fs = SandboxedFS(str(tmp_path / "sbx"))
    fs.mkdir("work/sub")
    fs.write_bytes("work/sub/data.bin", b"\x00\x01\x02")
    assert fs.exists("work/sub/data.bin")
    rels = set(fs.walk())
    assert "work/sub/data.bin" in rels


def test_write_bytes_blocks_traversal(tmp_path):
    fs = SandboxedFS(str(tmp_path / "sbx"))
    with pytest.raises(SandboxViolation):
        fs.write_bytes("../escape.bin", b"x")
