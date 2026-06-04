import os
import time
from pathlib import Path

from api.services.sandbox_reaper import reap_scratch


def test_reaper_removes_old_dirs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    base = Path("data/sandboxes")
    base.mkdir(parents=True)
    old = base / "wf-old"
    old.mkdir()
    new = base / "wf-new"
    new.mkdir()
    old_time = time.time() - 48 * 3600
    os.utime(old, (old_time, old_time))
    removed = reap_scratch(ttl_hours=24)
    assert "wf-old" in removed and not old.exists() and new.exists()
