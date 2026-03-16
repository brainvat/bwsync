"""Core data structures for bwsync."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class SyncStatus(str, Enum):
    """Status of an entry in the sync pipeline."""

    PENDING = "pending"
    SYNCED = "synced"
    CONFLICT = "conflict"
    SKIPPED = "skipped"
    ERROR = "error"


@dataclass
class NormalizedEntry:
    """A single credential entry, normalized across all sources."""

    url: str
    username: str
    password: str = ""
    source: str = ""  # "chrome", "icloud", "gpm"
    source_profile: str = ""  # e.g. "Profile 1", "login.keychain"
    name: str = ""  # human-readable label (e.g. domain name)
    notes: str = ""
    date_created: str = ""  # ISO date
    date_last_used: str = ""  # ISO date
    times_used: int = 0
    sync_status: SyncStatus = SyncStatus.PENDING
    bitwarden_id: Optional[str] = None
    source_key: str = field(default="", init=False)

    def __post_init__(self):
        self.source_key = self.generate_source_key(self.url, self.username)

    @staticmethod
    def generate_source_key(url: str, username: str) -> str:
        """SHA-256 hash of normalized url+username for dedup."""
        normalized = f"{url.lower().rstrip('/')}|{username.lower()}"
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def password_hash(self) -> str:
        """SHA-256 of the password (for DB storage — never store plaintext)."""
        if not self.password:
            return ""
        return hashlib.sha256(self.password.encode("utf-8")).hexdigest()

    def to_dict(self, include_password: bool = False) -> dict:
        """Serialize to dict. Excludes password by default, stores hash instead."""
        d = {
            "source_key": self.source_key,
            "url": self.url,
            "username": self.username,
            "source": self.source,
            "source_profile": self.source_profile,
            "name": self.name,
            "notes": self.notes,
            "date_created": self.date_created,
            "date_last_used": self.date_last_used,
            "times_used": self.times_used,
            "sync_status": self.sync_status.value,
            "bitwarden_id": self.bitwarden_id,
            "password_hash": self.password_hash(),
        }
        if include_password:
            d["password"] = self.password
        return d

    @classmethod
    def from_dict(cls, d: dict, password: str = "") -> NormalizedEntry:
        """Reconstruct from a DB row or dict."""
        entry = cls(
            url=d.get("url", ""),
            username=d.get("username", ""),
            password=password,
            source=d.get("source", ""),
            source_profile=d.get("source_profile", ""),
            name=d.get("name", ""),
            notes=d.get("notes", ""),
            date_created=d.get("date_created", ""),
            date_last_used=d.get("date_last_used", ""),
            times_used=d.get("times_used", 0),
            sync_status=SyncStatus(d.get("sync_status", "pending")),
            bitwarden_id=d.get("bitwarden_id"),
        )
        return entry


@dataclass
class SyncResult:
    """Summary of a sync run."""

    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    sources_used: list[str] = field(default_factory=list)
    total_extracted: int = 0
    new_entries: int = 0
    updated_entries: int = 0
    conflicts: int = 0
    errors: int = 0
    skipped: int = 0
    dry_run: bool = False
    duration_seconds: float = 0.0

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "sources_used": ",".join(self.sources_used),
            "total_extracted": self.total_extracted,
            "new_entries": self.new_entries,
            "updated_entries": self.updated_entries,
            "conflicts": self.conflicts,
            "errors": self.errors,
            "skipped": self.skipped,
            "dry_run": self.dry_run,
            "duration_seconds": self.duration_seconds,
        }


@dataclass
class AuditLogEntry:
    """A single audit log record."""

    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    action: str = ""  # "sync_run", "conflict_resolved", "entry_created", "error"
    details: str = ""
    source_key: Optional[str] = None
    sync_result: Optional[dict] = None

    def to_dict(self) -> dict:
        import json

        return {
            "timestamp": self.timestamp,
            "action": self.action,
            "details": self.details,
            "source_key": self.source_key or "",
            "sync_result_json": json.dumps(self.sync_result) if self.sync_result else "",
        }
