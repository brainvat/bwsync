"""Conflicts review screen for the bwsync TUI."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Label, Static

from bwsync.engine import BWSyncEngine


class ConflictDetail(Static):
    """Side panel showing conflict details."""

    def __init__(self) -> None:
        super().__init__()
        self._conflict: dict | None = None

    def compose(self) -> ComposeResult:
        yield Label("Select a conflict to view details", id="conflict-info")

    def show_conflict(self, conflict: dict) -> None:
        self._conflict = conflict
        info = self.query_one("#conflict-info", Label)
        info.update(
            f"URL: {conflict['url']}\n"
            f"Username: {conflict['username']}\n"
            f"Source: {conflict['source']} / {conflict['source_profile']}\n"
            f"Password hash: {conflict['password_hash'][:16]}...\n\n"
            f"Press [K] keep source, [B] keep bitwarden, [S] skip"
        )


class ConflictsScreen(Screen):
    """Interactive conflict review screen."""

    BINDINGS = [
        ("k", "resolve_keep_source", "Keep Source"),
        ("b", "resolve_keep_bitwarden", "Keep BW"),
        ("s", "resolve_skip", "Skip"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        with Container():
            yield Label(" Conflict Review ", id="header-bar")
            yield DataTable(id="conflicts-table")
            with Vertical(classes="conflict-detail"):
                yield ConflictDetail()
        yield Footer()

    def on_mount(self) -> None:
        self._conflicts: list[dict] = []
        self._selected_key: str | None = None
        self.refresh_conflicts()

    def refresh_conflicts(self) -> None:
        table = self.query_one("#conflicts-table", DataTable)
        table.clear(columns=True)
        table.add_columns("URL", "Username", "Source", "Source Key")

        try:
            engine = BWSyncEngine()
            self._conflicts = engine.get_conflicts()
        except Exception:
            self._conflicts = []

        for c in self._conflicts:
            table.add_row(
                c["url"],
                c["username"],
                c["source"],
                c["source_key"][:12] + "...",
                key=c["source_key"],
            )

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self._selected_key = str(event.row_key.value)
        conflict = next((c for c in self._conflicts if c["source_key"] == self._selected_key), None)
        if conflict:
            detail = self.query_one(ConflictDetail)
            detail.show_conflict(conflict)

    def _resolve(self, resolution: str) -> None:
        if not self._selected_key:
            return
        try:
            engine = BWSyncEngine()
            engine.resolve_conflict(self._selected_key, resolution)
            self.refresh_conflicts()
        except Exception:
            pass

    def action_resolve_keep_source(self) -> None:
        self._resolve("keep_source")

    def action_resolve_keep_bitwarden(self) -> None:
        self._resolve("keep_bitwarden")

    def action_resolve_skip(self) -> None:
        self._resolve("skip")
