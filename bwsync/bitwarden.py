"""Bitwarden REST client — talks to `bw serve` on localhost."""

from __future__ import annotations

import hashlib
import os
from typing import Any, Optional

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore[assignment]

from bwsync.schema import NormalizedEntry


class BitwardenError(Exception):
    """Raised when a Bitwarden API call fails."""


class BitwardenClient:
    """Client for the Bitwarden CLI REST API (`bw serve`).

    Requires `bw serve --port <port>` running in the background
    and BW_SESSION env var set.
    """

    def __init__(
        self,
        host: str = "http://localhost",
        port: int = 8087,
        session_token: str | None = None,
    ):
        self.base_url = f"{host}:{port}"
        self.session_token = session_token or os.environ.get("BW_SESSION", "")
        if httpx is None:
            raise ImportError("httpx is required for BitwardenClient: pip install httpx")
        self.client = httpx.Client(timeout=30.0)

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.session_token:
            headers["Authorization"] = f"Bearer {self.session_token}"
        return headers

    def _request(self, method: str, path: str, **kwargs: Any) -> dict:
        url = f"{self.base_url}{path}"
        resp = self.client.request(method, url, headers=self._headers(), **kwargs)
        if resp.status_code >= 400:
            raise BitwardenError(f"HTTP {resp.status_code}: {resp.text}")
        data = resp.json()
        if not data.get("success", True):
            raise BitwardenError(data.get("message", "Unknown error"))
        return data

    def test_connection(self) -> bool:
        """Test whether `bw serve` is reachable and session is valid."""
        try:
            self._request("GET", "/status")
            return True
        except (httpx.ConnectError, httpx.TimeoutException, BitwardenError):
            return False

    def get_status(self) -> dict:
        """Get Bitwarden vault status."""
        return self._request("GET", "/status")

    def get_vault_items(self) -> list[dict]:
        """Fetch all items from the vault."""
        data = self._request("GET", "/list/object/items")
        return data.get("data", {}).get("data", [])

    def search_items(self, query: str) -> list[dict]:
        """Search vault items by query string."""
        data = self._request("GET", "/list/object/items", params={"search": query})
        return data.get("data", {}).get("data", [])

    def get_item(self, item_id: str) -> dict:
        """Fetch a single vault item by ID."""
        data = self._request("GET", f"/object/item/{item_id}")
        return data.get("data", {})

    def create_item(self, entry: NormalizedEntry) -> dict:
        """Create a new login item in the Bitwarden vault from a NormalizedEntry."""
        payload = {
            "organizationId": None,
            "folderId": None,
            "type": 1,  # Login type
            "name": entry.name or entry.url,
            "notes": entry.notes or "",
            "login": {
                "uris": [{"match": None, "uri": entry.url}],
                "username": entry.username,
                "password": entry.password,
            },
        }
        data = self._request("POST", "/object/item", json=payload)
        return data.get("data", {})

    def update_item(self, item_id: str, entry: NormalizedEntry) -> dict:
        """Update an existing vault item."""
        # Fetch current item to preserve fields we don't manage
        current = self.get_item(item_id)

        current["name"] = entry.name or entry.url
        if "login" not in current:
            current["login"] = {}
        current["login"]["username"] = entry.username
        current["login"]["password"] = entry.password
        current["login"]["uris"] = [{"match": None, "uri": entry.url}]
        if entry.notes:
            current["notes"] = entry.notes

        data = self._request("PUT", f"/object/item/{item_id}", json=current)
        return data.get("data", {})

    def find_matching_item(self, entry: NormalizedEntry) -> Optional[dict]:
        """Find a vault item that matches the given entry by URL + username."""
        # Search by the entry name (domain)
        search_term = entry.name or entry.url
        items = self.search_items(search_term)

        for item in items:
            login = item.get("login", {})
            if not login:
                continue
            # Check username match
            if (login.get("username") or "").lower() != entry.username.lower():
                continue
            # Check URI match
            uris = login.get("uris") or []
            for uri_obj in uris:
                if uri_obj.get("uri", "").lower().rstrip("/") == entry.url.lower().rstrip("/"):
                    return item
        return None

    def password_matches(self, bw_item: dict, entry: NormalizedEntry) -> bool:
        """Check if a Bitwarden item's password matches the entry's password."""
        bw_password = bw_item.get("login", {}).get("password", "")
        if not bw_password and not entry.password:
            return True
        bw_hash = hashlib.sha256(bw_password.encode("utf-8")).hexdigest()
        return bw_hash == entry.password_hash()

    def close(self) -> None:
        self.client.close()
