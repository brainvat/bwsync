#!/usr/bin/env python3
"""
Chrome Profile Inventory
=========================
Scans all Chrome profiles and prints an anonymized summary by default.
No file is written unless you explicitly request it with --show-sensitive.

USAGE:
    python3 chrome_profile_inventory.py                   # safe — anonymized output only
    python3 chrome_profile_inventory.py --show-sensitive  # writes full CSV to Desktop

OUTPUT (--show-sensitive only):
    ~/Desktop/chrome_profile_inventory.csv
"""

import json
import csv
import os
import sqlite3
import shutil
import tempfile
import argparse
import re
from pathlib import Path
from datetime import datetime, timezone


def chrome_date(ts):
    if not ts:
        return ''
    try:
        unix_ts = (ts / 1_000_000) - 11644473600
        return datetime.fromtimestamp(unix_ts, tz=timezone.utc).strftime('%Y-%m-%d')
    except Exception:
        return ''


def count_logins(profile_dir: Path) -> int:
    login_data = profile_dir / 'Login Data'
    if not login_data.exists():
        return 0
    tmp_fd, tmp_path = tempfile.mkstemp(suffix='.db')
    os.close(tmp_fd)
    try:
        shutil.copy2(login_data, tmp_path)
        conn = sqlite3.connect(tmp_path)
        count = conn.execute("SELECT COUNT(*) FROM logins").fetchone()[0]
        conn.close()
        return count
    except Exception:
        return -1
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


def count_history(profile_dir: Path) -> int:
    history = profile_dir / 'History'
    if not history.exists():
        return 0
    tmp_fd, tmp_path = tempfile.mkstemp(suffix='.db')
    os.close(tmp_fd)
    try:
        shutil.copy2(history, tmp_path)
        conn = sqlite3.connect(tmp_path)
        count = conn.execute("SELECT COUNT(*) FROM urls").fetchone()[0]
        conn.close()
        return count
    except Exception:
        return -1
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


def get_last_active(profile_dir: Path) -> str:
    """Reads last active timestamp from History DB."""
    history = profile_dir / 'History'
    if not history.exists():
        return ''
    tmp_fd, tmp_path = tempfile.mkstemp(suffix='.db')
    os.close(tmp_fd)
    try:
        shutil.copy2(history, tmp_path)
        conn = sqlite3.connect(tmp_path)
        row = conn.execute(
            "SELECT last_visit_time FROM urls ORDER BY last_visit_time DESC LIMIT 1"
        ).fetchone()
        conn.close()
        return chrome_date(row[0]) if row else ''
    except Exception:
        return ''
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


def inspect_profile(profile_dir: Path) -> dict:
    prefs_path = profile_dir / 'Preferences'
    profile_name = profile_dir.name  # fallback
    display_name = ''
    signed_in_email = ''
    signed_in_name = ''
    avatar_icon = ''
    is_supervised = ''
    account_list = ''
    created_date = ''
    gaia_id = ''

    if prefs_path.exists():
        try:
            with open(prefs_path, 'r', encoding='utf-8') as f:
                prefs = json.load(f)

            profile_section = prefs.get('profile', {})
            display_name = profile_section.get('name', '')
            avatar_icon  = profile_section.get('avatar_icon', '')
            is_supervised = str(profile_section.get('is_supervised', False))

            # Created date
            created_ts = profile_section.get('creation_time', 0)
            created_date = chrome_date(created_ts)

            # Signed-in account info (Google account linked to this profile)
            account_info_list = prefs.get('account_info', [])
            if account_info_list:
                # Primary account is usually first
                primary = account_info_list[0]
                signed_in_email = primary.get('email', '')
                signed_in_name  = primary.get('full_name', '') or primary.get('given_name', '')
                gaia_id         = primary.get('gaia', '')

                # All accounts if more than one
                if len(account_info_list) > 1:
                    account_list = ' | '.join(
                        a.get('email', '') for a in account_info_list if a.get('email')
                    )
                else:
                    account_list = signed_in_email

            # Fallback: check signin.allowed / signin username
            if not signed_in_email:
                signed_in_email = prefs.get('google', {}).get('services', {}).get('signin', {}).get('username', '')

        except Exception as e:
            display_name = f'[error reading prefs: {e}]'

    password_count = count_logins(profile_dir)
    history_count  = count_history(profile_dir)
    last_active    = get_last_active(profile_dir)

    return {
        'profile_folder':           profile_dir.name,
        'display_name':             display_name,
        'signed_in_email':          signed_in_email,
        'signed_in_name':           signed_in_name,
        'all_accounts':             account_list,
        'gaia_id':                  gaia_id,
        'password_count':           password_count if password_count >= 0 else 'error',
        'history_entries':          history_count  if history_count  >= 0 else 'error',
        'last_active':              last_active,
        'profile_created':          created_date,
        'avatar_icon':              avatar_icon,
        'is_supervised':            is_supervised,
        'google_account_confirmed': '',   # ← YOU FILL THIS IN
        'notes':                    '',   # ← optional notes
    }


