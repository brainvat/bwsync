"""Click CLI for bwsync."""

from __future__ import annotations

import csv
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from bwsync.engine import BWSyncEngine
from bwsync.schema import SyncStatus

console = Console()


def _get_engine() -> BWSyncEngine:
    return BWSyncEngine()


@click.group(invoke_without_command=True)
@click.pass_context
def main(ctx):
    """bwsync — macOS password consolidation engine."""
    if ctx.invoked_subcommand is None:
        if sys.stdout.isatty():
            # Launch TUI if interactive terminal
            ctx.invoke(tui)
        else:
            click.echo(ctx.get_help())


@main.command()
@click.option("--source", "-s", multiple=True, type=click.Choice(["chrome", "icloud"]),
              help="Sources to sync (default: all enabled)")
@click.option("--dry-run", is_flag=True, help="Classify entries without pushing to Bitwarden")
def sync(source, dry_run):
    """Run the sync pipeline."""
    engine = _get_engine()
    sources = list(source) if source else None

    with console.status("[bold green]Syncing..."):
        result = engine.sync(sources=sources, dry_run=dry_run)

    table = Table(title="Sync Results" + (" (DRY RUN)" if dry_run else ""))
    table.add_column("Metric", style="cyan")
    table.add_column("Count", justify="right", style="green")

    table.add_row("Sources", ", ".join(result.sources_used) or "none")
    table.add_row("Total extracted", str(result.total_extracted))
    table.add_row("New entries", str(result.new_entries))
    table.add_row("Updated", str(result.updated_entries))
    table.add_row("Conflicts", str(result.conflicts))
    table.add_row("Errors", str(result.errors))
    table.add_row("Skipped", str(result.skipped))
    table.add_row("Duration", f"{result.duration_seconds}s")

    console.print()
    console.print(table)

    if result.conflicts > 0:
        console.print(f"\n[yellow]  {result.conflicts} conflict(s) need review.[/]")
        console.print("  Run: bwsync review --list")


@main.command()
def status():
    """Show dashboard summary."""
    engine = _get_engine()
    data = engine.status()

    table = Table(title="bwsync Status")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Total entries", str(data["total_entries"]))
    for status_name, count in sorted(data["counts"].items()):
        table.add_row(f"  {status_name}", str(count))

    bw_status = "[green]Connected[/]" if data["bitwarden_connected"] else "[red]Not connected[/]"
    table.add_row("Bitwarden", bw_status)

    if data["last_run"]:
        table.add_row("Last run", data["last_run"].get("timestamp", "unknown"))

    console.print()
    console.print(table)


@main.command()
@click.option("--interactive", "-i", is_flag=True, help="Walk through each conflict interactively")
@click.option("--list", "list_only", is_flag=True, help="List conflicts without resolving")
@click.option("--export", "export_path", type=click.Path(), help="Export conflicts to CSV")
def review(interactive, list_only, export_path):
    """Review and resolve conflicts."""
    engine = _get_engine()
    conflicts = engine.get_conflicts()

    if not conflicts:
        console.print("\n  [green]No conflicts to review.[/]\n")
        return

    if export_path:
        _export_conflicts(conflicts, export_path)
        return

    if list_only or not interactive:
        _list_conflicts(conflicts)
        return

    _interactive_review(engine, conflicts)


def _list_conflicts(conflicts: list[dict]):
    table = Table(title=f"Conflicts ({len(conflicts)})")
    table.add_column("Source Key (first 12)", style="dim")
    table.add_column("URL", style="cyan")
    table.add_column("Username", style="green")
    table.add_column("Source", style="yellow")

    for c in conflicts:
        table.add_row(
            c["source_key"][:12] + "...",
            c["url"],
            c["username"],
            c["source"],
        )

    console.print()
    console.print(table)
    console.print(f"\n  Run: bwsync review --interactive")


def _interactive_review(engine: BWSyncEngine, conflicts: list[dict]):
    console.print(f"\n  [bold]Reviewing {len(conflicts)} conflict(s):[/]\n")

    for i, conflict in enumerate(conflicts, 1):
        console.print(f"  [{i}/{len(conflicts)}] [cyan]{conflict['url']}[/]")
        console.print(f"    Username: {conflict['username']}")
        console.print(f"    Source:   {conflict['source']} / {conflict['source_profile']}")
        console.print(f"    Status:   {conflict['sync_status']}")
        console.print()

        choice = click.prompt(
            "  Action",
            type=click.Choice(["source", "bitwarden", "skip", "quit"]),
            default="skip",
        )

        if choice == "quit":
            break
        elif choice == "source":
            engine.resolve_conflict(conflict["source_key"], "keep_source")
            console.print("    [green]-> Will push source version on next sync[/]\n")
        elif choice == "bitwarden":
            engine.resolve_conflict(conflict["source_key"], "keep_bitwarden")
            console.print("    [green]-> Keeping Bitwarden version[/]\n")
        elif choice == "skip":
            engine.resolve_conflict(conflict["source_key"], "skip")
            console.print("    [dim]-> Skipped[/]\n")


