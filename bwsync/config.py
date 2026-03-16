"""Configuration management for bwsync."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "bwsync" / "config.json"

DEFAULT_CONFIG = {
    "bitwarden": {
        "server": "http://localhost",
        "port": 8087,
    },
    "sources": {
        "chrome": {"enabled": True},
        "icloud": {"enabled": True},
        "gpm": {"enabled": False},
    },
    "sync": {
        "conflict_strategy": "prompt",  # "prompt", "keep_source", "keep_bitwarden", "skip"
        "dedup_strategy": "latest",  # "latest" (by date_last_used), "first"
    },
    "backup": {
        "excel_password_env": "BWSYNC_EXCEL_PASSWORD",
        "backup_dir": str(Path.home() / "Documents" / "bwsync"),
    },
}


class Config:
    """JSON-based configuration with dotted-path access."""

    def __init__(self, config_path: Path | str = DEFAULT_CONFIG_PATH):
        self.config_path = Path(config_path)
        self._data: dict = {}
        self.load()

    def load(self) -> None:
        """Load config from disk, merging with defaults for missing keys."""
        if self.config_path.exists():
            with open(self.config_path, "r", encoding="utf-8") as f:
                self._data = json.load(f)
        else:
            self._data = {}
        self._data = self._merge_defaults(DEFAULT_CONFIG, self._data)

    @staticmethod
    def _merge_defaults(defaults: dict, overrides: dict) -> dict:
        """Deep merge: defaults are filled in where overrides are missing."""
        result = dict(defaults)
        for key, value in overrides.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = Config._merge_defaults(result[key], value)
            else:
                result[key] = value
        return result

    def get(self, dotted_path: str, default: Any = None) -> Any:
        """Get a config value by dotted path, e.g. 'bitwarden.port'."""
        keys = dotted_path.split(".")
        node = self._data
        for key in keys:
            if isinstance(node, dict) and key in node:
                node = node[key]
            else:
                return default
        return node

    def set(self, dotted_path: str, value: Any) -> None:
        """Set a config value by dotted path."""
        keys = dotted_path.split(".")
        node = self._data
        for key in keys[:-1]:
            if key not in node or not isinstance(node[key], dict):
                node[key] = {}
            node = node[key]
        node[keys[-1]] = value

    def save(self) -> None:
        """Persist config to disk."""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2)
        try:
            os.chmod(self.config_path, 0o600)
        except OSError:
            pass

    @property
    def data(self) -> dict:
        return self._data
