#!/bin/bash
# Bring the device's model back after it died (#640). Operator asset shared by the ZGX Nano, the ZGX Fury and generic
# machines, run every minute by aware-care-zrt-watchdog.timer (user unit, infra/<device>/zrt/), installed by
# `./demo.sh model` beside serve-model.sh in ~/.local/share/aware-care-demo/zrt/. It does not change ZRT, CUDA or
# drivers. aware-care-zrt-model.service is a oneshot (RemainAfterExit=yes): it asks ZRT to serve the model and stays
# "active", so when the model dies later (a vLLM crash, a ZRT reinstall or update, a GPU error) nothing else notices.
#
# It restarts the model unit (systemctl --user restart --no-block) only when all of these hold:
#   1. the unit is meant to run: enabled and active (a unit stopped or disabled on purpose, by ./demo.sh stop or
#      uninstall or systemctl --user stop, is inactive or disabled and never started), and active for at least
#      AWARECARE_WATCHDOG_GRACE seconds (default 300: a model that was just started may still be loading);
#   2. ZRT's proxy (the address serve-model.sh checks: AWARECARE_ZRT_URL, else the port `zrt config get proxy.port`
#      names, else 8080) does not list the model under any of its names;
#   3. no ZRT service process for the model is alive (`zrt services`; #636: ZRT 0.43 shows a loading service as Dead
#      while its process lives), so it never starts a second copy; when `zrt services` does not answer, it waits;
#   4. no restart is under way (the unit is then activating, not active) and it has not given up: after 3 restarts
#      within an hour it logs that it gives up and leaves the model alone until ZRT lists the model again or a person
#      runs ./demo.sh model (which clears the state file).
# State: watchdog.state beside this script, one line per event ("restart <epoch>", "gaveup <epoch>", "cleared
# <epoch>" once the model is served again). Every run logs
# its decision in one line to the journal (journalctl --user -u aware-care-zrt-watchdog.service).
# It takes no model lock: it restarts only a model that is neither served nor alive, so no AI job is using it.
# The model and its label: AWARECARE_MODEL_URI and AWARECARE_MODEL_LABEL (generic machines; model.env, the unit's
# EnvironmentFile), else the MODEL= and LABEL= lines of serve-model.sh beside this script (Nano, Fury);
# AWARECARE_MODEL_REVISION and AWARECARE_ZRT_MODE as serve-model.sh reads them.
set -uo pipefail
export PATH=$PATH:/snap/bin
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
UNIT=aware-care-zrt-model.service
STATE=${AWARECARE_WATCHDOG_STATE:-$HERE/watchdog.state}
GRACE=${AWARECARE_WATCHDOG_GRACE:-300}
MAX=3 WINDOW=3600
log() { echo "watchdog: $*"; }

