# bwsync — Personal Password Sync Engine
### Product Specification v0.2

---

## 1. Vision

A personal, developer-owned password sync engine that continuously harvests credentials from all local sources (Chrome profiles, iCloud Keychain, Google Password Manager CSV exports), deduplicates and normalizes them, and keeps a single Bitwarden vault as the authoritative source of truth — with full auditability, conflict review, and a clean extension model for adding new sources later.

**Design principles:**
- Bitwarden is the destination, never the origin. Data flows *into* it, not out.
- Nothing is overwritten silently. Conflicts are flagged and held for human review.
- Every sync run is logged. Full audit trail at all times.
- Sources are plugins. Adding a new one (Firefox, Dashlane CSV, etc.) should take under an hour.
- Secrets never touch disk unencrypted except during the brief extraction window, which is explicitly logged.

---

## 2. Architecture Overview

### UI Layer (interchangeable, never touch core logic)

```
┌───────────────────────────────────────────────────────────────────────┐
│                          UI Layer                                      │
│                                                                        │
│  ┌──────────────────┐   ┌──────────────────┐   ┌────────────────────┐ │
│  │  Textual TUI     │   │    Flet UI        │   │   Click CLI        │ │
│  │  (Phase 1)       │   │  desktop / web    │   │  escape hatch /    │ │
│  │                  │   │  (Phase 3)        │   │  scripting         │ │
│  │  btop-aesthetic  │   │  Flutter-rendered │   │  (always present)  │ │
│  │  live panels     │   │  same code both   │   │                    │ │
│  │  keyboard nav    │   │  modes            │   │                    │ │
│  └────────┬─────────┘   └────────┬──────────┘   └────────┬───────────┘ │
└───────────┼──────────────────────┼──────────────────────┼──────────────┘
            └──────────────────────┴──────────────────────┘
                                   │
                     ┌─────────────▼──────────────┐
                     │       BWSyncEngine           │
                     │  Pure Python — zero UI deps  │
                     │                              │
                     │  .sync()   → SyncResult      │
                     │  .status() → StatusData      │
                     │  .conflicts() → list         │
                     │  .resolve() → void           │
                     │  .audit()  → list[RunLog]    │
                     └──────────┬──────────────┬───┘
                                │              │
               ┌────────────────▼──┐    ┌──────▼────────────┐
               │   Source Layer     │    │  Bitwarden Layer   │
               │   plugin adapters  │    │  bw serve REST     │
               └────────────────┬──┘    └──────┬────────────┘
                                │              │
                           ┌────▼──────────────▼────┐
                           │      State Store         │
                           │  SQLite  ~/.config/bwsync│
                           └─────────────────────────┘
```

### Why this works without a rewrite

Textual, Flet, and Click all call the same `BWSyncEngine` methods and render the returned data in their own way. The engine never calls `print()`, never blocks on `input()`, and has no concept of terminal width or UI widgets. Adding a new UI surface is purely additive — no existing layer is touched.

Switching Flet between desktop and web mode is a single argument:
```python
flet.app(target=main)                           # native desktop window
flet.app(target=main, view=flet.WEB_BROWSER)    # opens in browser
```

---

## 3. Components

### 3.1 Source Layer

Each source is a plugin that implements a common interface:

```python
class BaseSource:
    name: str                    # "chrome", "icloud", "gpm"
    def extract(self) -> list[NormalizedEntry]:
        ...
```

**Bundled sources (v1):**

| Source | Method | Status |
|---|---|---|
| `chrome` | Reads local SQLite Login Data via existing extractor script | ✅ Existing code |
| `icloud` | Reads local Keychain via existing extractor script | ✅ Existing code |
| `gpm` | Ingests manually exported CSV from passwords.google.com | 🔜 Phase 1 |
| `bitwarden_csv` | One-time ingest of a BW export (bootstrap only) | 🔜 Phase 1 |

**Future sources (plugin slots):**
- Firefox (SQLite, similar to Chrome)
- Safari (Security framework on macOS)
- Dashlane / LastPass CSV exports
- 1Password CSV export