def anonymize_email(email: str) -> str:
    """user@example.com → u**r@example.com"""
    if not email or '@' not in email:
        return email
    local, domain = email.split('@', 1)
    if len(local) <= 2:
        return local[0] + '*@' + domain
    return local[0] + ('*' * min(7, len(local) - 2)) + local[-1] + '@' + domain


def anonymize_name(name: str) -> str:
    """Allen Hammock → A**** H*****"""
    if not name:
        return name
    parts = name.split()
    return ' '.join(p[0] + '*' * min(4, len(p) - 1) for p in parts)


def anonymize_row(row: dict) -> dict:
    r = dict(row)
    r['signed_in_email'] = anonymize_email(r.get('signed_in_email', ''))
    r['signed_in_name']  = anonymize_name(r.get('signed_in_name', ''))
    r['gaia_id']         = ('*' * 8) if r.get('gaia_id') else ''
    if r.get('all_accounts'):
        r['all_accounts'] = ' | '.join(
            anonymize_email(e.strip()) for e in r['all_accounts'].split('|')
        )
    return r


def assign_priority(password_count, is_duplicate: bool) -> tuple[str, str]:
    """
    Returns (priority_label, action) based on password count and duplicate status.
    Duplicates are flagged separately — same email seen in another profile.
    """
    if is_duplicate:
        return '⚪ SKIP', 'Duplicate account — already covered by another profile'
    if not isinstance(password_count, int) or password_count == 0:
        return '⚪ SKIP', 'No passwords in Chrome — check GPM anyway if you use this account'
    if password_count >= 200:
        return '🔴 CRITICAL', 'Export from passwords.google.com immediately'
    if password_count >= 40:
        return '🔴 HIGH',     'Export from passwords.google.com'
    if password_count >= 8:
        return '🟡 MEDIUM',   'Export from passwords.google.com'
    if password_count >= 1:
        return '🟢 LOW',      'Likely already covered by Chrome export — verify then skip'
    return '⚪ SKIP', 'No passwords found'


def tag_duplicates(rows: list[dict]) -> list[dict]:
    """
    For each email address, mark all but the highest-password-count profile
    as duplicates so we don't export the same Google account twice.
    """
    from collections import defaultdict
    email_groups = defaultdict(list)
    for i, row in enumerate(rows):
        email = (row.get('signed_in_email') or '').strip().lower()
        if email:
            email_groups[email].append(i)

    duplicate_indices = set()
    for email, indices in email_groups.items():
        if len(indices) > 1:
            # Keep the one with the highest password count; mark the rest
            best = max(indices, key=lambda i: rows[i]['password_count']
                       if isinstance(rows[i]['password_count'], int) else 0)
            for i in indices:
                if i != best:
                    duplicate_indices.add(i)

    for i, row in enumerate(rows):
        row['_is_duplicate'] = i in duplicate_indices
    return rows


