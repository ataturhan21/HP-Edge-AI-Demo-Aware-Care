#!/usr/bin/env bash
# AI regression set (#509): about 60 synthetic cases (cases.json) through the app API in local mode against each
# device's own ZRT model, once per device (the app calls the model at temperature 0, so no repeats). Required before
# merging any change to prompts, output validation or repair; the full qualification set is only for major prompt
# rewrites.
#
#   scripts/ai_regression/run.sh <nano|fury|both|here> [--only ID,ID]
#
# - nano: runs here (this host is the ZGX Nano) against ZRT on 127.0.0.1:8080, model qwen3.6-35b-a3b-fp8.
# - fury: copies this worktree's files (tracked and modified, no .git, no node_modules) to
#   ~/aware-care-qual/repo-ai-regression on the ZGX Fury, syncs its API environment with ~/aware-care-qual/bin/uv,
#   runs there against the Fury's ZRT on its loopback, model qwen3.6-35b-a3b-fp8 (#646: the Nano's), and copies the report back.
# - both: the two devices in parallel.
# - here (#537, `./demo.sh check-model`): this machine, whatever it is, against ZRT at $AI_REGRESSION_ZRT_URL (default
#   http://127.0.0.1:8080/v1) and the served model $AI_REGRESSION_MODEL (required: the ID ZRT serves). The API takes
#   that model's manifest from the catalogue (infra/models/catalog.json) by its label.
# Nothing is deployed and no device setting changes: the API runs in this process tree with a throwaway data
# directory (run_cases.py). Reports: $AI_REGRESSION_OUT (default /tmp/ai-regression-<time>)/<device>.json.
#
# Advisory (ADR-019): the table marks a device FAIL when any of these fails, but the run still exits 0: 100% urgent recall (red-flag screen and urgent journeys), no medicine instruction
# published, every expected publish published (G08 in both context orders, #407's phrasings repaired, the journeys),
# every health concern accepted. False alarms and non-health refusals are shown as WARN (advisory).
# Exit 2: a device could not be reached or the run did not produce a report.
# Model lock (#544, scripts/dev/with_model_lock.sh): one AI job per device model at a time. nano/here/both hold this
# machine's lock for the whole run (it waits, with a message, while another AI job runs); the Fury's cases hold the
# Fury's own lock on the Fury (its waiting message is in fury.log).
set -uo pipefail
{ # parsed whole before it runs, so editing this file during a run cannot change the run

REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
TARGET=${1:-}; shift || true
ONLY=()
[ "${1:-}" = --only ] && [ -n "${2:-}" ] && ONLY=(--only "$2")
case "$TARGET" in nano|fury|both|here) ;; *) sed -n '2,/^set -uo/p' "$0" | grep '^#' | sed 's/^# \{0,1\}//'; exit 2 ;; esac
if [ "$TARGET" != fury ] && [ -z "${AI_REGRESSION_LOCKED:-}" ]; then
  AI_REGRESSION_LOCKED=1 exec bash "$REPO/scripts/dev/with_model_lock.sh" bash "$0" "$TARGET" "$@"
fi
OUT=${AI_REGRESSION_OUT:-/tmp/ai-regression-$(date +%Y%m%d-%H%M%S)}
mkdir -p "$OUT"

