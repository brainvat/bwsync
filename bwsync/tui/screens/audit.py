"""Audit log screen for the bwsync TUI."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Label

from bwsync.engine import BWSyncEngine


class AuditScreen(Screen):
    """Scrollable audit log timeline."""

    def compose(self) -> ComposeResult:
        yield Header()
        with Container():
            yield Label(" Audit Log ", id="header-bar")
            yield DataTable(id="audit-table")
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_log()

    def refresh_log(self) -> None:
        table = self.query_one("#audit-table", DataTable)
        table.clear(columns=True)
        table.add_columns("Timestamp", "Action", "Details")

        try:
            engine = BWSyncEngine()
            entries = engine.get_audit_log(limit=100)
        except Exception:
            entries = []

        for entry in entries:
            table.add_row(
                entry.get("timestamp", ""),
                entry.get("action", ""),
                entry.get("details", "")[:80],
            )