### 3.2 Normalized Schema

All sources map to this common entry format before any comparison or sync:

```python
@dataclass
class NormalizedEntry:
    # Identity
    id: str                   # UUID, our internal key
    source: str               # "chrome", "icloud", "gpm"
    source_profile: str       # "Profile 7 / skai.io", "login.keychain", etc.
    source_key: str           # Hash(url + username) — stable dedup key

    # Credential
    url: str
    name: str                 # Derived from domain, or original if available
    username: str
    password: str             # Plaintext during processing only

    # Metadata
    notes: str
    date_created: datetime | None
    date_last_used: datetime | None
    times_used: int

    # Sync state
    bitwarden_id: str | None  # BW item UUID once synced
    sync_status: SyncStatus   # pending | synced | conflict | skipped | error
    last_synced_at: datetime | None
    conflict_data: dict | None  # Populated on conflict — stores both sides
```

**SyncStatus enum:**
```
pending   → extracted, not yet pushed to Bitwarden
synced    → exists in BW, matches source, no action needed
conflict  → exists in BW with different password — held for review
skipped   → user explicitly chose to skip this entry
error     → sync attempted, failed — see logs
```

### 3.3 State Store

Local SQLite database at `~/.config/bwsync/state.db`.

Stores:
- All normalized entries and their sync status
- Full conflict records (both sides of every conflict)
- Sync run history and audit log
- Source configuration

The state store is the system of record for "what has been seen, what has been synced, what is in conflict." Bitwarden is the vault. These are separate concerns.

### 3.4 Bitwarden Layer

Interfaces with Bitwarden via the official `bw` CLI using `bw serve`, which exposes a local REST API at `localhost:8087`. This avoids screen-scraping CLI output and gives clean JSON.

```
bw serve  →  http://localhost:8087
```

Key operations used:
- `GET  /list/object/items?search=<domain>`  — check if entry exists
- `POST /object/item`                         — create new item
- `PUT  /object/item/<id>`                   — update existing item
- `GET  /list/object/items`                  — full vault list (for initial diff)

Authentication: `bw login` + `bw unlock` run once interactively, session token stored in env. Subsequent runs use `BW_SESSION` env var — never written to disk.

### 3.5 Sync Engine

The core algorithm run on each `bwsync sync`:

```
1. EXTRACT  — run all enabled sources, get list of NormalizedEntry
2. NORMALIZE — deduplicate within the batch (same url+username, pick newest)
3. DIFF     — compare each entry against state store + Bitwarden:
     a. New entry, not in BW          → mark pending, push to BW
     b. Entry matches BW exactly      → mark synced, no action
     c. Entry exists in BW, pw differs → mark conflict, hold for review
     d. Entry in BW, not in any source → leave alone (BW-native, don't delete)
4. PUSH     — push all pending entries to BW via REST
5. LOG      — write full audit record for this run
```

Conflicts are **never auto-resolved**. They accumulate in the state store and surface in `bwsync review`.

---

## 4. UI Surfaces

### 4.1 Textual TUI (Phase 1 — primary interface)

The main interactive experience. Launches with `bwsync` (no arguments) and presents a full-terminal dashboard in the btop style: always-on status header, live-updating panels, keyboard-navigable tables, modal dialogs for conflict resolution.

