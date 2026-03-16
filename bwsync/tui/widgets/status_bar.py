"""Status bar widget for the bwsync TUI."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import Label, Static


class StatusBar(Static):
    """Bottom status bar showing connection state and last sync info."""

    def __init__(self) -> None:
        super().__init__()
        self._message = ""

    def compose(self) -> ComposeResult:
        yield Label("", id="status-message")

    def set_message(self, message: str) -> None:
        self._message = message
        self.query_one("#status-message", Label).update(message)
