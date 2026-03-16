#!/usr/bin/env python3
"""
Chrome Password Extractor for macOS
====================================
Extracts and decrypts passwords from ALL Chrome profiles on your Mac.

By default, prints an anonymized summary to the terminal — no file is written
and no sensitive data is displayed. This is the safe default.

Use --show-sensitive to write a plaintext CSV to Desktop, ready to import
into any password manager (1Password, Bitwarden, etc.)

REQUIRES:
    pip3 install pycryptodome

USAGE:
    python3 extract_chrome_passwords.py                   # safe — anonymized summary only
    python3 extract_chrome_passwords.py --show-sensitive  # writes plaintext CSV to Desktop

OUTPUT (--show-sensitive only):
    ~/Desktop/chrome_passwords_TIMESTAMP.csv  (permissions set to 600/owner-only)

SECURITY NOTE:
    The output file will contain PLAINTEXT passwords.
    Import into your password manager, then delete it immediately with:
        rm -P ~/Desktop/chrome_passwords_*.csv
"""

import sqlite3
import subprocess
import os
import csv
import shutil
import tempfile
import json
import argparse
import re
from pathlib import Path
from datetime import datetime, timezone

# --- Dependency Check ---
try:
    from Crypto.Cipher import AES
    from Crypto.Protocol.KDF import PBKDF2
    from Crypto.Hash import SHA1, HMAC as CryptoHMAC
except ImportError:
    print("\n❌  Missing dependency: pycryptodome")
    print("    Run this command first, then re-run the script:\n")
    print("        pip3 install pycryptodome\n")
    exit(1)


# ─────────────────────────────────────────────
# KEYCHAIN: Get Chrome's encryption secret
# ─────────────────────────────────────────────

def get_chrome_safe_storage_key() -> str:
    """
    Retrieves the Chrome Safe Storage password from macOS Keychain.
    Tries multiple known service name variants across Chrome versions/macOS releases.
    You may see a Keychain access dialog — click 'Always Allow'.
    """
    # Known variants across Chrome versions and macOS releases
    # Each tuple is (account, service) — Chrome stores account="Chrome", service="Chrome Safe Storage"
    candidates = [
        ('Chrome',   'Chrome Safe Storage'),
        ('Chromium', 'Chromium Safe Storage'),
        ('Chrome',   'Google Chrome Safe Storage'),
        ('Chrome',   'Chrome'),
    ]

    for account, service in candidates:
        result = subprocess.run(
            ['security', 'find-generic-password', '-a', account, '-s', service, '-w'],
            capture_output=True, text=True
        )
        if result.returncode == 0 and result.stdout.strip():
            print(f"    ✅  Found Keychain entry: account='{account}' service='{service}'")
            return result.stdout.strip()

    # Nothing found — run a diagnostic dump to help identify the correct name
    print("\n    ⚠️   None of the standard keychain entry names worked.")
    print("    Running diagnostic search for any Chrome-related keychain entries...\n")

    dump = subprocess.run(
        ['security', 'dump-keychain', 'login.keychain-db'],
        capture_output=True, text=True
    )
    chrome_lines = [
        line for line in dump.stdout.splitlines()
        if 'chrome' in line.lower() or 'chromium' in line.lower()
    ]

    if chrome_lines:
        print("    Found these Chrome-related Keychain entries:")
        for line in chrome_lines:
            print(f"      {line.strip()}")
        print()
        print("    👉  Copy the 'svce' value from above and re-run with:")
        print("          --keychain-service \"<name>\"")
    else:
        print("    ❌  No Chrome-related entries found in login.keychain-db at all.")
        print("        Possible causes:")
        print("          • Chrome has never been launched under this user account")
        print("          • Keychain access was denied — check System Settings → Privacy")
        print("          • Chrome is using a different keychain (check Keychain Access app)")

    raise RuntimeError("Could not retrieve Chrome Safe Storage key. See diagnostic output above.")


