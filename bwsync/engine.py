"""BWSyncEngine — the core sync pipeline."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from bwsync.bitwarden import BitwardenClient, BitwardenError
from bwsync.config import Config
from bwsync.db import StateStore
from bwsync.schema import AuditLogEntry, NormalizedEntry, SyncResult, SyncStatus
from bwsync.sources.base import BaseSource
from bwsync.sources.chrome import ChromeSource
from bwsync.sources.icloud import ICloudSource

# Registry of all known sources
SOURCE_REGISTRY: dict[str, type[BaseSource]] = {
    "chrome": ChromeSource,
    "icloud": ICloudSource,
}


class BWSyncEngine:
    """Main sync engine — pure logic, no UI dependencies.

    Pipeline: EXTRACT -> NORMALIZE (dedup) -> DIFF -> PUSH -> LOG
    """

    def __init__(
        self,
        db_path: Optional[Path | str] = None,
        config_path: Optional[Path | str] = None,
    ):
        self.config = Config(config_path) if config_path else Config()
        self.db = StateStore(db_path) if db_path else StateStore()

        bw_host = self.config.get("bitwarden.server", "http://localhost")
        bw_port = self.config.get("bitwarden.port", 8087)
        self.bw = BitwardenClient(host=bw_host, port=bw_port)

    def sync(
        self,
        sources: Optional[list[str]] = None,
        dry_run: bool = False,
    ) -> SyncResult:
        """Run the full sync pipeline.

        Args:
            sources: List of source names to sync (None = all enabled).
            dry_run: If True, classify entries but don't push to Bitwarden.

        Returns:
            SyncResult with counts and timing.
        """
        start = time.time()
        result = SyncResult(dry_run=dry_run)

        # 1. EXTRACT
        all_entries = self._extract(sources)
        result.total_extracted = len(all_entries)
        result.sources_used = list({e.source for e in all_entries})

        # 2. NORMALIZE (dedup)
        unique_entries = self._normalize(all_entries)

        # 3. DIFF against DB + Bitwarden
        for entry in unique_entries:
            classification = self._classify_entry(entry)

            if classification == "new":
                entry.sync_status = SyncStatus.PENDING
                result.new_entries += 1
            elif classification == "conflict":
                entry.sync_status = SyncStatus.CONFLICT
                result.conflicts += 1
            elif classification == "synced":
                entry.sync_status = SyncStatus.SYNCED
                result.skipped += 1
                continue  # Don't re-upsert unchanged entries
            elif classification == "error":
                entry.sync_status = SyncStatus.ERROR
                result.errors += 1

            # Persist to state DB
            self.db.upsert_entry(entry)

        # 4. PUSH to Bitwarden (unless dry_run)
        if not dry_run:
            pending = self.db.get_entries_by_status(SyncStatus.PENDING)
            for row in pending:
                try:
                    entry = NormalizedEntry.from_dict(row)
                    # We need the password for pushing — but we only stored the hash.
                    # Find it in our extracted entries.
                    pw_entry = self._find_entry_with_password(entry.source_key, unique_entries)
                    if pw_entry:
                        bw_item = self.bw.create_item(pw_entry)
                        bw_id = bw_item.get("id")
                        self.db.update_sync_status(
                            entry.source_key, SyncStatus.SYNCED, bitwarden_id=bw_id
                        )
                        result.updated_entries += 1
                except BitwardenError:
                    self.db.update_sync_status(entry.source_key, SyncStatus.ERROR)
                    result.errors += 1

        # 5. LOG
        result.duration_seconds = round(time.time() - start, 2)
        self.db.log_sync_run(result)

        return result

    def _extract(self, source_names: Optional[list[str]] = None) -> list[NormalizedEntry]:
        """Run extract() on each requested source."""
        entries: list[NormalizedEntry] = []

        for name, source_cls in SOURCE_REGISTRY.items():
            # Filter to requested sources
            if source_names and name not in source_names:
                continue
            # Check config enable flag
            if not self.config.get(f"sources.{name}.enabled", True):
                continue

            source = source_cls()
            if not source.is_available():
                continue

            try:
                extracted = source.extract()
                entries.extend(extracted)
            except Exception:
                continue

        return entries

    def _normalize(self, entries: list[NormalizedEntry]) -> list[NormalizedEntry]:
        """Dedup entries by source_key, keeping the one with the latest date_last_used."""
        best: dict[str, NormalizedEntry] = {}
        for entry in entries:
            existing = best.get(entry.source_key)
            if existing is None:
                best[entry.source_key] = entry
            else:
                # Keep the entry with the more recent date_last_used
                if (entry.date_last_used or "") > (existing.date_last_used or ""):
                    best[entry.source_key] = entry
        return list(best.values())

    def _classify_entry(self, entry: NormalizedEntry) -> str:
        """Classify an entry: 'new', 'synced', 'conflict', or 'error'.

        Compares against both the local DB and Bitwarden vault.
        """
        # Check local DB first
        db_row = self.db.get_entry_by_source_key(entry.source_key)

        if db_row is None:
            # Never seen before — check if it already exists in Bitwarden
            try:
                bw_item = self.bw.find_matching_item(entry)
                if bw_item:
                    if self.bw.password_matches(bw_item, entry):
                        return "synced"
                    else:
                        return "conflict"
            except (BitwardenError, Exception):
                pass
            return "new"

        # We've seen this entry before
        if db_row["sync_status"] == SyncStatus.SYNCED.value:
            # Check if password changed since last sync
            if db_row["password_hash"] == entry.password_hash():
                return "synced"
            else:
                return "conflict"

        if db_row["sync_status"] == SyncStatus.CONFLICT.value:
            return "conflict"

        return "new"

    @staticmethod
    def _find_entry_with_password(
        source_key: str, entries: list[NormalizedEntry]
    ) -> Optional[NormalizedEntry]:
        """Find an entry in the in-memory list that has the actual password."""
        for e in entries:
            if e.source_key == source_key and e.password:
                return e
        return None

    def get_conflicts(self) -> list[dict]:
        """Return all entries with conflict status."""
        return self.db.get_entries_by_status(SyncStatus.CONFLICT)

    def resolve_conflict(self, source_key: str, resolution: str) -> None:
        """Resolve a conflict.

        Args:
            source_key: The entry's source_key.
            resolution: "keep_source" | "keep_bitwarden" | "skip"
        """
        if resolution == "keep_source":
            self.db.update_sync_status(source_key, SyncStatus.PENDING)
            self.db.log_action(
                "conflict_resolved",
                f"Resolution: keep_source — will push on next sync",
                source_key=source_key,
            )
        elif resolution == "keep_bitwarden":
            self.db.update_sync_status(source_key, SyncStatus.SYNCED)
            self.db.log_action(
                "conflict_resolved",
                "Resolution: keep_bitwarden — marked as synced",
                source_key=source_key,
            )
        elif resolution == "skip":
            self.db.update_sync_status(source_key, SyncStatus.SKIPPED)
            self.db.log_action(
                "conflict_resolved",
                "Resolution: skip — entry will be ignored",
                source_key=source_key,
            )
        else:
            raise ValueError(f"Unknown resolution: {resolution}")

    def status(self) -> dict:
        """Dashboard data — counts by status, BW connection, last run."""
        all_entries = self.db.get_all_entries()
        counts: dict[str, int] = {}
        for entry in all_entries:
            s = entry.get("sync_status", "unknown")
            counts[s] = counts.get(s, 0) + 1

        bw_connected = self.bw.test_connection()

        last_run = None
        audit = self.db.get_audit_log(limit=1)
        if audit:
            last_run = audit[0]

        return {
            "total_entries": len(all_entries),
            "counts": counts,
            "bitwarden_connected": bw_connected,
            "last_run": last_run,
        }

    def get_audit_log(self, limit: int = 50) -> list[dict]:
        """Return recent audit log entries."""
        return self.db.get_audit_log(limit=limit)
