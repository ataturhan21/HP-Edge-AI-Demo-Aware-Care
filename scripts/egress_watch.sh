#!/bin/bash
# ADR-002 stage 6 sampler (#151): every second, the TCP/UDP sockets of the model processes.
#   sockets / non_loopback               connected sockets, and those whose peer is not loopback
#   listen / listen_non_loopback         listening sockets, and those bound to a non-loopback address
#   no_process                           no model process matched (the sample is not boundary evidence)
# usage: scripts/egress_watch.sh '<pgrep -f pattern of the model processes>' > egress.log   (stop it with kill)
# Read-only: socket sampling with ss, not a packet capture. `qualify_model.py gates --egress` reads the log.
# #295: the watcher's own command line contains the pattern, so its own processes (this shell, its subshells and
# the shells that started it) are excluded; before that, `no_process` was never written.
set -u
PAT=${1:?usage: egress_watch.sh <process pattern>}
LOOP='^(127\.|\[::1\]|\[::ffff:127\.)'
SELF=$$
# This shell and its ancestors (for example `bash -c 'egress_watch.sh PAT > log'`), computed once.
ANCESTORS=" $SELF "
p=$SELF
while p=$(ps -o ppid= -p "$p" 2>/dev/null | tr -d ' ') && [ -n "$p" ] && [ "$p" -gt 1 ]; do
  ANCESTORS="$ANCESTORS$p "
done

model_pids() {
  # pgrep excludes itself; drop the watcher, its ancestors and its children (command-substitution subshells).
  local pid ppid out=""
  for pid in $(pgrep -f -- "$PAT"); do
    case "$ANCESTORS" in *" $pid "*) continue ;; esac
    ppid=$(ps -o ppid= -p "$pid" 2>/dev/null | tr -d ' ')
    if [ -z "$ppid" ] || [ "$ppid" = "$SELF" ]; then continue; fi  # gone already, or our own subshell
    out="$out${out:+|}$pid"
  done
  printf '%s' "$out"
}

while true; do
  pids=$(model_pids)
  t=$(date -u +%s)
  if [ -z "$pids" ]; then echo "$t sockets=0 non_loopback=0 listen=0 listen_non_loopback=0 no_process"; sleep 1; continue; fi
  # With a state filter, `ss -tunpH` drops the State column: Netid Recv-Q Send-Q Local Peer Process (#295).
  conn=$(ss -tunpH state established 2>/dev/null | grep -E "pid=($pids),")
  # Without one, `ss -tulnpH` keeps it: Netid State Recv-Q Send-Q Local Peer Process.
  lsn=$(ss -tulnpH 2>/dev/null | grep -E "pid=($pids),")
  n_conn=$(printf '%s' "$conn" | grep -c . ); n_bad=$(printf '%s\n' "$conn" | awk 'NF{print $5}' | grep -vcE "$LOOP")
  n_lsn=$(printf '%s' "$lsn" | grep -c . ); n_lbad=$(printf '%s\n' "$lsn" | awk 'NF{print $5}' | grep -vcE "$LOOP|^\*:|^0\.0\.0\.0:|^\[::\]:")
  n_wild=$(printf '%s\n' "$lsn" | awk 'NF{print $5}' | grep -cE '^\*:|^0\.0\.0\.0:|^\[::\]:')
  echo "$t sockets=$n_conn non_loopback=$n_bad listen=$n_lsn listen_non_loopback=$((n_lbad + n_wild))"
  if [ "$n_bad" != "0" ]; then printf '%s\n' "$conn" | awk 'NF{print "  conn", $4, "->", $5}' | grep -vE " -> (127\.|\[::1\]|\[::ffff:127\.)"; fi
  if [ "$((n_lbad + n_wild))" != "0" ]; then printf '%s\n' "$lsn" | awk 'NF{print "  listen", $5}' | grep -vE "listen (127\.|\[::1\]|\[::ffff:127\.)"; fi
  sleep 1
done