# ─────────────────────────────────────────────
# DECRYPTION: AES-CBC, Chrome macOS scheme
# ─────────────────────────────────────────────

def derive_aes_key(raw_key: str) -> bytes:
    """
    Chrome derives a 16-byte AES key from the Safe Storage password
    using PBKDF2-HMAC-SHA1 with a fixed salt and 1003 iterations.
    """
    salt = b'saltysalt'
    return PBKDF2(
        raw_key.encode('utf-8'),
        salt,
        dkLen=16,
        count=1003,
        prf=lambda p, s: CryptoHMAC.new(p, s, SHA1).digest()
    )


def decrypt_password(encrypted_value: bytes, aes_key: bytes) -> str:
    """
    Decrypts a Chrome-encrypted password blob.
    Chrome on macOS prepends 'v10' to AES-CBC encrypted data.
    """
    if not encrypted_value:
        return ''

    # v10 = AES-CBC encrypted (macOS Chrome)
    if encrypted_value[:3] == b'v10':
        payload = encrypted_value[3:]
        iv = b' ' * 16  # Chrome uses a space-padded IV
        try:
            cipher = AES.new(aes_key, AES.MODE_CBC, IV=iv)
            decrypted = cipher.decrypt(payload)
            # Remove PKCS7 padding
            padding_len = decrypted[-1] if isinstance(decrypted[-1], int) else ord(decrypted[-1])
            return decrypted[:-padding_len].decode('utf-8', errors='replace')
        except Exception:
            return '[decryption failed]'

    # Fallback: try plain text (older Chrome versions)
    try:
        return encrypted_value.decode('utf-8', errors='replace')
    except Exception:
        return '[unreadable]'


# ─────────────────────────────────────────────
# PROFILE DISCOVERY
# ─────────────────────────────────────────────

def find_chrome_profiles() -> list[tuple[str, Path]]:
    """
    Scans the Chrome user data directory for all profiles that have a
    Login Data file. Returns a list of (display_name, profile_path) tuples.
    """
    chrome_base = Path.home() / 'Library' / 'Application Support' / 'Google' / 'Chrome'

    if not chrome_base.exists():
        raise RuntimeError(f"Chrome user data directory not found at:\n  {chrome_base}")

    candidate_dirs = [chrome_base / 'Default'] + sorted(chrome_base.glob('Profile *'))
    profiles = []

    for profile_dir in candidate_dirs:
        login_data = profile_dir / 'Login Data'
        if not login_data.exists():
            continue

        # Try to get a human-readable profile name from Preferences
        display_name = profile_dir.name  # fallback: "Default", "Profile 1", etc.
        prefs_path = profile_dir / 'Preferences'
        if prefs_path.exists():
            try:
                with open(prefs_path, 'r', encoding='utf-8') as f:
                    prefs = json.load(f)
                display_name = prefs.get('profile', {}).get('name', display_name)
            except Exception:
                pass

        profiles.append((display_name, profile_dir))

    return profiles


# ─────────────────────────────────────────────
# EXTRACTION: Read & decrypt one profile
# ─────────────────────────────────────────────

