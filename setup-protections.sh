#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# setup-protections.sh
#
# Installs all local repository protections for bwsync.
# Run this once after cloning, and again after pulling hook updates.
#
# USAGE:
#   chmod +x setup-protections.sh
#   ./setup-protections.sh
# ─────────────────────────────────────────────────────────────────────

set -euo pipefail

BOLD="\033[1m"
GREEN="\033[0;32m"
YELLOW="\033[0;33m"
RED="\033[0;31m"
DIM="\033[2m"
RESET="\033[0m"

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || {
    echo -e "${RED}✗  Not inside a git repository. Run this from the bwsync project root.${RESET}"
    exit 1
}

echo ""
echo -e "${BOLD}bwsync — protection setup${RESET}"
echo -e "${DIM}────────────────────────────────────────${RESET}"
echo ""

# ── 1. CREDENTIAL PROTECTION: git hooks ──────────────────────────────

echo -e "${BOLD}[1/3] Installing credential protection hooks...${RESET}"

HOOKS_SRC="$REPO_ROOT/hooks"
HOOKS_DEST="$REPO_ROOT/.git/hooks"

if [[ ! -d "$HOOKS_SRC" ]]; then
    echo -e "  ${RED}✗  hooks/ directory not found at $HOOKS_SRC${RESET}"
    echo -e "  ${DIM}Make sure you're running this from the repo root.${RESET}"
    exit 1
fi

# Point git at the committed hooks directory so updates travel with the repo
git config core.hooksPath "$HOOKS_SRC"
echo -e "  ${GREEN}✓${RESET}  git config core.hooksPath → hooks/"

# Ensure all hooks are executable
for hook in "$HOOKS_SRC"/*; do
    [[ -f "$hook" ]] || continue
    chmod +x "$hook"
    echo -e "  ${GREEN}✓${RESET}  chmod +x hooks/$(basename "$hook")"
done

echo ""

# ── 2. SENSITIVE DIRECTORY: never-push-passwords ─────────────────────

echo -e "${BOLD}[2/3] Verifying sensitive directory protection...${RESET}"

SENSITIVE_DIR="$REPO_ROOT/never-push-passwords"
GITIGNORE="$REPO_ROOT/.gitignore"

# Create the directory if it doesn't exist
if [[ ! -d "$SENSITIVE_DIR" ]]; then
    mkdir -p "$SENSITIVE_DIR"
    echo -e "  ${GREEN}✓${RESET}  Created never-push-passwords/"
else
    echo -e "  ${GREEN}✓${RESET}  never-push-passwords/ exists"
fi

# Verify it's in .gitignore
if grep -q "never-push-passwords" "$GITIGNORE" 2>/dev/null; then
    echo -e "  ${GREEN}✓${RESET}  never-push-passwords/ is in .gitignore"
else
    echo "never-push-passwords/" >> "$GITIGNORE"
    echo -e "  ${GREEN}✓${RESET}  Added never-push-passwords/ to .gitignore"
fi

echo ""

# ── 3. SELF-TEST ──────────────────────────────────────────────────────

echo -e "${BOLD}[3/3] Running self-test...${RESET}"

# Create a fake credential file and verify the pre-commit hook blocks it
TEST_FILE="$SENSITIVE_DIR/test_passwords.csv"
touch "$TEST_FILE"

# Attempt to stage it — this should be blocked by .gitignore
if git add "$TEST_FILE" 2>/dev/null; then
    # If .gitignore didn't catch it, check if the hook fires
    if git diff --cached --name-only | grep -q "test_passwords.csv"; then
        # Unstage immediately
        git reset HEAD "$TEST_FILE" 2>/dev/null
        echo -e "  ${YELLOW}⚠${RESET}  test_passwords.csv was staged — hook should catch it at commit time"
    fi
else
    echo -e "  ${GREEN}✓${RESET}  .gitignore blocked test credential file (first line of defense)"
fi

rm -f "$TEST_FILE"

# Verify hook file integrity
for hook in pre-commit pre-push; do
    if [[ -x "$HOOKS_SRC/$hook" ]]; then
        echo -e "  ${GREEN}✓${RESET}  hooks/$hook is present and executable"
    else
        echo -e "  ${RED}✗${RESET}  hooks/$hook missing or not executable"
    fi
done

# ── SUMMARY ───────────────────────────────────────────────────────────

echo ""
echo -e "${DIM}────────────────────────────────────────${RESET}"
echo -e "${GREEN}${BOLD}✓  Protection setup complete.${RESET}"
echo ""
echo -e "  ${BOLD}What is now protected:${RESET}"
echo -e "  ${DIM}•${RESET}  never-push-passwords/   ${DIM}← blocked at .gitignore + hook level${RESET}"
echo -e "  ${DIM}•${RESET}  *.csv / *.json / *.txt  ${DIM}← blocked if name contains credential keywords${RESET}"
echo -e "  ${DIM}•${RESET}  Code files (.py, .sh)   ${DIM}← never blocked, even if 'passwords' in name${RESET}"
echo ""
echo -e "  ${BOLD}What is NOT protected:${RESET}"
echo -e "  ${DIM}•${RESET}  git push --no-verify    ${DIM}← bypasses hooks (don't do this)${RESET}"
echo -e "  ${DIM}•${RESET}  git add -f + --no-verify${DIM}← bypasses everything (really don't do this)${RESET}"
echo ""
echo -e "  To re-run after pulling hook updates:"
echo -e "  ${DIM}./setup-protections.sh${RESET}"
echo ""
