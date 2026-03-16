# bwsync Phase 1 — Test Plan

This document covers both automated tests (pytest) and manual verification steps for the Phase 1 implementation.

## Prerequisites

```bash
cd ~/Desktop/projects/digital-life/bwsync
source venv/bin/activate
pip install -e ".[dev]"       # installs all deps + pytest + ruff
./setup-protections.sh        # ensures git hooks are active
```

---

## Part 1: Automated Tests (pytest)

Run the full suite:

```bash
pytest tests/ -v
```

### Test files and what they cover

| File | Module | Tests |
|------|--------|-------|
| `tests/test_schema.py` | `bwsync.schema` | NormalizedEntry source_key generation, password hashing, to_dict/from_dict roundtrip, SyncResult/AuditLogEntry serialization |
| `tests/test_db.py` | `bwsync.db` | Table creation, upsert/get, update-on-conflict, status filtering, sync status updates, audit logging |
| `tests/test_chrome_source.py` | `bwsync.sources.chrome` | Chrome date conversion, URL-to-name derivation (unit tests only, no Chrome needed) |
| `tests/test_icloud_source.py` | `bwsync.sources.icloud` | Keychain dump parsing, protocol mapping, URL construction (unit tests only, no Keychain needed) |
| `tests/test_bitwarden.py` | `bwsync.bitwarden` | Password matching, URL construction, header construction (unit tests only, no bw serve needed) |
| `tests/test_engine.py` | `bwsync.engine` | Dedup/normalize logic, entry classification (new/synced/conflict), conflict resolution, status aggregation |

### Linting

```bash
ruff check bwsync/
```

---

## Part 2: Manual Integration Tests

These tests require macOS, Chrome installed, and optionally Bitwarden CLI.

### Test 2.1: Emergency Backup Script

**Purpose**: Verify sensitive data migration from repo to ~/Documents/bwsync/

```bash
# 1. Run the backup script
python scripts/emergency_backup.py

# 2. Verify outputs
ls -la ~/Documents/bwsync/
# Expected: bwsync_emergency_backup_YYYYMMDD_HHMMSS.xlsx and passwords_YYYYMMDD_HHMMSS.zip
# Expected: directory is chmod 700, files are chmod 600

# 3. Open the Excel file and verify:
#    - Tab 1 "Profile Inventory" has the CSV data
#    - Tab 2 "Metadata" has backup date and counts

# 4. Test encrypted backup (optional):
export BWSYNC_EXCEL_PASSWORD="testpass123"
python scripts/emergency_backup.py
# Verify the new Excel file requires the password to open

# 5. After verification, delete originals from repo:
rm never-push-passwords/chrome_profile_inventory.csv
rm tmp/passwords.zip
```

**Pass criteria**: Backup files exist in ~/Documents/bwsync/ with correct permissions; Excel has correct tabs and data.

### Test 2.2: Chrome Source Extraction

**Purpose**: Verify ChromeSource extracts real passwords from Chrome profiles

```bash
# Safe mode test (no actual sync, just extraction):
python -c "
from bwsync.sources.chrome import ChromeSource
source = ChromeSource()
print(f'Available: {source.is_available()}')
if source.is_available():
    entries = source.extract()
    print(f'Extracted: {len(entries)} entries')
    for e in entries[:3]:
        print(f'  {e.name}: {e.username} (source_key: {e.source_key[:12]}...)')
"
```

**Pass criteria**: Extracts entries from Chrome. A Keychain dialog may appear — click "Allow" or "Always Allow".

### Test 2.3: iCloud Keychain Source Extraction

**Purpose**: Verify ICloudSource extracts internet passwords from the login keychain

```bash
# This WILL trigger macOS Keychain access prompts
python -c "
from bwsync.sources.icloud import ICloudSource
source = ICloudSource()
print(f'Available: {source.is_available()}')
if source.is_available():
    entries = source.extract()
    print(f'Extracted: {len(entries)} entries')
    for e in entries[:3]:
        print(f'  {e.name}: {e.username}')
"
```

**Pass criteria**: Extracts entries. Multiple Keychain prompts are expected (one per password lookup). You can click "Deny" to skip individual entries or "Always Allow" to let them through.

### Test 2.4: CLI Smoke Tests

**Purpose**: Verify all CLI commands respond correctly