def extract_from_profile(profile_name: str, profile_dir: Path, aes_key: bytes) -> list[dict]:
    """
    Copies the Login Data SQLite DB to a temp file (avoids Chrome file lock),
    queries all saved logins, decrypts passwords, and returns a list of dicts.
    """
    login_data_src = profile_dir / 'Login Data'

    # Work on a temp copy so we don't interfere with a running Chrome
    tmp_fd, tmp_path = tempfile.mkstemp(suffix='.db', prefix='chrome_ld_')
    os.close(tmp_fd)

    try:
        shutil.copy2(login_data_src, tmp_path)
        conn = sqlite3.connect(tmp_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                origin_url,
                action_url,
                username_element,
                username_value,
                password_element,
                password_value,
                date_created,
                date_last_used,
                times_used
            FROM logins
            ORDER BY origin_url ASC
        """)

        rows = cursor.fetchall()
        conn.close()

        entries = []
        for (origin_url, action_url, user_elem, username,
             pass_elem, enc_password, date_created, date_last_used, times_used) in rows:

            password = decrypt_password(enc_password, aes_key)

            # Convert Chrome's Windows epoch (microseconds since 1601-01-01) to ISO date
            def chrome_date(ts):
                if not ts:
                    return ''
                try:
                    # Chrome timestamps are microseconds since Jan 1, 1601
                    unix_ts = (ts / 1_000_000) - 11644473600
                    return datetime.fromtimestamp(unix_ts, tz=timezone.utc).strftime('%Y-%m-%d')
                except Exception:
                    return ''

            entries.append({
                'source':         'Chrome',
                'profile':        profile_name,
                'url':            origin_url or action_url or '',
                'username':       username or '',
                'password':       password,
                'date_created':   chrome_date(date_created),
                'date_last_used': chrome_date(date_last_used),
                'times_used':     times_used or 0,
                'notes':          ''
            })

        return entries

    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


# ─────────────────────────────────────────────
# ANONYMIZATION HELPERS
# ─────────────────────────────────────────────

def anonymize_url(url: str) -> str:
    """Keep the domain visible, mask everything else."""
    if not url:
        return ''
    try:
        # Extract just scheme + domain, hide path/query
        match = re.match(r'(https?://[^/?#]+)', url)
        if match:
            return match.group(1) + '/***'
        return '***'
    except Exception:
        return '***'

def anonymize_username(username: str) -> str:
    """Show first char and last char, mask the middle."""
    if not username:
        return ''
    if len(username) <= 2:
        return username[0] + '*'
    return username[0] + ('*' * min(6, len(username) - 2)) + username[-1]

def anonymize_entry(entry: dict) -> dict:
    """Return a copy of the entry with credentials masked."""
    return {
        **entry,
        'url':      anonymize_url(entry['url']),
        'username': anonymize_username(entry['username']),
        'password': '••••••••••••',
    }


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    print()
    print("╔══════════════════════════════════════════════╗")
    print("║    Chrome Password Extractor  •  macOS       ║")
    print("╚══════════════════════════════════════════════╝")
    print()

    # ─── Argument parsing ───
    parser = argparse.ArgumentParser(description='Extract Chrome passwords on macOS')
    parser.add_argument(
        '--show-sensitive',
        action='store_true',
        help='Write a plaintext CSV of all passwords to Desktop. '
             'Default is anonymized terminal summary only — no file written.'
    )
    parser.add_argument(
        '--keychain-service',
        type=str,
        default=None,
        metavar='NAME',
        help='Override the Keychain service name to look up (e.g. "Chrome Safe Storage")'
    )
    args = parser.parse_args()

    if not args.show_sensitive:
        print("  🔒  Safe mode — credentials will be anonymized, no file will be saved.")
        print("      Run with --show-sensitive to write the full plaintext CSV.\n")

    # 1. Get encryption key
    print("🔑  Retrieving Chrome Safe Storage key from Keychain...")
    print("    (A Keychain access dialog may appear — click 'Always Allow')\n")
    try:
        if args.keychain_service:
            print(f"    Using override service name: '{args.keychain_service}'")
            result = subprocess.run(
                ['security', 'find-generic-password', '-a', 'Chrome', '-s', args.keychain_service, '-w'],
                capture_output=True, text=True
            )
            if result.returncode != 0 or not result.stdout.strip():
                raise RuntimeError(f"Keychain entry '{args.keychain_service}' not found or returned empty.")
            raw_key = result.stdout.strip()
            print(f"    ✅  Found Keychain entry: '{args.keychain_service}'")
        else:
            raw_key = get_chrome_safe_storage_key()
        aes_key = derive_aes_key(raw_key)
        print("    ✅  Encryption key retrieved and AES key derived.\n")
    except RuntimeError as e:
        print(f"    ❌  {e}\n")
        return

    # 2. Find profiles
    print("📂  Scanning for Chrome profiles...")
    try:
        profiles = find_chrome_profiles()
    except RuntimeError as e:
        print(f"    ❌  {e}\n")
        return

    if not profiles:
        print("    ❌  No Chrome profiles with saved passwords found.\n")
        return

    print(f"    ✅  Found {len(profiles)} profile(s):\n")
    for name, path in profiles:
        print(f"        • {name}  ({path.name})")
    print()

    # 3. Extract from all profiles
    all_entries = []
    total_failed = 0

    for profile_name, profile_dir in profiles:
        print(f"    ⏳  Extracting: {profile_name} ...", end=' ', flush=True)
        try:
            entries = extract_from_profile(profile_name, profile_dir, aes_key)
            all_entries.extend(entries)
            print(f"{len(entries):,} entries")
        except Exception as e:
            print(f"FAILED — {e}")
            total_failed += 1

    print()

    if not all_entries:
        print("❌  No password entries found across all profiles.")
        return

    # 4. Deduplicate (same url + username across profiles)
    seen = set()
    unique_entries = []
    duplicates = 0
    for e in all_entries:
        key = (e['url'].lower(), e['username'].lower(), e['password'])
        if key not in seen:
            seen.add(key)
            unique_entries.append(e)
        else:
            duplicates += 1

    # 5. Safe mode — print anonymized summary, no file written
    if not args.show_sensitive:
        print("═" * 52)
        print(f"  🔒  SAFE MODE SUMMARY")
        print(f"  Total entries found     : {len(all_entries):,}")
        print(f"  Duplicates removed      : {duplicates:,}")
        print(f"  Unique entries          : {len(unique_entries):,}")
        print("═" * 52)
        print()
        print("  Sample (first 10 entries, anonymized):")
        print()
        print(f"  {'PROFILE':<20} {'URL':<35} {'USERNAME':<20} {'PASSWORD'}")
        print(f"  {'-'*20} {'-'*35} {'-'*20} {'-'*14}")
        for e in unique_entries[:10]:
            a = anonymize_entry(e)
            print(f"  {a['profile']:<20} {a['url']:<35} {a['username']:<20} {a['password']}")
        print()
        if len(unique_entries) > 10:
            print(f"  ... and {len(unique_entries) - 10:,} more entries (not shown).")
        print()
        print("  ✅  Safe mode complete. No file was written.")
        print("      Run with --show-sensitive to export the full plaintext CSV.\n")
        return

    # ─── --show-sensitive mode: write CSV ───
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_path = Path.home() / 'Desktop' / f'chrome_passwords_{timestamp}.csv'

    fieldnames = ['source', 'profile', 'url', 'username', 'password',
                  'date_created', 'date_last_used', 'times_used', 'notes']

    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(unique_entries)

    # Restrict file permissions to owner read/write only
    os.chmod(output_path, 0o600)

    # ─── Summary ───
    print("═" * 52)
    print(f"  ✅  Total entries extracted : {len(all_entries):,}")
    print(f"  🔁  Duplicates removed      : {duplicates:,}")
    print(f"  📄  Unique entries saved    : {len(unique_entries):,}")
    if total_failed:
        print(f"  ⚠️   Profiles that failed   : {total_failed}")
    print("═" * 52)
    print()
    print(f"  📁  Output file:")
    print(f"      {output_path}")
    print()
    print("  ⚠️   SECURITY — DO THIS NOW:")
    print("  ─────────────────────────────────────────────")
    print("  1. Import the CSV into your password manager")
    print("     (1Password / Bitwarden / etc.)")
    print()
    print("  2. Securely delete the CSV when done:")
    print(f"     rm -P \"{output_path}\"")
    print()
    print("  3. Do NOT email, AirDrop, or sync this file")
    print("     anywhere before deleting it.")
    print()


if __name__ == '__main__':
    main()
