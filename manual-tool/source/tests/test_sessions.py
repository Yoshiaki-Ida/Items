from __future__ import annotations

import os
import time
import uuid

from manual_tool.sessions import SessionStore


def test_delete_removes_session_from_memory_and_disk(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    session = store.create("manual.md", "# Manual")

    store.delete(session.id)

    assert not session.directory.exists()
    try:
        store.get(session.id)
    except KeyError:
        pass
    else:
        raise AssertionError("deleted session remained available")


def test_startup_cleanup_removes_only_expired_session_directories(tmp_path):
    root = tmp_path / "sessions"
    expired = root / uuid.uuid4().hex
    unrelated = root / "keep-me"
    expired.mkdir(parents=True)
    unrelated.mkdir()
    old = time.time() - 48 * 60 * 60
    os.utime(expired, (old, old))
    os.utime(unrelated, (old, old))

    SessionStore(root, max_age_seconds=24 * 60 * 60)

    assert not expired.exists()
    assert unrelated.exists()