**Layout:**
```
╔══════════════════════════════════════════════════════════════════════╗
║  bwsync                          🔒 Bitwarden: connected  [Q]uit    ║
╠══════════════════╦═══════════════════════════════════════════════════╣
║  SOURCES         ║  SYNC STATUS                                      ║
║  ✅ chrome  553  ║   Synced       ████████████████████  1,204        ║
║  ✅ icloud   88  ║   Pending      ███░░░░░░░░░░░░░░░░░    171        ║
║  ⏸  gpm    ---  ║   Conflicts    █░░░░░░░░░░░░░░░░░░░     18        ║
║                  ║   Errors       ░░░░░░░░░░░░░░░░░░░░      0        ║
╠══════════════════╩═══════════════════════════════════════════════════╣
║  CONFLICTS  (18 unresolved)                         [R]esolve [E]xport ║
║  ──────────────────────────────────────────────────────────────────  ║
║  ⚠  github.com              user@example.com    chrome→BW       ║
║  ⚠  aws.amazon.com          user@example.com    icloud→BW       ║
║  ⚠  notion.so               user42@example.com       chrome→BW  ◄    ║
║  ⚠  slack.com               user@example.org         chrome→BW       ║
╠══════════════════════════════════════════════════════════════════════╣
║  AUDIT LOG                                                           ║
║  2026-03-15 14:32  sync  chrome+icloud  +171 pushed  18 conflicts   ║
║  2026-03-14 09:11  sync  chrome         +3 pushed    0 conflicts    ║
╠══════════════════════════════════════════════════════════════════════╣
║  [S]ync  [R]eview conflicts  [A]udit  [C]onfig  [?]Help  [Q]uit    ║
╚══════════════════════════════════════════════════════════════════════╝
```

Conflict resolution opens a full modal with both passwords side-by-side, keyboard shortcuts to keep/override/skip, and optional reveal toggle.

**Key bindings:**
- `s` — run sync (opens live progress panel)
- `r` — enter conflict review mode
- `a` — audit log view
- `c` — config editor
- `f2` — toggle dry-run mode
- `q` — quit

### 4.2 Click CLI (always present — scripting / automation / CI)

Every engine operation is also reachable as a non-interactive CLI command for scripting, cron, and piping. The Textual TUI is the default when a TTY is detected; CLI mode activates when piped or when `--no-tui` is passed.

```bash
bwsync sync                             # launches TUI with sync running
bwsync sync --no-tui                    # plain output, scriptable
bwsync sync --source chrome --dry-run --no-tui | tee sync_preview.txt
bwsync resolve <id> --keep-bitwarden --no-tui
bwsync status --no-tui --json           # machine-readable JSON output
bwsync audit --no-tui --export audit.csv
```

### 4.3 Flet UI (Phase 3 — desktop + browser)

A Flutter-rendered Python UI using Flet. Identical Python codebase runs as a native desktop app or in a browser — one flag switches modes. Designed for the conflict review workflow where a richer layout helps: side-by-side password comparison, color-coded source badges, checkbox bulk selection, sortable tables.

```python
# desktop
flet.app(target=main)

# browser (serves on localhost:8550)
flet.app(target=main, view=flet.WEB_BROWSER, port=8550)
```

No separate backend needed — Flet's Python process IS the backend. The UI calls `BWSyncEngine` methods directly, same as Textual does.

---

## 5. Configuration

Config file: `~/.config/bwsync/config.json`

```json
{
  "bitwarden": {
    "server": "https://vault.bitwarden.com",
    "email": "user@example.com",
    "serve_port": 8087
  },
  "sources": {
    "chrome": {
      "enabled": true,
      "profiles": "auto"
    },
    "icloud": {
      "enabled": true
    },
    "gpm": {
      "enabled": false,
      "note": "Run manually: bwsync sync --source gpm --file <path>"
    }
  },
  "sync": {
    "conflict_strategy": "flag",
    "dedup_strategy": "latest_used",
    "auto_schedule": false
  }
}
```

---

## 6. Security Model

- Passwords exist in memory only during the extraction and push window
- State store holds **hashed** passwords (SHA-256) for change detection, never plaintext
- Bitwarden session token passed via environment variable, never written to disk or config
- All temp files (copied SQLite DBs) use `tempfile.mkstemp` and are deleted in `finally` blocks — same pattern as existing scripts
- State DB file permissions: `600` (owner read/write only)
- `--dry-run` mode never decrypts or transmits passwords at all

---

## 7. File & Directory Structure