def _export_conflicts(conflicts: list[dict], path: str):
    fieldnames = ["source_key", "url", "username", "source", "source_profile", "sync_status"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(conflicts)
    os.chmod(path, 0o600)
    console.print(f"\n  [green]Exported {len(conflicts)} conflicts to {path}[/]\n")


@main.command()
@click.argument("source_key")
@click.option("--keep-source", "resolution", flag_value="keep_source", help="Keep the source version")
@click.option("--keep-bitwarden", "resolution", flag_value="keep_bitwarden", help="Keep the Bitwarden version")
@click.option("--skip", "resolution", flag_value="skip", help="Skip this entry")
def resolve(source_key, resolution):
    """Resolve a single conflict by source_key."""
    if not resolution:
        console.print("[red]  Specify one of: --keep-source, --keep-bitwarden, --skip[/]")
        return

    engine = _get_engine()
    engine.resolve_conflict(source_key, resolution)
    console.print(f"  [green]Resolved {source_key[:12]}... -> {resolution}[/]")


@main.command()
@click.option("--limit", "-n", default=20, help="Number of entries to show")
@click.option("--export", "export_path", type=click.Path(), help="Export audit log to JSON")
def audit(limit, export_path):
    """View the audit log."""
    engine = _get_engine()
    entries = engine.get_audit_log(limit=limit)

    if export_path:
        with open(export_path, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2, default=str)
        os.chmod(export_path, 0o600)
        console.print(f"\n  [green]Exported {len(entries)} audit entries to {export_path}[/]\n")
        return

    if not entries:
        console.print("\n  [dim]No audit entries yet.[/]\n")
        return

    table = Table(title=f"Audit Log (last {limit})")
    table.add_column("Timestamp", style="dim")
    table.add_column("Action", style="cyan")
    table.add_column("Details", style="green")

    for entry in entries:
        table.add_row(
            entry.get("timestamp", ""),
            entry.get("action", ""),
            entry.get("details", ""),
        )

    console.print()
    console.print(table)


@main.command()
def tui():
    """Launch the interactive TUI."""
    try:
        from bwsync.tui.app import BWsyncApp
        app = BWsyncApp()
        app.run()
    except ImportError as e:
        console.print(f"[red]  TUI requires textual: {e}[/]")
        console.print("  Install: pip install textual")


@main.command()
@click.option("--output", "-o", type=click.Path(), help="Output path for the Excel file")
def backup(output):
    """Create an Excel emergency backup."""
    try:
        import openpyxl
    except ImportError:
        console.print("[red]  Requires openpyxl: pip install openpyxl[/]")
        return

    engine = _get_engine()
    all_entries = engine.db.get_all_entries()

    if not all_entries:
        console.print("\n  [dim]No entries in database to backup.[/]\n")
        return

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = Path(engine.config.get("backup.backup_dir", str(Path.home() / "Documents" / "bwsync")))
    backup_dir.mkdir(parents=True, exist_ok=True)

    output_path = Path(output) if output else backup_dir / f"bwsync_backup_{timestamp}.xlsx"

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Entries"

    # Header
    headers = ["url", "username", "source", "source_profile", "name", "sync_status",
               "date_created", "date_last_used", "times_used"]
    ws.append(headers)

    for entry in all_entries:
        ws.append([entry.get(h, "") for h in headers])

    # Metadata sheet
    ws_meta = wb.create_sheet("Metadata")
    ws_meta.append(["Field", "Value"])
    ws_meta.append(["Backup Date", datetime.now().isoformat()])
    ws_meta.append(["Entry Count", len(all_entries)])

    wb.save(output_path)
    os.chmod(output_path, 0o600)

    # Encrypt if password is set
    password_env = engine.config.get("backup.excel_password_env", "BWSYNC_EXCEL_PASSWORD")
    password = os.environ.get(password_env, "")
    if password:
        try:
            import msoffcrypto
            import tempfile

            tmp_fd, tmp_path = tempfile.mkstemp(suffix=".xlsx")
            os.close(tmp_fd)
            with open(output_path, "rb") as f_in, open(tmp_path, "wb") as f_out:
                file = msoffcrypto.OfficeFile(f_in)
                file.load_key(password="")
                file.encrypt(password, f_out)
            import shutil
            shutil.move(tmp_path, output_path)
            console.print(f"  [green]Encrypted with {password_env}[/]")
        except Exception as e:
            console.print(f"  [yellow]Encryption failed: {e}[/]")

    console.print(f"\n  [green]Backup saved: {output_path}[/]\n")


if __name__ == "__main__":
    main()
