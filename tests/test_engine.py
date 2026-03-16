"""Tests for bwsync.engine — uses temp DB, no real sources or Bitwarden."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from bwsync.db import StateStore
from bwsync.engine import BWSyncEngine
from bwsync.schema import NormalizedEntry, SyncStatus


def _make_engine(tmp_dir: Path) -> BWSyncEngine:
    """Create an engine with temp DB, config, and mocked BW client (no httpx needed)."""
    engine = BWSyncEngine.__new__(BWSyncEngine)
    engine.config = __import__("bwsync.config", fromlist=["Config"]).Config(tmp_dir / "cfg.json")
    engine.db = StateStore(tmp_dir / "state.db")
    engine.bw = MagicMock()
    return engine


def test_normalize_dedup():
    with tempfile.TemporaryDirectory() as tmp:
        engine = _make_engine(Path(tmp))
        entries = [
            NormalizedEntry(
                url="https://example.com",
                username="alice",
                password="pw1",
                source="chrome",
                date_last_used="2024-01-01",
            ),
            NormalizedEntry(
                url="https://example.com",
                username="alice",
                password="pw2",
                source="chrome",
                date_last_used="2024-06-01",
            ),
        ]
        result = engine._normalize(entries)
        assert len(result) == 1
        assert result[0].password == "pw2"  # latest date wins


def test_normalize_keeps_distinct():
    with tempfile.TemporaryDirectory() as tmp:
        engine = _make_engine(Path(tmp))
        entries = [
            NormalizedEntry(url="https://a.com", username="alice", source="chrome"),
            NormalizedEntry(url="https://b.com", username="bob", source="chrome"),
        ]
        result = engine._normalize(entries)
        assert len(result) == 2


def test_classify_new_entry():
    with tempfile.TemporaryDirectory() as tmp:
        engine = _make_engine(Path(tmp))
        engine.bw = MagicMock()
        engine.bw.find_matching_item.return_value = None

        entry = NormalizedEntry(
            url="https://new-site.com", username="user", password="pw"
        )
        assert engine._classify_entry(entry) == "new"


def test_classify_synced_same_password():
    with tempfile.TemporaryDirectory() as tmp:
        engine = _make_engine(Path(tmp))
        entry = NormalizedEntry(
            url="https://example.com",
            username="alice",
            password="secret",
            sync_status=SyncStatus.SYNCED,
        )
        engine.db.upsert_entry(entry)
        engine.db.update_sync_status(entry.source_key, SyncStatus.SYNCED)

        assert engine._classify_entry(entry) == "synced"


def test_classify_conflict_different_password():
    with tempfile.TemporaryDirectory() as tmp:
        engine = _make_engine(Path(tmp))
        entry = NormalizedEntry(
            url="https://example.com",
            username="alice",
            password="old_password",
            sync_status=SyncStatus.SYNCED,
        )
        engine.db.upsert_entry(entry)
        engine.db.update_sync_status(entry.source_key, SyncStatus.SYNCED)

        # Same URL+username but different password
        new_entry = NormalizedEntry(
            url="https://example.com",
            username="alice",
            password="new_password",
        )
        assert engine._classify_entry(new_entry) == "conflict"


def test_resolve_conflict_keep_source():
    with tempfile.TemporaryDirectory() as tmp:
        engine = _make_engine(Path(tmp))
        entry = NormalizedEntry(
            url="https://example.com",
            username="alice",
            password="pw",
            sync_status=SyncStatus.CONFLICT,
        )
        engine.db.upsert_entry(entry)

        engine.resolve_conflict(entry.source_key, "keep_source")
        row = engine.db.get_entry_by_source_key(entry.source_key)
        assert row["sync_status"] == "pending"


def test_resolve_conflict_keep_bitwarden():
    with tempfile.TemporaryDirectory() as tmp:
        engine = _make_engine(Path(tmp))
        entry = NormalizedEntry(
            url="https://example.com",
            username="alice",
            password="pw",
            sync_status=SyncStatus.CONFLICT,
        )
        engine.db.upsert_entry(entry)

        engine.resolve_conflict(entry.source_key, "keep_bitwarden")
        row = engine.db.get_entry_by_source_key(entry.source_key)
        assert row["sync_status"] == "synced"


def test_resolve_conflict_skip():
    with tempfile.TemporaryDirectory() as tmp:
        engine = _make_engine(Path(tmp))
        entry = NormalizedEntry(
            url="https://example.com",
            username="alice",
            password="pw",
            sync_status=SyncStatus.CONFLICT,
        )
        engine.db.upsert_entry(entry)

        engine.resolve_conflict(entry.source_key, "skip")
        row = engine.db.get_entry_by_source_key(entry.source_key)
        assert row["sync_status"] == "skipped"


def test_status_returns_counts():
    with tempfile.TemporaryDirectory() as tmp:
        engine = _make_engine(Path(tmp))
        engine.bw = MagicMock()
        engine.bw.test_connection.return_value = False

        for i in range(3):
            entry = NormalizedEntry(
                url=f"https://site{i}.com",
                username="user",
                password="pw",
                sync_status=SyncStatus.PENDING,
            )
            engine.db.upsert_entry(entry)

        status = engine.status()
        assert status["total_entries"] == 3
        assert status["counts"].get("pending", 0) == 3
        assert status["bitwarden_connected"] is False


def test_get_conflicts():
    with tempfile.TemporaryDirectory() as tmp:
        engine = _make_engine(Path(tmp))
        for i in range(2):
            entry = NormalizedEntry(
                url=f"https://conflict{i}.com",
                username="user",
                password="pw",
                sync_status=SyncStatus.CONFLICT,
            )
            engine.db.upsert_entry(entry)

        conflicts = engine.get_conflicts()
        assert len(conflicts) == 2