```
bwsync/
├── pyproject.toml
├── README.md
├── bwsync/
│   ├── __init__.py
│   │
│   ├── engine.py           # ★ BWSyncEngine — pure core, zero UI deps
│   ├── schema.py           # NormalizedEntry dataclass, SyncStatus enum
│   ├── config.py           # Load / validate config
│   ├── db.py               # SQLite state store (all reads/writes)
│   ├── bitwarden.py        # BW REST client wrapping bw serve
│   │
│   ├── sources/            # Extractor plugins
│   │   ├── __init__.py
│   │   ├── base.py         # Abstract BaseSource
│   │   ├── chrome.py       # Adapted from extract_chrome_passwords.py
│   │   ├── icloud.py       # Adapted from icloud extractor
│   │   └── gpm.py          # Google PM: CSV file ingest
│   │
│   ├── tui/                # Textual TUI (Phase 1)
│   │   ├── __init__.py
│   │   ├── app.py          # Textual App class, layout, key bindings
│   │   ├── screens/
│   │   │   ├── dashboard.py
│   │   │   ├── conflicts.py
│   │   │   └── audit.py
│   │   └── widgets/
│   │       ├── status_bar.py
│   │       ├── source_panel.py
│   │       └── progress_panel.py
│   │
│   ├── cli.py              # Click CLI — calls engine, no TUI deps
│   │
│   └── ui/                 # Flet UI (Phase 3)
│       ├── __init__.py
│       ├── app.py          # Flet app entry — desktop + web
│       ├── pages/
│       │   ├── dashboard.py
│       │   ├── conflicts.py
│       │   └── audit.py
│       └── components/
│           ├── sync_card.py
│           └── conflict_row.py
│
└── tests/
    ├── test_schema.py
    ├── test_engine.py
    ├── test_bitwarden.py
    └── fixtures/
        └── sample_logins.csv
```

---

## 8. Phased Delivery

### Phase 1 — Engine + Textual TUI + Chrome & iCloud sources
- `BWSyncEngine` class (pure core, no UI)
- `schema.py`, `db.py`, `config.py`, `bitwarden.py`
- Chrome source plugin (port of existing script)
- iCloud source plugin (port of existing script)
- Textual TUI: dashboard, conflict review, live sync progress
- Click CLI as non-interactive fallback (`--no-tui`)
- `--dry-run` throughout all surfaces

### Phase 2 — Google PM + Audit + Scheduling
- GPM CSV ingest source
- Full audit log view in TUI + CLI export
- `bwsync schedule` → generates launchd plist or cron entry
- `--watch` mode for continuous background sync

### Phase 3 — Flet UI (desktop + browser)
- `bwsync ui` launches Flet desktop window
- `bwsync ui --web` launches in browser at localhost:8550
- Conflict review dashboard with richer layout
- Same `BWSyncEngine` underneath — zero duplication

### Phase 4 — Bitwarden Secrets Manager
- `bwsync secrets sync` command
- Sync developer API keys / `.env` vars into BW Secrets Manager
- GitHub Actions / CI integration
- SDK support (Python, Node) for reading secrets in projects

---

## 9. Out of Scope (v1)

- Syncing *from* Bitwarden back to Chrome/iCloud (BW is the destination)
- Deletion of entries from Bitwarden (too destructive to automate)
- Multi-user / shared vaults
- Mobile password sources
- Cloud-hosted version of this tool

---

## 10. Open Questions (Pre-Build)

1. **iCloud extractor**: What is the current output schema of the iCloud script? Needs mapping to NormalizedEntry.
2. **BW Folder structure**: Should imported entries be organized into BW Folders by source (Chrome, iCloud, etc.) or left flat?
3. **Scheduling**: For ongoing sync, should Phase 1 include a `--watch` mode or is cron/launchd configuration sufficient?

---

## 11. Key Dependencies

| Package | Purpose | Phase |
|---|---|---|
| `textual` | TUI framework (btop-style) | 1 |
| `click` | CLI argument parsing | 1 |
| `rich` | Text formatting, tables (used by Textual) | 1 |
| `pycryptodome` | Chrome AES-CBC decryption (existing) | 1 |
| `httpx` | HTTP client for `bw serve` REST calls | 1 |
| `flet` | Flutter-rendered desktop + web UI | 3 |

---

*Last updated: 2026-03-15 | Status: v0.2 — UI architecture updated*
