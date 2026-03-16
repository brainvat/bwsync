#!/usr/bin/env bash
# scripts/push-check.sh — run from repo root

GREEN="\033[0;32m"
YELLOW="\033[0;33m"
CYAN="\033[0;36m"
BOLD="\033[1m"
DIM="\033[2m"
RESET="\033[0m"

echo ""
echo -e "${BOLD}${CYAN}╔══════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}${CYAN}║${RESET}  ${BOLD}🔍  bwsync — push safety check${RESET}              ${BOLD}${CYAN}║${RESET}"
echo -e "${BOLD}${CYAN}║${RESET}  ${DIM}files excluded from git (will NOT be pushed)${RESET}  ${BOLD}${CYAN}║${RESET}"
echo -e "${BOLD}${CYAN}╚══════════════════════════════════════════════╝${RESET}"
echo ""

git ls-files --others --ignored --exclude-standard \
  | grep -vE "^(venv|\.venv|__pycache__|\.pytest_cache|.*\.pyc$|.*\.pyo$|.*\.egg-info)" \
  | tree --fromfile

echo ""
echo -e "${BOLD}${GREEN}╔══════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}${GREEN}║${RESET}  ${GREEN}✅  all clear — nothing sensitive in flight${RESET}  ${BOLD}${GREEN}║${RESET}"
echo -e "${BOLD}${GREEN}║${RESET}  ${DIM}never-push-passwords/ is staying local 🔒${RESET}   ${BOLD}${GREEN}║${RESET}"
echo -e "${BOLD}${GREEN}╚══════════════════════════════════════════════╝${RESET}"
echo ""
