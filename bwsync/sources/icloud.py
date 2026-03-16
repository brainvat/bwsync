"""iCloud Keychain password source — extracts internet passwords via macOS security CLI."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass

from bwsync.schema import NormalizedEntry, SyncStatus
from bwsync.sources.base import BaseSource

KEYCHAIN_PATH = "login.keychain-db"


@dataclass
class _KeychainItem:
    """Parsed fields from a single keychain internet password entry."""

    server: str = ""
    account: str = ""
    protocol: str = ""
    path: str = ""
    port: str = ""
    auth_type: str = ""


def _parse_keychain_dump(output: str) -> list[_KeychainItem]:
    """Parse output of `security dump-keychain` for internet password items (class=inet)."""
    items: list[_KeychainItem] = []
    current: _KeychainItem | None = None
    in_inet_block = False

    for line in output.splitlines():
        # Start of any new class block — save previous inet block first
        if "class:" in line:
            if current and in_inet_block:
                items.append(current)
            if '"inet"' in line:
                current = _KeychainItem()
                in_inet_block = True
            else:
                current = None
                in_inet_block = False
            continue

        if not in_inet_block or current is None:
            continue

        # Parse attribute lines like:    "srvr"<blob>="github.com"
        # or:    0x00000007 <blob>="server name"
        attr_match = re.match(r'\s+"(\w+)"<\w+>="(.+)"', line)
        if attr_match:
            key, value = attr_match.group(1), attr_match.group(2)
            if key == "srvr":
                current.server = value
            elif key == "acct":
                current.account = value
            elif key == "ptcl":
                current.protocol = value
            elif key == "path":
                current.path = value
            elif key == "port":
                current.port = value
            elif key == "atyp":
                current.auth_type = value

    # Don't forget the last block
    if current and in_inet_block:
        items.append(current)

    return items


def _protocol_to_scheme(protocol: str) -> str:
    """Map keychain protocol codes to URL schemes."""
    mapping = {
        "htps": "https",
        "http": "http",
        "ftp ": "ftp",
        "ftps": "ftps",
        "smtp": "smtp",
        "imap": "imap",
        "pop3": "pop3",
    }
    return mapping.get(protocol.strip(), "https")


def _build_url(item: _KeychainItem) -> str:
    """Construct a URL from keychain item fields."""
    scheme = _protocol_to_scheme(item.protocol)
    url = f"{scheme}://{item.server}"
    if item.port and item.port != "0":
        url += f":{item.port}"
    if item.path and item.path != "/":
        url += item.path
    return url


def _get_password(server: str, account: str) -> str:
    """Retrieve the actual password for a specific keychain entry.

    This will trigger a macOS Keychain access prompt on first run.
    """
    result = subprocess.run(
        ["security", "find-internet-password", "-s", server, "-a", account, "-w"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return result.stdout.strip()
    return ""


class ICloudSource(BaseSource):
    """Extract internet passwords from macOS login keychain."""

    name = "icloud"

    def is_available(self) -> bool:
        """Check if login.keychain-db is accessible."""
        result = subprocess.run(
            ["security", "list-keychains"],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0

    def extract(self) -> list[NormalizedEntry]:
        """Dump the login keychain, parse internet passwords, and retrieve each password.

        Note: This will trigger macOS Keychain access prompts.
        """
        result = subprocess.run(
            ["security", "dump-keychain", KEYCHAIN_PATH],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Failed to dump keychain: {result.stderr.strip()}")

        items = _parse_keychain_dump(result.stdout)

        entries: list[NormalizedEntry] = []
        seen_keys: set[str] = set()

        for item in items:
            if not item.server or not item.account:
                continue

            # Dedup within this source
            dedup_key = f"{item.server}|{item.account}"
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)

            url = _build_url(item)
            password = _get_password(item.server, item.account)

            # Derive name from server
            name = re.sub(r"^www\.", "", item.server)

            entries.append(
                NormalizedEntry(
                    url=url,
                    username=item.account,
                    password=password,
                    source="icloud",
                    source_profile="login.keychain",
                    name=name,
                    sync_status=SyncStatus.PENDING,
                )
            )

        return entries
