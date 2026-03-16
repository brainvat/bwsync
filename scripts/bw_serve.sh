#!/usr/bin/env bash
# bw_serve.sh — start/stop helper for `bw serve`
#
# USAGE:
#   ./scripts/bw_serve.sh start    # Start bw serve on port 8087
#   ./scripts/bw_serve.sh stop     # Stop bw serve
#   ./scripts/bw_serve.sh status   # Check if bw serve is running
#
# REQUIRES:
#   - Bitwarden CLI installed: brew install bitwarden-cli
#   - BW_SESSION env var set: export BW_SESSION=$(bw unlock --raw)

set -euo pipefail

PORT="${BW_PORT:-8087}"
PID_FILE="/tmp/bw_serve.pid"

start() {
    if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
        echo "bw serve is already running (PID $(cat "$PID_FILE")) on port $PORT"
        return 0
    fi

    if [[ -z "${BW_SESSION:-}" ]]; then
        echo "ERROR: BW_SESSION is not set."
        echo "  Run: export BW_SESSION=\$(bw unlock --raw)"
        exit 1
    fi

    echo "Starting bw serve on port $PORT..."
    bw serve --port "$PORT" &
    local pid=$!
    echo "$pid" > "$PID_FILE"
    sleep 2

    if kill -0 "$pid" 2>/dev/null; then
        echo "bw serve started (PID $pid) on port $PORT"
    else
        echo "ERROR: bw serve failed to start"
        rm -f "$PID_FILE"
        exit 1
    fi
}

stop() {
    if [[ -f "$PID_FILE" ]]; then
        local pid
        pid=$(cat "$PID_FILE")
        if kill -0 "$pid" 2>/dev/null; then
            echo "Stopping bw serve (PID $pid)..."
            kill "$pid"
            rm -f "$PID_FILE"
            echo "Stopped."
        else
            echo "bw serve is not running (stale PID file removed)"
            rm -f "$PID_FILE"
        fi
    else
        echo "bw serve is not running (no PID file)"
    fi
}

status() {
    if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
        echo "bw serve is running (PID $(cat "$PID_FILE")) on port $PORT"
    else
        echo "bw serve is not running"
    fi
}

case "${1:-}" in
    start)  start ;;
    stop)   stop ;;
    status) status ;;
    *)
        echo "Usage: $0 {start|stop|status}"
        exit 1
        ;;
esac
