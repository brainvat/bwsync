"""Tests for bwsync.db."""

import tempfile
from pathlib import Path

from bwsync.db import StateStore
from bwsync.schema import NormalizedEntry, SyncResult, SyncStatus


def make_store() -> StateStore:
    """Create a StateStore backed by a temp file."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    return StateStore(db_path=Path(tmp.name))


def test_init_creates_tables():
    store = make_store()
    tables = store.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    table_names = {r["name"] for r in tables}
    assert "entries" in table_names
    assert "audit_log" in table_names
    assert "config" in table_names
    store.close()


def test_upsert_and_get_entry():
    store = make_store()
    entry = NormalizedEntry(
        url="https://example.com",
        username="alice",
        password="secret123",
        source="chrome",
        source_profile="Default",
    )
    store.upsert_entry(entry)

    row = store.get_entry_by_source_key(entry.source_key)
    assert row is not None
    assert row["url"] == "https://example.com"
    assert row["username"] == "alice"
    assert row["password_hash"] == entry.password_hash()
    assert row["source"] == "chrome"
    # Password itself must NOT be in the row
    assert "secret123" not in str(row.values())
    store.close()


def test_upsert_updates_existing():
    store = make_store()
    entry = NormalizedEntry(
        url="https://example.com",
        username="alice",
        password="old_pass",
        source="chrome",
    )
    store.upsert_entry(entry)

    entry.password = "new_pass"
    entry.times_used = 10
    store.upsert_entry(entry)

    row = store.get_entry_by_source_key(entry.source_key)
    assert row["times_used"] == 10
    assert row["password_hash"] == entry.password_hash()
    # Should still be just one row
    all_entries = store.get_all_entries()
    assert len(all_entries) == 1
    store.close()


def test_get_entries_by_status():
    store = make_store()
    for i in range(5):
        entry = NormalizedEntry(
            url=f"https://site{i}.com",
            username="user",
            source="chrome",
            sync_status=SyncStatus.PENDING if i < 3 else SyncStatus.SYNCED,
        )
        store.upsert_entry(entry)

    pending = store.get_entries_by_status(SyncStatus.PENDING)
    synced = store.get_entries_by_status(SyncStatus.SYNCED)
    assert len(pending) == 3
    assert len(synced) == 2
    store.close()


def test_update_sync_status():
    store = make_store()
    entry = NormalizedEntry(url="https://example.com", username="alice", source="chrome")
    store.upsert_entry(entry)

    store.update_sync_status(entry.source_key, SyncStatus.SYNCED, bitwarden_id="bw-123")
    row = store.get_entry_by_source_key(entry.source_key)
    assert row["sync_status"] == "synced"
    assert row["bitwarden_id"] == "bw-123"
    store.close()


def test_get_nonexistent_entry():
    store = make_store()
    assert store.get_entry_by_source_key("nonexistent") is None
    store.close()


def test_log_sync_run():
    store = make_store()
    result = SyncResult(
        sources_used=["chrome"],
        total_extracted=50,
        new_entries=30,
        conflicts=2,
    )
    store.log_sync_run(result)

    log = store.get_audit_log(limit=1)
    assert len(log) == 1
    assert log[0]["action"] == "sync_run"
    assert log[0]["sync_result"]["total_extracted"] == 50
    store.close()


def test_log_action():
    store = make_store()
    store.log_action("conflict_resolved", "Kept source version", source_key="abc123")

    log = store.get_audit_log(limit=1)
    assert len(log) == 1
    assert log[0]["action"] == "conflict_resolved"
    assert log[0]["source_key"] == "abc123"
    store.close()


def test_get_all_entries():
    store = make_store()
    for i in range(3):
        entry = NormalizedEntry(
            url=f"https://site{i}.com", username="user", source="chrome"
        )
        store.upsert_entry(entry)

    all_entries = store.get_all_entries()
    assert len(all_entries) == 3
    store.close()
