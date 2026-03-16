"""Dashboard screen for the bwsync TUI."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Label, Static

from bwsync.engine import BWSyncEngine


class StatusCard(Static):
    """A status card widget showing a metric."""

    def __init__(self, title: str, value: str, style_class: str = "") -> None:
        super().__init__()
        self._title = title
        self._value = value
        if style_class:
            self.add_class(style_class)

    def compose(self) -> ComposeResult:
        yield Label(self._title, classes="count-label")
        yield Label(self._value, classes="count-value")

    def update_value(self, value: str) -> None:
        self._value = value
        labels = self.query(Label)
        label_list = list(labels)
        if len(label_list) > 1:
            label_list[1].update(value)


class DashboardScreen(Screen):
    """Main dashboard showing sync status overview."""

    BINDINGS = [
        ("s", "run_sync", "Sync (dry-run)"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        with Container():
            yield Label(" bwsync Dashboard ", id="header-bar")
            with Horizontal():
                with Vertical(classes="status-card"):
                    yield Label("Total Entries", classes="status-card-title")
                    yield Label("--", id="total-entries", classes="count-value")
                with Vertical(classes="status-card"):
                    yield Label("Pending", classes="status-card-title")
                    yield Label("--", id="pending-count", classes="count-value")
                with Vertical(classes="status-card"):
                    yield Label("Synced", classes="status-card-title")
                    yield Label("--", id="synced-count", classes="count-value")
                with Vertical(classes="status-card"):
                    yield Label("Conflicts", classes="status-card-title")
                    yield Label("--", id="conflict-count", classes="count-value")
            with Horizontal():
                with Vertical(classes="status-card"):
                    yield Label("Bitwarden", classes="status-card-title")
                    yield Label("--", id="bw-status", classes="count-value")
                with Vertical(classes="status-card"):
                    yield Label("Last Run", classes="status-card-title")
                    yield Label("--", id="last-run", classes="count-value")
                with Vertical(classes="status-card"):
                    yield Label("Errors", classes="status-card-title")
                    yield Label("--", id="error-count", classes="count-value")
            yield Label("", id="sync-status")
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_dashboard()

    def refresh_dashboard(self) -> None:
        try:
            engine = BWSyncEngine()
            data = engine.status()

            self.query_one("#total-entries", Label).update(str(data["total_entries"]))
            counts = data["counts"]
            self.query_one("#pending-count", Label).update(str(counts.get("pending", 0)))
            self.query_one("#synced-count", Label).update(str(counts.get("synced", 0)))
            self.query_one("#conflict-count", Label).update(str(counts.get("conflict", 0)))
            self.query_one("#error-count", Label).update(str(counts.get("error", 0)))

            bw_text = "Connected" if data["bitwarden_connected"] else "Not connected"
            self.query_one("#bw-status", Label).update(bw_text)

            if data["last_run"]:
                self.query_one("#last-run", Label).update(
                    data["last_run"].get("timestamp", "unknown")
                )
        except Exception as e:
            self.query_one("#sync-status", Label).update(f"Error: {e}")

    def action_run_sync(self) -> None:
        self.run_sync()

    def run_sync(self) -> None:
        status_label = self.query_one("#sync-status", Label)
        status_label.update("Syncing (dry-run)...")
        try:
            engine = BWSyncEngine()
            result = engine.sync(dry_run=True)
            status_label.update(
                f"Sync complete: {result.total_extracted} extracted, "
                f"{result.new_entries} new, {result.conflicts} conflicts"
            )
            self.refresh_dashboard()
        except Exception as e:
            status_label.update(f"Sync error: {e}")
