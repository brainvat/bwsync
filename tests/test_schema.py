"""Tests for bwsync.schema."""

from bwsync.schema import AuditLogEntry, NormalizedEntry, SyncResult, SyncStatus


def test_sync_status_values():
    assert SyncStatus.PENDING.value == "pending"
    assert SyncStatus.SYNCED.value == "synced"
    assert SyncStatus.CONFLICT.value == "conflict"
    assert SyncStatus.SKIPPED.value == "skipped"
    assert SyncStatus.ERROR.value == "error"


def test_generate_source_key_deterministic():
    key1 = NormalizedEntry.generate_source_key("https://example.com", "user@test.com")
    key2 = NormalizedEntry.generate_source_key("https://example.com", "user@test.com")
    assert key1 == key2
    assert len(key1) == 64  # SHA-256 hex


def test_generate_source_key_case_insensitive():
    key1 = NormalizedEntry.generate_source_key("https://Example.COM/", "User@Test.com")
    key2 = NormalizedEntry.generate_source_key("https://example.com", "user@test.com")
    assert key1 == key2


def test_generate_source_key_different_inputs():
    key1 = NormalizedEntry.generate_source_key("https://example.com", "alice")
    key2 = NormalizedEntry.generate_source_key("https://example.com", "bob")
    assert key1 != key2


def test_normalized_entry_source_key_auto_generated():
    entry = NormalizedEntry(url="https://example.com", username="alice")
    assert entry.source_key != ""
    assert len(entry.source_key) == 64


def test_password_hash():
    entry = NormalizedEntry(url="https://example.com", username="alice", password="secret123")
    h = entry.password_hash()
    assert len(h) == 64
    assert "secret123" not in h


def test_password_hash_empty():
    entry = NormalizedEntry(url="https://example.com", username="alice", password="")
    assert entry.password_hash() == ""


def test_to_dict_excludes_password_by_default():
    entry = NormalizedEntry(
        url="https://example.com",
        username="alice",
        password="secret123",
        source="chrome",
    )
    d = entry.to_dict()
    assert "password" not in d
    assert d["password_hash"] != ""
    assert d["url"] == "https://example.com"
    assert d["source"] == "chrome"


def test_to_dict_includes_password_when_requested():
    entry = NormalizedEntry(
        url="https://example.com",
        username="alice",
        password="secret123",
    )
    d = entry.to_dict(include_password=True)
    assert d["password"] == "secret123"


def test_from_dict_roundtrip():
    entry = NormalizedEntry(
        url="https://example.com",
        username="alice",
        password="secret123",
        source="chrome",
        source_profile="Default",
        name="example.com",
        date_created="2024-01-01",
        date_last_used="2024-06-15",
        times_used=42,
        sync_status=SyncStatus.SYNCED,
    )
    d = entry.to_dict(include_password=True)
    restored = NormalizedEntry.from_dict(d, password=d["password"])
    assert restored.url == entry.url
    assert restored.username == entry.username
    assert restored.password == entry.password
    assert restored.source == entry.source
    assert restored.sync_status == SyncStatus.SYNCED
    assert restored.source_key == entry.source_key


def test_sync_result_to_dict():
    result = SyncResult(
        sources_used=["chrome", "icloud"],
        total_extracted=100,
        new_entries=50,
        conflicts=5,
    )
    d = result.to_dict()
    assert d["sources_used"] == "chrome,icloud"
    assert d["total_extracted"] == 100
    assert d["new_entries"] == 50


def test_audit_log_entry_to_dict():
    entry = AuditLogEntry(action="sync_run", details="Completed successfully")
    d = entry.to_dict()
    assert d["action"] == "sync_run"
    assert d["details"] == "Completed successfully"
    assert d["timestamp"] != ""
