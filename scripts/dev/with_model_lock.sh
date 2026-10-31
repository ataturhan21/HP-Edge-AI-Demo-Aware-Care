#!/usr/bin/env bash
# with_model_lock.sh <command...> : run one AI job against this device's model, one at a time (#544).
#
# The device model serves one request at a time (max-num-seqs 1), so parallel AI jobs only queue behind each other
# and slow each other down (release smoke times doubled while an AI harness ran). Every AI job on a device takes this
# lock: scripts/ai_regression/run.sh (the Fury takes it on the Fury), ./demo.sh check-model, the release smoke of the
# local device, and any harness an agent runs (`scripts/dev/with_model_lock.sh python3 evidence/.../run.py ...`).
#
# Lock file: $AWARE_CARE_MODEL_LOCK, default /tmp/aware-care-model.lock: one file for the whole device, so it covers
# every user of the model (a per-user ~/.cache lock would not see another user's job). It is created mode 0666 and
# only ever opened read-only (no O_CREAT on an existing file), so the sticky /tmp's protected_regular rule does not
# stop a second user. The lock is the kernel's flock, held through a descriptor that the command inherits: it is
# released when the wrapper and the command have both exited, also on a failure or a kill (#566). The command runs in
# its own process group, with this shell's standard input; a SIGTERM, SIGINT or SIGHUP to the wrapper is passed on to
# that whole group, and the wrapper waits for the command and returns its status. A SIGKILLed wrapper cannot pass it
# on, but the running command keeps the lock until it ends (so does any background child it leaves behind).
# While waiting it prints "waiting for the model (another AI job is running: <pid> <command>)" with the elapsed time;
# it gives up after $AWARE_CARE_MODEL_LOCK_WAIT seconds (default 3600) with exit 75. Nested use (a locked command that
# runs another locked command) does not wait for itself: $AWARE_CARE_MODEL_LOCK_HELD names the lock already held.
#
# Sourced (`. scripts/dev/with_model_lock.sh`), it only defines model_lock_acquire: the calling shell then holds the
# lock until it exits.

MODEL_LOCK_FILE=${AWARE_CARE_MODEL_LOCK:-/tmp/aware-care-model.lock}

model_lock_holder() {  # "<pid> <command>" of the job holding the lock (each user records its own holder file)
  local f pid rest
  for f in "$MODEL_LOCK_FILE".holder.*; do
    read -r pid rest < "$f" 2>/dev/null || continue
    [ -n "$pid" ] && [ -d "/proc/$pid" ] && { echo "$pid $rest"; return 0; }
  done
  echo "unknown"
}

# model_lock_acquire [description]: take the lock on a descriptor of this shell (MODEL_LOCK_FD) and record this
# shell's pid and the description for whoever waits next; 0 on success, 75 on a timeout.
model_lock_acquire() {
  local wait=${AWARE_CARE_MODEL_LOCK_WAIT:-3600} step=${AWARE_CARE_MODEL_LOCK_STEP:-30} start=$SECONDS left
  if [ "${AWARE_CARE_MODEL_LOCK_HELD:-}" = "$MODEL_LOCK_FILE" ]; then MODEL_LOCK_FD=""; return 0; fi
  if [ ! -e "$MODEL_LOCK_FILE" ]; then
    mkdir -p "$(dirname "$MODEL_LOCK_FILE")"
    (umask 000; : >> "$MODEL_LOCK_FILE") 2>/dev/null
    chmod 0666 "$MODEL_LOCK_FILE" 2>/dev/null
  fi
  exec {MODEL_LOCK_FD}<"$MODEL_LOCK_FILE" || { echo "model lock: cannot open $MODEL_LOCK_FILE" >&2; return 75; }
  if ! flock -n "$MODEL_LOCK_FD"; then
    while :; do
      echo "waiting for the model (another AI job is running: $(model_lock_holder)) $((SECONDS - start)) s" >&2
      left=$(( wait - (SECONDS - start) ))
      if [ "$left" -le 0 ]; then
        echo "model lock: gave up after $((SECONDS - start)) s waiting for the model ($MODEL_LOCK_FILE, held by" \
          "$(model_lock_holder)); wait for that job or raise AWARE_CARE_MODEL_LOCK_WAIT" >&2
        exec {MODEL_LOCK_FD}<&-; return 75
      fi
      flock -w "$(( left < step ? left : step ))" "$MODEL_LOCK_FD" && break
    done
    echo "model lock: acquired after $((SECONDS - start)) s" >&2
  fi
  echo "$$ ${1:-$(ps -o args= -p $$ 2>/dev/null)}" | cut -c1-160 > "$MODEL_LOCK_FILE.holder.$(id -u)" 2>/dev/null
  export AWARE_CARE_MODEL_LOCK_HELD=$MODEL_LOCK_FILE
  return 0
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  set -uo pipefail
  [ $# -gt 0 ] || { awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0" >&2; exit 2; }
  model_lock_acquire "$*" || exit $?
  if [ -z "$MODEL_LOCK_FD" ]; then exec "$@"; fi
  # #566: the command in its own process group (job control on), keeping stdin (a background command would otherwise
  # read /dev/null) and the lock descriptor; a signal to this wrapper goes to the whole group, then the wrapper waits.
  # #614: SIGCONT follows it, so a stopped job gets it too. On a terminal where this wrapper runs in the foreground,
  # the job's group gets the terminal while it runs (a background group is stopped by its first read of the terminal,
  # SIGTTIN, and the lock would stay held), and Ctrl-C then reaches the job directly; the terminal returns afterwards.
  job=""
  # shellcheck disable=SC2317,SC2329  # called indirectly from the signal traps below
  pass_on() {
    if [ -n "$job" ]; then kill -s "$1" -- "-$job" 2>/dev/null; kill -s CONT -- "-$job" 2>/dev/null
    else exit $((128 + $2)); fi
  }
  # tty_fg <process group>: make it the terminal's foreground group (python3: bash has no tcsetpgrp); quiet when it can't
  tty_fg() {
    python3 -c 'import os, signal, sys
signal.signal(signal.SIGTTOU, signal.SIG_IGN)
os.tcsetpgrp(0, int(sys.argv[1]))' "$1" 2>/dev/null
  }
  trap 'pass_on TERM 15' TERM
  trap 'pass_on INT 2' INT
  trap 'pass_on HUP 1' HUP
  term_fg=""
  if [ -t 0 ]; then
    # the terminal's foreground group, only when it is this wrapper's own (never take the terminal from another job)
    term_fg=$(python3 -c 'import os; print(os.tcgetpgrp(0) if os.tcgetpgrp(0) == os.getpgrp() else "")' 2>/dev/null) \
      || term_fg=""
  fi
  set -m
  "$@" <&0 &
  job=$!
  set +m
  if [ -n "$term_fg" ] && tty_fg "$job"; then kill -s CONT -- "-$job" 2>/dev/null; else term_fg=""; fi
  while :; do
    wait "$job"; rc=$?
    kill -0 "$job" 2>/dev/null || break  # still running: wait returned for a signal that was passed on
  done
  [ -z "$term_fg" ] || tty_fg "$term_fg"
  exit "$rc"
fi
