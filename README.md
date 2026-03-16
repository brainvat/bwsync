# bwsync

> A personal, developer-owned password sync engine — harvest credentials from Chrome, iCloud Keychain, and Google Password Manager, deduplicate them, and keep a single [Bitwarden](https://bitwarden.com) vault as your authoritative source of truth.

```
╔══════════════════════════════════════════════════════════════════════╗
║  bwsync                          🔒 Bitwarden: connected  [Q]uit    ║
╠══════════════════╦═══════════════════════════════════════════════════╣
║  SOURCES         ║  SYNC STATUS                                      ║
║  ✅ chrome  553  ║   Synced       ████████████████████  1,204        ║
║  ✅ icloud   88  ║   Pending      ███░░░░░░░░░░░░░░░░░    171        ║
║  ⏸  gpm    ---  ║   Conflicts    █░░░░░░░░░░░░░░░░░░░     18        ║
╠══════════════════╩═══════════════════════════════════════════════════╣
║  CONFLICTS  (18 unresolved)                         [R]esolve        ║
║  ⚠  github.com              user@example.com    chrome → BW            ║
║  ⚠  aws.amazon.com          user@example.com    icloud → BW            ║
╠══════════════════════════════════════════════════════════════════════╣
║  [S]ync  [R]eview conflicts  [A]udit  [C]onfig  [?]Help  [Q]uit    ║
╚══════════════════════════════════════════════════════════════════════╝
```

---

## Why this exists

If you use Chrome, you probably have multiple profiles — one for work, one personal, maybe a few more you barely remember. Each profile has its own password vault, completely isolated from the others. Chrome has no way to consolidate them.

Then there's iCloud Keychain for Safari logins, and Google Password Manager which stores yet another set — with no programmatic API and aggressive lock-in by design.

The result: hundreds of passwords scattered across sources, with no single answer to "what's my password for this site?" — and no disaster recovery if you lose access to one of those sources.

**bwsync fixes this in one run.** Extract everything locally, deduplicate across sources, push to Bitwarden, keep it in sync automatically. You'll never wonder which profile has the right password again.

---

## Features

- **Beautiful Textual TUI** — btop-inspired terminal dashboard with live sync progress, keyboard navigation, and interactive conflict resolution
- **Multiple Chrome profiles** — extracts and decrypts passwords from all local Chrome profiles simultaneously, handles duplicates across profiles automatically
- **iCloud Keychain** — reads directly from macOS Keychain via the native security framework
- **Google Password Manager** — ingests manually exported CSVs (GPM's only export path, by design)
- **Smart deduplication** — deduplicates within and across sources before anything touches Bitwarden
- **Conflict review, never auto-overwrite** — when a source password differs from Bitwarden, it's flagged for your review. Nothing is silently overwritten.
- **Full audit trail** — every sync run is logged with what was pushed, what conflicted, and what was skipped
- **Security-first** — passwords exist in memory only during the extraction window; state store never holds plaintext; temp files always cleaned up
- **Scriptable** — every operation available as a non-interactive CLI for cron, CI, and piping
- **Plugin architecture** — adding a new source (Firefox, Dashlane CSV, etc.) takes one file

---

## Installation

**Requirements:** Python 3.11+, [Bitwarden CLI](https://bitwarden.com/help/cli/) (`bw`), macOS (for Chrome + iCloud sources)

```bash
git clone https://github.com/brainvat/bwsync.git
cd bwsync
python -m venv venv && source venv/bin/activate
pip install -e .
```

Install the Bitwarden CLI if you haven't already:
```bash
brew install bitwarden-cli
bw login
```

---

## Quick start

```bash
# Launch the TUI dashboard
bwsync

# Or run a sync directly from the command line
bwsync sync --dry-run          # preview what would change, push nothing
bwsync sync                    # run for real
bwsync review                  # resolve any flagged conflicts
```

---

## Usage

### TUI (default)

Launch with `bwsync`. The dashboard shows all sources, sync status, unresolved conflicts, and recent audit log. Everything is keyboard-driven:

| Key | Action |
|-----|--------|
| `s` | Run sync |
| `r` | Conflict review mode |
| `a` | Audit log |
| `c` | Config editor |
| `F2` | Toggle dry-run |
| `q` | Quit |

### CLI (scripting / automation)

```bash
bwsync sync --no-tui                              # plain output, pipeable
bwsync sync --source chrome --dry-run --no-tui
bwsync sync --source gpm --file ~/Downloads/export.csv
bwsync status --no-tui --json
bwsync review --list
bwsync review --export conflicts.csv
bwsync resolve <id> --keep-bitwarden
bwsync resolve <id> --keep-source
bwsync audit --export audit.csv
```

---

## Sources

### Chrome
Reads directly from Chrome's local SQLite `Login Data` files across all profiles. Uses the macOS Keychain (`Chrome Safe Storage`) to derive the AES decryption key — the same mechanism Chrome itself uses. A Keychain access dialog may appear on first run; click *Always Allow*.

### iCloud Keychain
Reads from the local macOS Keychain via the `security` command-line tool.

### Google Password Manager
GPM has no programmatic API. Export manually from [passwords.google.com](https://passwords.google.com) → Settings → Export, then:
```bash
bwsync sync --source gpm --file ~/Downloads/Google\ Passwords.csv
```
Once you're fully migrated to Bitwarden, you can delete your GPM data and stop using it.

---

## Security model

- **No plaintext at rest** — the state store holds SHA-256 hashes of passwords for change detection, never the passwords themselves
- **Memory-only window** — credentials are decrypted, compared, and pushed in one pass, then discarded
- **Temp files** — Chrome's SQLite databases are copied to `tempfile.mkstemp()` paths and deleted in `finally` blocks; they never persist
- **Session token** — Bitwarden's session token is passed via `BW_SESSION` environment variable, never written to disk or config
- **File permissions** — state DB and any output files are created with `chmod 600` (owner read/write only)

---

## Protection setup

This repo includes a layered system to prevent credential files from ever accidentally entering git history. **Run this once after cloning:**

```bash
chmod +x setup-protections.sh
./setup-protections.sh
```

Re-run it after pulling if hooks have been updated.

### What it does

`setup-protections.sh` sets up three layers of defense:

**Layer 1 — `.gitignore`**
The `never-push-passwords/` directory is permanently excluded. Any file you place there is invisible to git entirely. This is where raw exported CSV files from passwords.google.com, Chrome, or iCloud should live temporarily before import.

**Layer 2 — `hooks/pre-commit`**
Runs before every commit. Blocks staging of any file that matches both a credential-sounding name *and* a data file extension (`.csv`, `.json`, `.txt`, `.db`, etc.). Code files like `.py` and `.sh` are never blocked, even if they have "passwords" in their name — because a script is not a credential file.

**Layer 3 — `hooks/pre-push`**
Runs before every push. Scans the full set of commits being pushed, not just the staging area. This is the safety net: even if something somehow slipped through the pre-commit hook, it will be caught here before it ever leaves your machine.

### The code vs. data rule

The hooks are designed around one key distinction:

| File | Blocked? | Why |
|------|----------|-----|
| `extract_chrome_passwords.py` | ✅ No | It's code — it contains logic, not credentials |
| `chrome_passwords_20260315.csv` | 🚫 Yes | It's a data file with a credential name |
| `never-push-passwords/export.csv` | 🚫 Yes | It's inside the protected directory |
| `bwsync/sources/icloud.py` | ✅ No | It's code |
| `icloud_keychain_backup.json` | 🚫 Yes | It's a data file with a credential name |

The earlier version of these hooks blocked on name alone, which caused `extract_chrome_passwords.py` to trip the pre-push hook. The current version requires both a credential-sounding name *and* a data file extension.

### Bypassing (when you genuinely need to)

The hooks can be bypassed with `--no-verify`, but this is logged and leaves you fully responsible:

```bash
git commit --no-verify   # bypass pre-commit
git push --no-verify     # bypass pre-push
```

Never use `--no-verify` as a routine shortcut. If the hook is blocking something legitimate, fix the hook pattern instead.

### Hooks are version-controlled

Unlike hooks placed directly in `.git/hooks/`, these hooks live in `hooks/` at the repo root and are committed to the repository. `setup-protections.sh` runs `git config core.hooksPath hooks/` to activate them. This means:

- Hook updates are distributed automatically when you `git pull`
- Anyone who clones the repo and runs `./setup-protections.sh` gets the same protection
- Your future self, on a new machine, is protected from day one

---

## Architecture

The core is a `BWSyncEngine` class with no UI dependencies — it returns structured data and emits no output itself. All UI surfaces (Textual TUI, Click CLI, and the forthcoming Flet UI) call the same engine methods and render results independently.

```
  Textual TUI  │  Click CLI  │  Flet UI (Phase 3)
               └──────┬──────┘
                  BWSyncEngine
               ┌──────┴──────┐
          Sources          Bitwarden
      (Chrome, iCloud,    (bw serve
         GPM, ...)         REST API)
               └──────┬──────┘
                  State Store
                  (SQLite, local)
```

---

## Roadmap

- **Phase 1** — Textual TUI, sync engine, Chrome + iCloud sources, conflict review, audit log *(in progress)*
- **Phase 2** — Google PM source, scheduled sync (`launchd` / cron), `--watch` mode
- **Phase 3** — [Flet](https://flet.dev) UI — same Python codebase runs as a native desktop app or in a browser (`bwsync ui --web`)
- **Phase 4** — Bitwarden Secrets Manager integration for developer API keys and CI/CD secrets

---

## Contributing

Contributions welcome — especially new source plugins. Each source is a single file implementing `BaseSource`:

```python
class BaseSource:
    name: str
    def extract(self) -> list[NormalizedEntry]:
        ...
```

See `bwsync/sources/base.py` for the interface and `bwsync/sources/chrome.py` for a reference implementation.

Please read `SECURITY.md` before contributing. Do not include real credentials in test fixtures — use the anonymized samples in `tests/fixtures/`.

---

## License

MIT — do whatever you want, just don't blame us if you lose your passwords.

---

*Built on [Bitwarden](https://bitwarden.com) · [Textual](https://textual.textualize.io) · [Flet](https://flet.dev)*
