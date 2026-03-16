"""Chrome password source — extracts credentials from all Chrome profiles on macOS."""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from bwsync.schema import NormalizedEntry, SyncStatus
from bwsync.sources.base import BaseSource

# Lazy import — pycryptodome may not be installed in test environments
_AES = None
_PBKDF2 = None
_SHA1 = None
_CryptoHMAC = None


def _ensure_crypto():
    global _AES, _PBKDF2, _SHA1, _CryptoHMAC
    if _AES is None:
        from Crypto.Cipher import AES
        from Crypto.Hash import SHA1
        from Crypto.Hash import HMAC as CryptoHMAC
        from Crypto.Protocol.KDF import PBKDF2

        _AES = AES
        _PBKDF2 = PBKDF2
        _SHA1 = SHA1
        _CryptoHMAC = CryptoHMAC


CHROME_BASE = Path.home() / "Library" / "Application Support" / "Google" / "Chrome"


def _get_chrome_safe_storage_key() -> str:
    """Retrieve Chrome Safe Storage password from macOS Keychain."""
    candidates = [
        ("Chrome", "Chrome Safe Storage"),
        ("Chromium", "Chromium Safe Storage"),
        ("Chrome", "Google Chrome Safe Storage"),
        ("Chrome", "Chrome"),
    ]
    for account, service in candidates:
        result = subprocess.run(
            ["security", "find-generic-password", "-a", account, "-s", service, "-w"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    raise RuntimeError("Could not retrieve Chrome Safe Storage key from Keychain.")


def _derive_aes_key(raw_key: str) -> bytes:
    """Derive 16-byte AES key from Chrome Safe Storage password via PBKDF2."""
    _ensure_crypto()
    return _PBKDF2(
        raw_key.encode("utf-8"),
        b"saltysalt",
        dkLen=16,
        count=1003,
        prf=lambda p, s: _CryptoHMAC.new(p, s, _SHA1).digest(),
    )


def _decrypt_password(encrypted_value: bytes, aes_key: bytes) -> str:
    """Decrypt a Chrome-encrypted password blob (v10 = AES-CBC on macOS)."""
    _ensure_crypto()
    if not encrypted_value:
        return ""
    if encrypted_value[:3] == b"v10":
        payload = encrypted_value[3:]
        iv = b" " * 16
        try:
            cipher = _AES.new(aes_key, _AES.MODE_CBC, IV=iv)
            decrypted = cipher.decrypt(payload)
            padding_len = decrypted[-1] if isinstance(decrypted[-1], int) else ord(decrypted[-1])
            return decrypted[:-padding_len].decode("utf-8", errors="replace")
        except Exception:
            return "[decryption failed]"
    try:
        return encrypted_value.decode("utf-8", errors="replace")
    except Exception:
        return "[unreadable]"


def _chrome_date_to_iso(ts: int) -> str:
    """Convert Chrome timestamp (microseconds since 1601-01-01) to ISO date string."""
    if not ts:
        return ""
    try:
        unix_ts = (ts / 1_000_000) - 11644473600
        return datetime.fromtimestamp(unix_ts, tz=timezone.utc).strftime("%Y-%m-%d")
    except Exception:
        return ""


def _derive_name_from_url(url: str) -> str:
    """Extract a human-readable name from a URL (e.g. 'github.com')."""
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        # Strip www. prefix
        host = re.sub(r"^www\.", "", host)
        return host
    except Exception:
        return ""


def _find_chrome_profiles() -> list[tuple[str, Path]]:
    """Find all Chrome profiles that have a Login Data file."""
    if not CHROME_BASE.exists():
        return []
    candidate_dirs = [CHROME_BASE / "Default"] + sorted(CHROME_BASE.glob("Profile *"))
    profiles = []
    for profile_dir in candidate_dirs:
        login_data = profile_dir / "Login Data"
        if not login_data.exists():
            continue
        display_name = profile_dir.name
        prefs_path = profile_dir / "Preferences"
        if prefs_path.exists():
            try:
                with open(prefs_path, "r", encoding="utf-8") as f:
                    prefs = json.load(f)
                display_name = prefs.get("profile", {}).get("name", display_name)
            except Exception:
                pass
        profiles.append((display_name, profile_dir))
    return profiles


def _extract_from_profile(
    profile_name: str, profile_dir: Path, aes_key: bytes
) -> list[NormalizedEntry]:
    """Extract and decrypt all logins from a single Chrome profile."""
    login_data_src = profile_dir / "Login Data"
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".db", prefix="chrome_ld_")
    os.close(tmp_fd)

    try:
        shutil.copy2(login_data_src, tmp_path)
        conn = sqlite3.connect(tmp_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT origin_url, action_url, username_value, password_value,
                   date_created, date_last_used, times_used
            FROM logins ORDER BY origin_url ASC
        """)
        rows = cursor.fetchall()
        conn.close()

        entries = []
        for origin_url, action_url, username, enc_password, date_created, date_last_used, times_used in rows:
            url = origin_url or action_url or ""
            password = _decrypt_password(enc_password, aes_key)
            entries.append(
                NormalizedEntry(
                    url=url,
                    username=username or "",
                    password=password,
                    source="chrome",
                    source_profile=profile_name,
                    name=_derive_name_from_url(url),
                    date_created=_chrome_date_to_iso(date_created),
                    date_last_used=_chrome_date_to_iso(date_last_used),
                    times_used=times_used or 0,
                    sync_status=SyncStatus.PENDING,
                )
            )
        return entries
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


class ChromeSource(BaseSource):
    """Extract passwords from all Chrome profiles on macOS."""

    name = "chrome"

    def is_available(self) -> bool:
        return CHROME_BASE.exists()

    def extract(self) -> list[NormalizedEntry]:
        raw_key = _get_chrome_safe_storage_key()
        aes_key = _derive_aes_key(raw_key)
        profiles = _find_chrome_profiles()

        all_entries: list[NormalizedEntry] = []
        for profile_name, profile_dir in profiles:
            try:
                entries = _extract_from_profile(profile_name, profile_dir, aes_key)
                all_entries.extend(entries)
            except Exception:
                continue

        return all_entries
