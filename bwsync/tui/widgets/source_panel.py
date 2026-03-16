"""Source panel widget for the bwsync TUI."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Label, Static

from bwsync.engine import SOURCE_REGISTRY


class SourcePanel(Static):
    """Panel showing available password sources and their status."""

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Password Sources", classes="status-card-title")
            for name, source_cls in SOURCE_REGISTRY.items():
                source = source_cls()
                available = source.is_available()
                status = "Available" if available else "Not found"
                style = "green" if available else "red"
                yield Label(f"  [{style}]{name}: {status}[/]")
