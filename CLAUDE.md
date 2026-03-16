# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

bwsync is a macOS-only password consolidation engine that syncs credentials from multiple sources (Chrome, iCloud Keychain, Google Password Manager) into Bitwarden. It is currently in **Phase 1 scaffolding** — only standalone extraction scripts exist. The core application (BWSyncEngine, TUI, plugin system) described in `bwsync_product_spec.md` has not yet been built.

## Development Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
./setup-protections.sh        # REQUIRED: activates git hooks via core.hooksPath
```

Requires Python 3.11+ and macOS. The sole current dependency is `pycryptodome` for Chrome AES decryption.

## Running Scripts

```bash
python scripts/extract_chrome_passwords.py              # anonymized output
python scripts/extract_chrome_passwords.py --show-sensitive  # plaintext (never commit output)
python scripts/chrome_profile_inventory.py
python scripts/chrome_profile_inventory.py --show-sensitive
```

No test suite, linter, or build system exists yet.

## Critical: Credential Protection System

Three-layer defense prevents accidental credential leaks:

1. **`.gitignore`** — `never-push-passwords/` and `tmp/` are invisible to git
2. **`hooks/pre-commit`** — blocks files matching credential name + data extension from staging
3. **`hooks/pre-push`** — scans all commits being pushed as a safety net

**The "code vs. data" rule**: Hooks only block files that have BOTH a credential-sounding name (`password`, `credential`, `secret`, `login.data`, etc.) AND a data extension (`.csv`, `.json`, `.txt`, `.db`, `.sqlite`, etc.). Code files (`.py`, `.sh`, `.md`) are never blocked, even with "passwords" in the name.

Hooks are version-controlled in `hooks/` (not `.git/hooks/`) and distributed via `git config core.hooksPath hooks/`.

## Architecture (Current vs. Planned)

**Current**: Two standalone scripts in `scripts/` that use macOS Keychain + SQLite to extract/inventory Chrome passwords.

**Planned** (see `bwsync_product_spec.md`): A `BWSyncEngine` core with `NormalizedEntry` schema, `BaseSource` plugin interface, SQLite state store at `~/.config/bwsync/state.db`, and three UI surfaces (Textual TUI, Click CLI, Flet desktop). The Bitwarden CLI (`bw serve`) provides the REST API target.

## Three Inviolable Conventions

1. **Never push to remote** without explicit user permission. Git hooks enforce this, and Claude Code must never run `git push`.
2. **Never leave untracked files** during a commit. Every file is either tracked+committed or gitignored. If unclear, ask the user.
3. **Never merge to main**. All work stays on feature branches. The user merges manually.

## Repository Conventions

- Sensitive data files go in `never-push-passwords/` (gitignored)
- Temp files go in `tmp/` (gitignored)
- Sensitive output files must use `chmod 600`
- `BW_SESSION` is passed via environment variable, never written to disk
- Mirrors: GitHub (`brainvat/bwsync`) and GitLab (`digital-life-hacks/bwsync`)