```bash
# Help
bwsync --help

# Status (works without Bitwarden)
bwsync status

# Dry-run sync from Chrome only
bwsync sync --dry-run --source chrome

# List conflicts (if any)
bwsync review --list

# Audit log
bwsync audit

# Backup
bwsync backup
```

**Pass criteria**: Each command produces output without crashing. `sync --dry-run` shows extracted/classified entries.

### Test 2.5: Bitwarden API Integration (requires Bitwarden CLI)

**Purpose**: Verify end-to-end sync to Bitwarden vault

**Setup**:
```bash
# 1. Install Bitwarden CLI if not present
brew install bitwarden-cli

# 2. Login and unlock
bw login
export BW_SESSION=$(bw unlock --raw)

# 3. Start bw serve
./scripts/bw_serve.sh start
# or: bw serve --port 8087 &

# 4. Test connection
curl http://localhost:8087/status
```

**Test with dummy data**:
```bash
python -c "
from bwsync.bitwarden import BitwardenClient
client = BitwardenClient()

# Test connection
print(f'Connected: {client.test_connection()}')

# Get vault status
status = client.get_status()
print(f'Status: {status}')

# Create a test entry
from bwsync.schema import NormalizedEntry
test_entry = NormalizedEntry(
    url='https://test-bwsync-dummy.example.com',
    username='bwsync-test-user',
    password='bwsync-test-password-DELETE-ME',
    name='bwsync test entry (DELETE ME)',
    notes='Created by bwsync API test — safe to delete',
)
result = client.create_item(test_entry)
print(f'Created item: {result.get(\"id\", \"unknown\")}')
print('SUCCESS: Delete the test entry from Bitwarden when done')
"
```

**Full pipeline test**:
```bash
bwsync sync --source chrome --dry-run     # Preview what would sync
bwsync sync --source chrome               # Actually push to Bitwarden
bwsync status                              # Verify counts
bwsync review --list                       # Check for conflicts
bwsync audit                               # View sync log
```

**Cleanup**:
```bash
./scripts/bw_serve.sh stop
```

**Pass criteria**: Test entry appears in the Bitwarden vault. Full sync creates items for Chrome passwords. Delete the test entry afterward.

### Test 2.6: TUI Launch

**Purpose**: Verify the Textual TUI starts correctly

```bash
bwsync tui
```

**In the TUI**:
- Press `d` → Dashboard screen shows status counts
- Press `s` → Triggers dry-run sync
- Press `r` → Review screen shows conflict table
- Press `a` → Audit screen shows log entries
- Press `q` → Quit

**Pass criteria**: TUI launches, screens are navigable, data loads without errors.

### Test 2.7: Git Safety Verification

**Purpose**: Confirm credential protection hooks still work

```bash
# 1. Verify hooks path is set
git config core.hooksPath
# Expected: hooks

# 2. Try to stage a credential file (should be blocked)
touch never-push-passwords/test_passwords.csv
git add never-push-passwords/test_passwords.csv
# Expected: blocked by pre-commit hook

# 3. Verify .gitignore covers new entries
git status
# Expected: venv/, __pycache__/, .env, *.egg-info/ are NOT shown as untracked

# 4. Clean up
rm never-push-passwords/test_passwords.csv
```

**Pass criteria**: Hooks block credential files; gitignore covers all generated files.

---

## Part 3: Edge Cases to Test

- **Chrome not installed**: `ChromeSource().is_available()` should return `False`
- **Bitwarden not running**: `bwsync status` should show "Not connected" without crashing
- **Empty state DB**: `bwsync status` and `bwsync review --list` should handle gracefully
- **No network**: `pip install` will fail — all code should work without network (except Bitwarden sync)
- **Duplicate entries across sources**: Same URL+username from Chrome and iCloud should dedup by `source_key`

---

## Test Environment Notes

- Python 3.11+ required (current venv is 3.14.3)
- macOS only (uses `security` CLI and Chrome macOS paths)
- Bitwarden API key is stored in `never-push-passwords/bitwarden-api-key.png` (gitignored)
- Bitwarden collection URL is in `never-push-passwords/bitwarden-vault.txt` (gitignored)
- All sensitive test outputs should go to `never-push-passwords/` or `~/Documents/bwsync/`
