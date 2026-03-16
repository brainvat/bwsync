"""SQLite state store for bwsync."""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Optional

from bwsync.schema import AuditLogEntry, NormalizedEntry, SyncResult, SyncStatus

DEFAULT_DB_PATH = Path.home() / ".config" / "bwsync" / "state.db"


class StateStore:
    """Plain SQLite state store. Passwords are never stored — only hashes."""

    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.init_db()
        # Secure the DB file
        try:
            os.chmod(self.db_path, 0o600)
        except OSError:
            pass

    def init_db(self) -> None:
        """Create tables if they don't exist."""
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS entries (
                source_key TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                username TEXT NOT NULL,
                password_hash TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT '',
                source_profile TEXT NOT NULL DEFAULT '',
                name TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT '',
                date_created TEXT NOT NULL DEFAULT '',
                date_last_used TEXT NOT NULL DEFAULT '',
                times_used INTEGER NOT NULL DEFAULT 0,
                sync_status TEXT NOT NULL DEFAULT 'pending',
                bitwarden_id TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL DEFAULT (datetime('now')),
                action TEXT NOT NULL,
                details TEXT NOT NULL DEFAULT '',
                source_key TEXT NOT NULL DEFAULT '',
                sync_result_json TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)
        self.conn.commit()

    def upsert_entry(self, entry: NormalizedEntry) -> None:
        """Insert or update an entry. Never stores the password — only the hash."""
        self.conn.execute(
            """
            INSERT INTO entries (
                source_key, url, username, password_hash, source, source_profile,
                name, notes, date_created, date_last_used, times_used,
                sync_status, bitwarden_id, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(source_key) DO UPDATE SET
                url = excluded.url,
                username = excluded.username,
                password_hash = excluded.password_hash,
                source = excluded.source,
                source_profile = excluded.source_profile,
                name = excluded.name,
                notes = excluded.notes,
                date_created = excluded.date_created,
                date_last_used = excluded.date_last_used,
                times_used = excluded.times_used,
                sync_status = excluded.sync_status,
                bitwarden_id = excluded.bitwarden_id,
                updated_at = datetime('now')
            """,
            (
                entry.source_key,
                entry.url,
                entry.username,
                entry.password_hash(),
                entry.source,
                entry.source_profile,
                entry.name,
                entry.notes,
                entry.date_created,
                entry.date_last_used,
                entry.times_used,
                entry.sync_status.value,
                entry.bitwarden_id,
            ),
        )
        self.conn.commit()

    def get_entry_by_source_key(self, source_key: str) -> Optional[dict]:
        """Fetch a single entry by source_key. Returns dict or None."""
        row = self.conn.execute(
            "SELECT * FROM entries WHERE source_key = ?", (source_key,)
        ).fetchone()
        return dict(row) if row else None

    def get_entries_by_status(self, status: SyncStatus) -> list[dict]:
        """Fetch all entries with a given sync status."""
        rows = self.conn.execute(
            "SELECT * FROM entries WHERE sync_status = ? ORDER BY url",
            (status.value,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_all_entries(self) -> list[dict]:
        """Fetch all entries."""
        rows = self.conn.execute(
            "SELECT * FROM entries ORDER BY url"
        ).fetchall()
        return [dict(r) for r in rows]

    def update_sync_status(
        self, source_key: str, status: SyncStatus, bitwarden_id: Optional[str] = None
    ) -> None:
        """Update the sync status (and optionally bitwarden_id) of an entry."""
        if bitwarden_id is not None:
            self.conn.execute(
                """UPDATE entries
                   SET sync_status = ?, bitwarden_id = ?, updated_at = datetime('now')
                   WHERE source_key = ?""",
                (status.value, bitwarden_id, source_key),
            )
        else:
            self.conn.execute(
                """UPDATE entries
                   SET sync_status = ?, updated_at = datetime('now')
                   WHERE source_key = ?""",
                (status.value, source_key),
            )
        self.conn.commit()

    def log_sync_run(self, result: SyncResult) -> None:
        """Write a sync run record to the audit log."""
        entry = AuditLogEntry(
            action="sync_run",
            details=f"Extracted {result.total_extracted}, new {result.new_entries}, "
            f"conflicts {result.conflicts}, errors {result.errors}",
            sync_result=result.to_dict(),
        )
        self._write_audit_log(entry)

    def log_action(self, action: str, details: str, source_key: str = "") -> None:
        """Write an arbitrary action to the audit log."""
        entry = AuditLogEntry(action=action, details=details, source_key=source_key)
        self._write_audit_log(entry)

    def _write_audit_log(self, entry: AuditLogEntry) -> None:
        d = entry.to_dict()
        self.conn.execute(
            """INSERT INTO audit_log (timestamp, action, details, source_key, sync_result_json)
               VALUES (?, ?, ?, ?, ?)""",
            (d["timestamp"], d["action"], d["details"], d["source_key"], d["sync_result_json"]),
        )
        self.conn.commit()

    def get_audit_log(self, limit: int = 50) -> list[dict]:
        """Fetch recent audit log entries."""
        rows = self.conn.execute(
            "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        results = []
        for row in rows:
            d = dict(row)
            if d.get("sync_result_json"):
                try:
                    d["sync_result"] = json.loads(d["sync_result_json"])
                except json.JSONDecodeError:
                    d["sync_result"] = None
            else:
                d["sync_result"] = None
            results.append(d)
        return results

    def close(self) -> None:
        self.conn.close()
