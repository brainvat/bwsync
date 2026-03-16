"""Main Textual TUI application for bwsync."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding

from bwsync.tui.screens.audit import AuditScreen
from bwsync.tui.screens.conflicts import ConflictsScreen
from bwsync.tui.screens.dashboard import DashboardScreen


class BWsyncApp(App):
    """Interactive terminal UI for bwsync."""

    TITLE = "bwsync"
    SUB_TITLE = "Password Consolidation Engine"
    CSS = """
    Screen {
        background: $surface;
    }

    #header-bar {
        dock: top;
        height: 1;
        background: $accent;
        color: $text;
        text-align: center;
    }

    .status-card {
        border: solid $primary;
        padding: 1 2;
        margin: 1;
        height: auto;
    }

    .status-card-title {
        text-style: bold;
        color: $accent;
    }

    .count-label {
        color: $text-muted;
    }

    .count-value {
        color: $text;
        text-style: bold;
    }

    DataTable {
        height: 1fr;
    }

    .conflict-detail {
        border: solid $warning;
        padding: 1 2;
        margin: 1;
    }

    Footer {
        background: $panel;
    }
    """

    BINDINGS = [
        Binding("d", "switch_screen('dashboard')", "Dashboard", show=True),
        Binding("r", "switch_screen('conflicts')", "Review", show=True),
        Binding("a", "switch_screen('audit')", "Audit", show=True),
        Binding("s", "sync", "Sync", show=True),
        Binding("q", "quit", "Quit", show=True),
    ]

    SCREENS = {
        "dashboard": DashboardScreen,
        "conflicts": ConflictsScreen,
        "audit": AuditScreen,
    }

    def on_mount(self) -> None:
        self.push_screen("dashboard")

    def action_sync(self) -> None:
        """Trigger a dry-run sync from the TUI."""
        dashboard = self.query_one(DashboardScreen, DashboardScreen) if self.screen.id == "dashboard" else None
        if dashboard and hasattr(dashboard, "run_sync"):
            dashboard.run_sync()
        else:
            self.push_screen("dashboard")