MODEL=${AWARECARE_MODEL_URI:-$(sed -n 's/^MODEL=\(hf:.*\)$/\1/p' "$HERE/serve-model.sh" 2>/dev/null | head -n1)}
LABEL=${AWARECARE_MODEL_LABEL:-$(sed -n 's/^LABEL=//p' "$HERE/serve-model.sh" 2>/dev/null | head -n1)}
if [ -z "$MODEL" ] || [ -z "$LABEL" ]; then log "no model named (serve-model.sh or model.env); nothing to watch"; exit 0; fi
[ -z "${AWARECARE_MODEL_REVISION:-}" ] || MODEL=${MODEL%@*}@$AWARECARE_MODEL_REVISION
REPO=${MODEL#hf:}; REPO=${REPO%@*}
ZRT=(zrt)
[ -z "${AWARECARE_ZRT_MODE:-}" ] || ZRT+=(-m "$AWARECARE_ZRT_MODE")
zrt_url() {  # as serve-model.sh
  local port
  if [ -n "${AWARECARE_ZRT_URL:-}" ]; then echo "${AWARECARE_ZRT_URL%/}"; return; fi
  port=$(timeout 10 "${ZRT[@]}" config get proxy.port 2>/dev/null | tr -d '[:space:]') || port=""
  case "$port" in ''|*[!0-9]*) port=8080 ;; esac
  echo "http://127.0.0.1:$port/v1"
}
served() {  # ZRT's proxy lists the model under any of its names (serve-model.sh's rule)
  local names
  names="(hf:)?($(printf '%s|%s' "$LABEL" "$REPO" | sed 's/[.]/[.]/g'))(@[^\"]*)?"
  curl -sf --noproxy '*' -m 10 "$(zrt_url)/models" 2>/dev/null | grep -iqE "\"id\": *\"$names\""
}
# service_pids: the PID of each `zrt services` row that names the model (its URI or served name, on the row or its
# continuation lines). A row starts with a cell beginning hf:; the PID is the cell before it (both of ZRT's layouts).
service_pids() {
  local out
  out=$(timeout 30 "${ZRT[@]}" services 2>/dev/null) || return 1
  awk -F'│' -v repo="$(tr '[:upper:]' '[:lower:]' <<< "$REPO")" -v label="$(tr '[:upper:]' '[:lower:]' <<< "$LABEL")" '
    function flush() { if (pid != "" && (index(text, repo) || index(text, label))) print pid; pid = ""; text = "" }
    {
      for (i = 2; i < NF; i++) {
        c = $i; gsub(/^[ \t]+|[ \t]+$/, "", c)
        if (tolower(substr(c, 1, 3)) == "hf:") {
          flush(); p = $(i - 1); gsub(/[ \t]/, "", p)
          if (p ~ /^[0-9]+$/) pid = p
          break
        }
      }
      if (pid != "") text = text " " tolower($0)
    }
    END { flush() }' <<< "$out"
}
count_recent() { awk -v since=$(($(date +%s) - WINDOW)) '$1 == "restart" && $2 >= since { n++ } END { print n + 0 }' "$STATE" 2>/dev/null || echo 0; }
gave_up() { [ "$(awk '{ last = $1 } END { print last }' "$STATE" 2>/dev/null)" = gaveup ]; }  # the last event

enabled=$(systemctl --user is-enabled "$UNIT" 2>/dev/null)
active=$(systemctl --user is-active "$UNIT" 2>/dev/null)
if [ "$enabled" != enabled ] || [ "$active" != active ]; then
  log "$UNIT is ${enabled:-not installed}, ${active:-unknown}: not meant to run (or starting); leaving it"; exit 0
fi
if served; then
  if gave_up; then echo "cleared $(date +%s)" >> "$STATE"; log "$LABEL is served again; restarts allowed again"
  else log "$LABEL is served; nothing to do"; fi
  exit 0
fi
since=$(systemctl --user show -p ActiveEnterTimestamp --value "$UNIT" 2>/dev/null)
since=$(date -d "$since" +%s 2>/dev/null) || since=0
if [ $(($(date +%s) - since)) -lt "$GRACE" ]; then
  log "$LABEL is not listed, but $UNIT started less than ${GRACE}s ago (still loading?); waiting"; exit 0
fi
if ! pids=$(service_pids); then log "$LABEL is not listed and zrt services does not answer; waiting"; exit 0; fi
for pid in $pids; do
  if ps -p "$pid" >/dev/null 2>&1; then log "$LABEL is not listed, but its ZRT service process $pid is alive (loading?); waiting"; exit 0; fi
done
if gave_up; then log "$LABEL is not served; gave up earlier ($MAX restarts within an hour): run ./demo.sh model"; exit 0; fi
n=$(count_recent)
if [ "$n" -ge "$MAX" ]; then
  echo "gaveup $(date +%s)" >> "$STATE"
  log "$LABEL is not served after $n restarts within an hour; giving up: leaving it alone until it is served again or someone runs ./demo.sh model"
  exit 0
fi
log "$LABEL is not served and no ZRT service process for it is alive; restarting $UNIT (restart $((n + 1)) of $MAX within an hour)"
echo "restart $(date +%s)" >> "$STATE"
systemctl --user restart --no-block "$UNIT" || { log "systemctl --user restart $UNIT failed"; exit 1; }