def main():
    parser = argparse.ArgumentParser(description='Chrome Profile Inventory')
    parser.add_argument(
        '--show-sensitive',
        action='store_true',
        help='Write full CSV with real names and emails to Desktop. '
             'Default is anonymized terminal output only — no file written.'
    )
    args = parser.parse_args()

    chrome_base = Path.home() / 'Library' / 'Application Support' / 'Google' / 'Chrome'

    if not chrome_base.exists():
        print(f"❌  Chrome directory not found: {chrome_base}")
        return

    candidate_dirs = [chrome_base / 'Default'] + sorted(chrome_base.glob('Profile *'))
    rows = []

    print(f"\n📂  Scanning Chrome profiles in:\n    {chrome_base}\n")
    if not args.show_sensitive:
        print("  🔒  Safe mode — emails and names are anonymized. No file will be saved.")
        print("      Run with --show-sensitive to write the full CSV.\n")

    for profile_dir in candidate_dirs:
        if not profile_dir.is_dir():
            continue
        print(f"  • {profile_dir.name:<15}", end=' ', flush=True)
        row = inspect_profile(profile_dir)
        rows.append(row)
        display = anonymize_row(row) if not args.show_sensitive else row
        print(
            f"  {display['display_name'] or '(no name)':<25}"
            f"  {display['signed_in_email'] or '(not signed in)':<35}"
            f"  {row['password_count']} passwords"
        )

    if not rows:
        print("❌  No Chrome profiles found.")
        return

    # Sort: signed-in profiles first, then by password count desc
    rows.sort(key=lambda r: (
        0 if r['signed_in_email'] else 1,
        -(r['password_count'] if isinstance(r['password_count'], int) else 0)
    ))

    # Tag duplicates and assign priority
    rows = tag_duplicates(rows)
    for row in rows:
        priority, action = assign_priority(row['password_count'], row['_is_duplicate'])
        row['priority'] = priority
        row['action']   = action

    if not args.show_sensitive:
        print(f"\n{'═'*100}")
        print(f"  🔒  SAFE MODE SUMMARY — {len(rows)} profiles found\n")
        print(f"  {'FOLDER':<14} {'DISPLAY NAME':<18} {'SIGNED-IN EMAIL':<28} {'PWDS':>5}  {'LAST ACTIVE':<12}  PRIORITY")
        print(f"  {'-'*14} {'-'*18} {'-'*28} {'-'*5}  {'-'*12}  {'-'*20}")
        for r in rows:
            a = anonymize_row(r)
            print(
                f"  {r['profile_folder']:<14} "
                f"{a['display_name'] or '(none)':<18} "
                f"{a['signed_in_email'] or '(not signed in)':<28} "
                f"{str(r['password_count']):>5}  "
                f"{r['last_active']:<12}  "
                f"{r['priority']}"
            )
        # Action plan — only actionable rows
        actionable = [r for r in rows if '⚪' not in r['priority']]
        print(f"\n  📋  ACTION PLAN — {len(actionable)} accounts need passwords.google.com export:\n")
        for r in actionable:
            a = anonymize_row(r)
            print(f"  {r['priority']:<14}  {a['signed_in_email']:<28}  {r['action']}")
        print(f"\n  ✅  Safe mode complete. No file was written.")
        print(f"      Run with --show-sensitive to save the full CSV.\n")
        return

    # --show-sensitive mode — write CSV
    output_path = Path.home() / 'Desktop' / 'chrome_profile_inventory.csv'
    fieldnames = [
        'priority', 'action', 'profile_folder', 'display_name', 'signed_in_email',
        'signed_in_name', 'all_accounts', 'gaia_id', 'password_count', 'history_entries',
        'last_active', 'profile_created', 'avatar_icon', 'is_supervised',
        'google_account_confirmed', 'notes'
    ]

    # Strip internal keys before writing
    clean_rows = [{k: v for k, v in r.items() if not k.startswith('_')} for r in rows]

    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(clean_rows)

    os.chmod(output_path, 0o600)

    print(f"\n{'═'*60}")
    print(f"  ✅  {len(rows)} profiles written to:")
    print(f"      {output_path}")
    print(f"\n  👉  Open the CSV, check 'signed_in_email' — Chrome may")
    print(f"      have already filled most of it in for you.")
    print(f"      Fill in 'google_account_confirmed' for any gaps,")
    print(f"      then visit passwords.google.com for each unique account.")
    print(f"{'═'*60}\n")


if __name__ == '__main__':
    main()
