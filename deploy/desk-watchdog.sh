#!/bin/bash
# Local uptime watchdog for Options Edge Desk + Cloudflare tunnel.
# Runs every 2 minutes via desk-watchdog.timer. Log: journalctl -t desk-watchdog
set -eu

log() { logger -t desk-watchdog "$*"; echo "$*"; }

code_local() {
  curl -sS -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:8080/healthz 2>/dev/null || echo 000
}

# --- edge-desk ---
if ! systemctl is-active --quiet edge-desk; then
  log "edge-desk inactive — restarting"
  systemctl restart edge-desk || true
  sleep 4
fi

LOCAL="$(code_local)"
if [ "$LOCAL" != "200" ]; then
  sleep 3
  LOCAL="$(code_local)"
fi
if [ "$LOCAL" != "200" ]; then
  log "local healthz=$LOCAL — restarting edge-desk"
  systemctl restart edge-desk || true
  sleep 5
  LOCAL="$(code_local)"
  if [ "$LOCAL" != "200" ]; then
    log "healthz still $LOCAL — stop, free :8080, start"
    systemctl stop edge-desk || true
    fuser -k 8080/tcp >/dev/null 2>&1 || true
    sleep 2
    systemctl start edge-desk || true
    sleep 5
    LOCAL="$(code_local)"
  fi
  log "after restart healthz=$LOCAL"
fi

# --- cloudflared ---
if ! systemctl is-active --quiet cloudflared; then
  log "cloudflared inactive — restarting"
  systemctl restart cloudflared || true
  sleep 4
fi

# Soft public check (do not restart on CF-only blips unless local is OK and public fails twice)
PUB="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 12 https://deskapi.ravindra-devireddy.com/healthz 2>/dev/null || echo 000)"
if [ "$LOCAL" = "200" ] && [ "$PUB" != "200" ]; then
  sleep 5
  PUB="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 12 https://deskapi.ravindra-devireddy.com/healthz 2>/dev/null || echo 000)"
  if [ "$PUB" != "200" ]; then
    log "public healthz=$PUB (local OK) — restarting cloudflared"
    systemctl restart cloudflared || true
  fi
fi

log "ok local=$LOCAL public=$PUB"