NANO_MODEL=qwen3.6-35b-a3b-fp8
HERE_MODEL=${AI_REGRESSION_MODEL:-}
HERE_URL=${AI_REGRESSION_ZRT_URL:-http://127.0.0.1:8080/v1}
FURY_MODEL=qwen3.6-35b-a3b-fp8  # #646: the Fury serves the Nano's model (ADR-018 amendment 1)
# The Fury over SSH: AI_REGRESSION_FURY_SSH=<user>@<device-host> and AI_REGRESSION_FURY_SSH_PORT (<ssh-port>, default 22).
FURY_SSH=(ssh -o BatchMode=yes -o ConnectTimeout=15 -p "${AI_REGRESSION_FURY_SSH_PORT:-22}" "${AI_REGRESSION_FURY_SSH:-<user>@<device-host>}")
FURY_DIR=aware-care-qual/repo-ai-regression

served() {  # <model list json> <model>: the expected model is served
  python3 -c 'import json,sys; ids=[m["id"] for m in json.load(sys.stdin)["data"]]; sys.exit(sys.argv[1] not in ids)' "$1"
}

run_nano() {
  local log=$OUT/nano.log
  if ! curl -sf -m 5 http://127.0.0.1:8080/v1/models | served "$NANO_MODEL"; then
    echo "nano: ZRT on 127.0.0.1:8080 does not serve $NANO_MODEL" | tee "$log"; return 2
  fi
  (cd "$REPO/apps/api" && uv sync --locked -q && AWARECARE_MODE=local AWARECARE_MODEL_ID=$NANO_MODEL \
    uv run --no-sync python ../../scripts/ai_regression/run_cases.py ../../scripts/ai_regression/cases.json \
    "$OUT/nano.json" "${ONLY[@]}") > "$log" 2>&1
}

run_here() {
  local log=$OUT/here.log
  if [ -z "$HERE_MODEL" ]; then echo "here: set AI_REGRESSION_MODEL to the model ID ZRT serves" | tee "$log"; return 2; fi
  if ! curl -sf --noproxy '*' -m 5 "$HERE_URL/models" | served "$HERE_MODEL"; then
    echo "here: ZRT on $HERE_URL does not serve $HERE_MODEL" | tee "$log"; return 2
  fi
  (cd "$REPO/apps/api" && uv sync --locked -q && AWARECARE_MODE=local AWARECARE_MODEL_ID=$HERE_MODEL \
    AWARECARE_MODEL_BASE_URL=$HERE_URL uv run --no-sync python ../../scripts/ai_regression/run_cases.py \
    ../../scripts/ai_regression/cases.json "$OUT/here.json" "${ONLY[@]}") > "$log" 2>&1
}

run_fury() {
  local log=$OUT/fury.log
  # The worktree's files as they are now (tracked and modified, untracked but not ignored), without Git metadata
  # and without what the API does not read (evidence, docs, mockups, the web app).
  if ! (cd "$REPO" && git ls-files -z --cached --others --exclude-standard -- . ':!evidence' ':!docs' ':!spec/mockups' \
        ':!apps/web' | while IFS= read -r -d '' f; do [ -e "$f" ] && printf '%s\0' "$f"; done \
        | tar --null -T - -czf "$OUT/repo.tgz" 2>/dev/null); then
    echo "fury: could not pack the worktree" | tee "$log"; return 2
  fi
  if ! "${FURY_SSH[@]}" "rm -rf ~/$FURY_DIR.new && mkdir -p ~/$FURY_DIR.new && tar --warning=no-timestamp -xzf - -C ~/$FURY_DIR.new" < "$OUT/repo.tgz"; then
    echo "fury: copy over ssh failed" | tee "$log"; return 2
  fi
  local only=""
  [ ${#ONLY[@]} -gt 0 ] && only="--only ${ONLY[1]}"
  # Keep the API environment between runs (a fresh .venv takes a minute): move it into the new copy.
  "${FURY_SSH[@]}" bash -s > "$log" 2>&1 <<EOF
set -u
cd ~
if [ -d $FURY_DIR/apps/api/.venv ]; then mv $FURY_DIR/apps/api/.venv $FURY_DIR.new/apps/api/.venv; fi
rm -rf $FURY_DIR && mv $FURY_DIR.new $FURY_DIR
curl -sf -m 5 http://127.0.0.1:8080/v1/models | grep -q '"$FURY_MODEL"' || { echo "fury: ZRT does not serve $FURY_MODEL"; exit 2; }
cd $FURY_DIR/apps/api
~/aware-care-qual/bin/uv sync --locked -q || exit 2
AWARECARE_MODE=local AWARECARE_MODEL_ID=$FURY_MODEL AWARECARE_MODEL_MANIFEST=infra/fury/model-manifest.json AWARECARE_TELEMETRY_PRICING=infra/fury/telemetry-pricing.json \
  bash ~/$FURY_DIR/scripts/dev/with_model_lock.sh ~/aware-care-qual/bin/uv run --no-sync python ../../scripts/ai_regression/run_cases.py \
  ../../scripts/ai_regression/cases.json /tmp/ai-regression-fury.json $only
EOF
  local rc=$?
  "${FURY_SSH[@]}" "cat /tmp/ai-regression-fury.json && rm -f /tmp/ai-regression-fury.json" > "$OUT/fury.json" 2>/dev/null \
    || rm -f "$OUT/fury.json"
  return "$rc"
}

start=$(date +%s)
declare -A RC SECS
devices=()
if [ "$TARGET" = here ]; then devices=(here)
else
  [ "$TARGET" != fury ] && devices+=(nano)
  [ "$TARGET" != nano ] && devices+=(fury)
fi
declare -A PIDS T0
for d in "${devices[@]}"; do
  T0[$d]=$(date +%s)
  { case "$d" in nano) run_nano ;; here) run_here ;; *) run_fury ;; esac; rc=$?; date +%s > "$OUT/$d.end"; exit "$rc"; } &
  PIDS[$d]=$!
  echo "==> $d started (log $OUT/$d.log)"
done
for d in "${devices[@]}"; do
  wait "${PIDS[$d]}"; RC[$d]=$?; SECS[$d]=$(( $(cat "$OUT/$d.end" 2>/dev/null || date +%s) - T0[$d] ))
done

echo
for d in "${devices[@]}"; do
  echo "== $d (${SECS[$d]} s, exit ${RC[$d]})"
  grep -E '^(PASS|FAIL|WARN) ' "$OUT/$d.log" || tail -n 20 "$OUT/$d.log"
  echo
done
echo "| Device | Cases | Urgent recall | Medicine instructions published | Expected publishes | Health accepted | Advisory WARN | Gate | Seconds |"
echo "|---|---|---|---|---|---|---|---|---|"
status=0
for d in "${devices[@]}"; do
  if [ ! -s "$OUT/$d.json" ]; then
    echo "| $d | - | - | - | - | - | - | NO REPORT (exit ${RC[$d]}) | ${SECS[$d]} |"; status=2; continue
  fi
  python3 - "$OUT/$d.json" "$d" "${SECS[$d]}" <<'PY'
import json, sys
s = json.load(open(sys.argv[1]))["summary"]
warn = len(s["false_alarms_advisory"]) + len(s["non_health_not_refused_advisory"])
print(f"| {sys.argv[2]} | {s['cases']} | {s['urgent_recall']} | {s['medicine_instructions_published']} | "
      f"{s['expected_publishes']} | {s['health_concerns_accepted']} | {warn} | {s['gate']} | {sys.argv[3]} |")
if s["gate_failures"]:
    print(f"|   | gate failures: {', '.join(s['gate_failures'])} |||||||| ")
PY
  gate=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["summary"]["gate"])' "$OUT/$d.json")
  [ "$gate" = PASS ] || echo "$d: advisory FAIL (put it in the PR; it does not block the merge)"
done
echo
echo "Reports: $OUT (total $(( $(date +%s) - start )) s)"
exit $status
}
