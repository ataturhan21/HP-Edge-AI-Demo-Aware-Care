#!/usr/bin/env bash
# demo.sh: run the Aware Care demo with one command (#525) on an HP ZGX Nano, a ZGX Fury or, #537, any NVIDIA Linux
# machine (the model is chosen from infra/models/catalog.json by the GPU memory found here).
#
#   ./demo.sh setup             #549: everything after the clone, in order, each step skipped when it is done: the doctor
#                               checks, the model (served through ZRT), the build and deploy, the tunnel and the URL;
#                               --mock: mock mode instead. `./demo.sh` alone asks once on a terminal, then runs setup
#   ./demo.sh mock              try it: no model, no Docker (development servers, scripted synthetic results)
#   ./demo.sh local             real on-device AI: checks, builds the images, deploys the two containers; #678: keeps
#                               the GPU power sampler running for the telemetry page (a user crontab line)
#   ./demo.sh model             serve this machine's model with ZRT: a copy ZRT already has (any revision), else
#                               it downloads the pinned revision (once; 10 to 40 GB); #640: with the unit, its
#                               watchdog (a timer that restarts the unit when the model died)
#   ./demo.sh doctor            what this machine has (GPUs, memory, CUDA, ZRT) and which model it will use
#   ./demo.sh check-model       the advisory AI regression set against the model this machine serves
#   ./demo.sh status            what runs, which commit or tag, which model ZRT serves
#   ./demo.sh open              #695: the tunnel command and the address of the demo that runs here, at any time
#   ./demo.sh fresh             #698: back up the data, uninstall --all (never the model) and set up again
#   ./demo.sh update [<tag>]    check out a release tag (default: the latest v*), then rerun mock or local
#   ./demo.sh stop [mock|local] stop the app (data kept); #644: whoever's it is (there is no main instance)
#   ./demo.sh uninstall         stop and remove the app, its data, images, the model unit and its watchdog, and the power
#                               sampler's crontab line (asks first)
#   ./demo.sh uninstall --all   everything demo.sh added on this machine, to start from scratch (--with-model: the
#                               downloaded model too); Docker, ZRT and the checkout stay
#
# Options: --port <n>, --device nano|fury|auto, --model <label>, --zrt-url <url>, --zrt-port <n>,
# --zrt-mode user|system, --revision <rev>, --timeout <time>, --instance <name>, --api-port <n>, --web-port <n>, --all,
# --with-model, --mock, --rebuild, --replace, --dry-run, --yes, --no-color, -h/--help (see help()). --dry-run holds for every command: it prints what it would do
# and changes nothing (no fetch, checkout, docker, systemctl, kill, rm or report).
#
# Machines (#537): apps/api/app/runtime/hardware.py reads the GPUs (nvidia-smi), memory (/proc/meminfo; a GB10's is
# unified), the DMI product name, CUDA and the architecture, then picks the first catalogue entry this machine can
# hold. A GB10 and a GB300 keep the Nano's and the Fury's qualified scripts, units and deploy configurations unchanged;
# any other machine gets the generic serve script and unit (infra/generic/zrt/) and deploy configuration
# (infra/deploy/demo-generic.json) with its own name, a detected inventory, neutral prices and images built for its
# architecture (linux/amd64 or linux/arm64). Every zrt call gets -m <mode>: --zrt-mode, else AWARECARE_ZRT_MODE, else
# `zrt config get mode`, else system (ZRT's default).
#
# ZRT's address (#535, #549: any loopback port): --zrt-url, else --zrt-port <n> (http://127.0.0.1:<n>/v1), else
# AWARECARE_ZRT_URL, else ZRT's proxy on the port ZRT is set to (`zrt config get proxy.port`), else 8080. The deploy
# tool gets the same address (--zrt-base-url), and so does the API; the model unit's serve script reads the same port.
# When it does not list the device's model and neither --zrt-url nor --zrt-port was given, a Ready ZRT service for
# the model with its own loopback endpoint (`zrt services`) that lists it is used instead, with a note.
#
# Output (#533, #648: one scheme): a header with the checked-out commit or tag, then sections (Checks, Model, Build,
# Deploy, Open it) separated by blank lines, one line per step: a green ✓ done; a yellow ! with its fix in plain words
# (Fix:); a red ✗ that says what happened, why, and the command that fixes it (Run:); → a long step; dim lines for
# detail. Color only on a terminal (--no-color or NO_COLOR turn it off, FORCE_COLOR turns it on), so tests and logs
# get the same text without it; the elapsed-time indicator only on a terminal. Details go to a log file under runtime-data/demo-logs/; a failed step prints its path and last
# lines. It never runs a GitHub workflow.
#
# A second local instance with its own containers, data and device ports: --instance, --api-port and --web-port (or
# AWARECARE_DEMO_INSTANCE, AWARECARE_DEMO_API_PORT and AWARECARE_DEMO_WEB_PORT); its data goes to
# ~/.local/share/<instance> unless AWARECARE_DEMO_DATA_ROOT says otherwise.
set -uo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
cd "$ROOT" || exit 1
LOG_DIR=${AWARECARE_DEMO_LOG_DIR:-$ROOT/runtime-data/demo-logs}
MOCK_STATE="$LOG_DIR/mock.state"
ZRT_URL=http://127.0.0.1:8080/v1  # zrt_address sets it (#549)
ZRT_URL_ENV=${AWARECARE_ZRT_URL:-}
ZRT_URL_OPT=""  # --zrt-url: used as given, no discovery
ZRT_PORT_OPT="" # --zrt-port: ZRT's proxy on that loopback port, no discovery
ZRT_URL_FROM="" ZRT_CONFIG_PORT=""  # where ZRT_URL came from; the port `zrt config get proxy.port` names
ZRT_FOUND=""    # set when ZRT_URL is a service endpoint found in `zrt services` instead of the configured address
ZRT_FOUND_ON="" # #632: "port" when it was found on another listening loopback port instead
ZRT_HOME=${AWARECARE_ZRT_HOME:-/opt/hp/zrt}  # ZRT's system-mode home: proxy.json and the model cache (models/)
PROBE_URL=${AWARECARE_DEMO_PROBE_URL:-https://ghcr.io/v2/}
DEFAULT_DATA_ROOT="$HOME/.local/share/aware-care-demo"
DEFAULT_INSTANCE=aware-care-demo
INSTANCE=${AWARECARE_DEMO_INSTANCE:-$DEFAULT_INSTANCE}  # --instance overrides; DATA_ROOT is set after the options
UNIT=aware-care-zrt-model.service
WD_SERVICE=aware-care-zrt-watchdog.service WD_TIMER=aware-care-zrt-watchdog.timer  # #640: the model's watchdog
READY_PATH=/api/v1/health/ready

CMD="" ARG="" PORT="" DEVICE="" DRY=0 YES=0 REVISION="" HELP=0 NO_COLOR_OPT=0 TIMEOUT="" ALL=0 WITH_MODEL=0
MODEL_OPT="" ZRT_MODE_OPT="" ZRT_MODE="" ZRT_MODE_FROM="" CHOSEN=0 MOCK_OPT=0 REBUILD=0 DOC_STRICT=0 REPLACE=0
LOG=/dev/null

# ------------------------------------------------------------------ output

# Color only on a terminal: --no-color and NO_COLOR turn it off, FORCE_COLOR turns it on (https://no-color.org).
B="" D="" RED="" GRN="" YEL="" CYN="" HEAD="" X="" SPIN=0
cap() { local v; v=$(tput "$@" 2>/dev/null) && [ -n "$v" ] && printf '%s' "$v"; }  # tput, else the ANSI fallback
setup_style() {
  local on=0
  if [ "$NO_COLOR_OPT" = 1 ]; then on=0
  elif [ -n "${FORCE_COLOR:-}" ] && [ "$FORCE_COLOR" != 0 ]; then on=1
  elif [ -n "${NO_COLOR:-}" ]; then on=0
  elif [ -t 1 ] && [ "${TERM:-dumb}" != dumb ]; then on=1; fi
  if [ "$on" = 1 ]; then
    B=$(cap bold || printf '\033[1m'); D=$(cap dim || printf '\033[2m'); X=$(cap sgr0 || printf '\033[0m')
    RED=$(cap setaf 1 || printf '\033[31m'); GRN=$(cap setaf 2 || printf '\033[32m')
    YEL=$(cap setaf 3 || printf '\033[33m'); CYN=$(cap setaf 6 || printf '\033[36m')
    HEAD="$B$(cap smul || printf '\033[4m')$(cap setaf 4 || printf '\033[34m')"  # #648: headings stand out
  fi
  # The elapsed-time indicator rewrites its line, so it runs only on a terminal.
  if [ -t 1 ] && [ "${TERM:-dumb}" != dumb ]; then SPIN=1; fi
}

# header <what> [dry]: "Aware Care · <what>" in bold, then a dim line with the commit or tag.
header() {
  local title="Aware Care · $1"
  if [ "${2:-}" = dry ] && [ "$DRY" = 1 ]; then title+=" · dry run"; fi
  printf '%s%s%s\n' "$B" "$title" "$X"
  printf '%s%s%s\n' "$D" "$(version_line)" "$X"
}
section() { printf '\n%s%s%s\n' "$HEAD" "$1" "$X"; }  # a blank line, then the section's heading
ok() { printf '  %s\342\234\223%s %s\n' "$GRN$B" "$X" "$*"; }
# note <what> [fix in plain words...] (#647): a yellow !, then its fix
note() {
  printf '  %s!%s %s\n' "$YEL$B" "$X" "$1"; shift
  local first=1 line
  for line in "$@"; do
    if [ "$first" = 1 ]; then printf '    %sFix:%s %s\n' "$YEL" "$X" "$line"; first=0; else printf '         %s\n' "$line"; fi
  done
}
doing() { printf '  %s\342\206\222%s %s\n' "$CYN$B" "$X" "$*"; }
info() { printf '    %s%s%s\n' "$D" "$*" "$X"; }  # a detail, dim
cmdline() { printf '    %s$%s %s\n' "$D" "$X" "$*"; }  # a command that a dry run prints instead of running
# err_lines <line>... (#648): the lines under a ✗: "$ <command>" is the command that fixes it (Run:, in bold), any
# other line says why, or what else to know, in plain words.
err_lines() {
  local line
  for line in "$@"; do
    case "$line" in
      '$ '*) printf '    %sRun:%s %s%s%s\n' "$RED$B" "$X" "$B" "${line#\$ }" "$X" ;;
      '> '*) printf '      %s%s%s\n' "$B" "${line#> }" "$X" ;;  # #694: a line of a block to copy as it is
      *) printf '    %s\n' "$line" ;;
    esac
  done
}
# fail <what happened> [why...] [$ <command>...]: a red ✗, why, the command that fixes it, then the log path and its last
# lines; exits 1.
fail() {
  local msg=$1 line; shift
  printf '  %s\342\234\227%s %s%s%s\n' "$RED$B" "$X" "$B" "$msg" "$X" >&2
  err_lines "$@" >&2
  if [ "$LOG" != /dev/null ] && [ -s "$LOG" ]; then
    printf '\n    %s: %s\n' "${LOG_TITLE:-Log}" "$LOG" >&2
    grep -v '^[[:space:]]*$' "$LOG" | tail -n "${TAIL_N:-10}" | while IFS= read -r line; do
      printf '    %s\342\224\202 %s%s\n' "$D" "$line" "$X" >&2
    done
  fi
  exit 1
}
start_log() {
  # #562: a dry run changes nothing, so it writes no log file either
  if [ "$DRY" = 1 ]; then LOG=/dev/null; return 0; fi
  mkdir -p "$LOG_DIR"
  LOG="$LOG_DIR/$1-$(date +%Y%m%d-%H%M%S).log"
  : > "$LOG"
}
# run <description> <command...>: runs quietly into the log (or prints it in a dry run).
run() {
  local what=$1; shift
  if [ "$DRY" = 1 ]; then cmdline "$(quote "$@")"; return 0; fi
  printf '\n$ %s\n' "$(quote "$@")" >> "$LOG"
  "$@" >> "$LOG" 2>&1 || fail "$what failed" "The last lines of its log, below, say why; fix that, then rerun:" "\$ ./demo.sh $CMD"
}
quote() { local out="" a; for a in "$@"; do out+="$(printf '%q' "$a") "; done; printf '%s' "${out% }"; }
elapsed() { if [ "$1" -ge 60 ]; then printf '%dm%02ds' $(($1 / 60)) $(($1 % 60)); else printf '%ds' "$1"; fi; }
# progress <command...>: runs a long step in the background (its output into the log) and, on a terminal, shows a
# spinner with the elapsed time. Returns the command's status and sets TOOK (the elapsed time).
# #697 (T4): with PROGRESS_HINT set to a function, its text (how far, how long left) follows the elapsed time on a terminal,
# refreshed every few seconds; without a terminal it is a dim status line every EVERY seconds (logs stay plain).
progress() {
  local start=$SECONDS pid rc i=0 frames=(⠋ ⠙ ⠹ ⠸ ⠼ ⠴ ⠦ ⠧ ⠇ ⠏) hint="" asked=-10 said=0 t
  "$@" >> "$LOG" 2>&1 < /dev/null &
  pid=$!
  # shellcheck disable=SC2064  # expand $pid now
  trap "kill $pid 2>/dev/null; echo; exit 130" INT TERM
  if [ "$SPIN" = 1 ]; then
    while kill -0 "$pid" 2>/dev/null; do
      t=$((SECONDS - start))
      if [ -n "${PROGRESS_HINT:-}" ] && [ $((t - asked)) -ge 5 ]; then hint=$("$PROGRESS_HINT" "$t"); asked=$t; fi
      printf '\r\033[K    %s%s %s%s%s' "$CYN" "${frames[i++ % 10]}" "$(elapsed "$t")" "${hint:+ · $hint}" "$X"
      sleep 0.2
    done
    printf '\r\033[K'
  elif [ -n "${PROGRESS_HINT:-}" ]; then
    while kill -0 "$pid" 2>/dev/null; do
      t=$((SECONDS - start))
      if [ $((t - said)) -ge "$EVERY" ]; then info "$(elapsed "$t"): $("$PROGRESS_HINT" "$t")"; said=$t; fi
      sleep "$POLL"
    done
  fi
  wait "$pid"; rc=$?
  trap - INT TERM
  TOOK=$(elapsed $((SECONDS - start)))
  return "$rc"
}
# long_run <description> <doing line> <command...>: run() for a long step, with a → line and the progress indicator.
long_run() {
  local what=$1 label=$2; shift 2
  if [ "$DRY" = 1 ]; then cmdline "$(quote "$@")"; return 0; fi
  doing "$label"
  printf '\n$ %s\n' "$(quote "$@")" >> "$LOG"
  progress "$@" || fail "$what failed" "The last lines of its log, below, say why; fix that, then rerun:" "\$ ./demo.sh $CMD"
}

help_rows() { while [ $# -ge 2 ]; do printf '  %s%-*s%s %s\n' "$CYN" "${HELP_W:-23}" "$1" "$X" "$2"; shift 2; done; }
help() {
  printf '%sAware Care · demo.sh%s\n' "$B" "$X"
  printf '%sRun the demo on an HP ZGX Nano, a ZGX Fury or any NVIDIA Linux machine with one command.%s\n' "$D" "$X"
  printf '%sAfter the clone: ./demo.sh setup (./demo.sh alone asks, then runs it).%s\n' "$D" "$X"
  printf '\n%sUsage%s\n  ./demo.sh <command> [options]\n' "$HEAD" "$X"
  printf '\n%sCommands%s\n' "$HEAD" "$X"
  help_rows \
    "setup" "everything after the clone: checks, model, build, deploy, tunnel; reruns skip what is done" \
    "mock" "try it: no model, no Docker (development servers, scripted synthetic results)" \
    "local" "real on-device AI: checks, builds the images, deploys the two containers" \
    "model" "serve this machine's model with ZRT (a copy ZRT has, else downloads the pinned revision)" \
    "doctor" "what this machine has (GPUs, memory, CUDA, ZRT) and which model it will use" \
    "check-model" "run the advisory AI regression set against the served model; writes a report" \
    "status" "what runs, which commit or tag, which model ZRT serves" \
    "open" "the tunnel command and the address of the demo that runs here (anyone's), at any time" \
    "update [<tag>]" "check out a release tag (default: the latest v*), then rerun mock or local" \
    "stop [mock|local]" "stop the app (data kept)" \
    "uninstall [--all]" "remove the app, its data, images, model unit, sampler (asks first); --all: all demo.sh added" \
    "fresh" "start again: back up the data, uninstall --all (never the model), then setup (asks first)"
  printf '\n%sOptions%s\n' "$HEAD" "$X"
  help_rows \
    "--port <n>" "the browser port on your computer (default 15173 for mock, 18180 for local); in mock also the" \
    "" "device's web port (default 5173)" \
    "--device nano|fury|auto" "a ZGX device's qualified model and settings (auto: detect; the default)" \
    "--model <label>" "serve this catalogue model instead of the one chosen by GPU memory" \
    "--zrt-mode user|system" "ZRT's mode (default: zrt config get mode, else system)" \
    "--zrt-url <url>" "ZRT's address on this device (default AWARECARE_ZRT_URL, else ZRT's proxy port)" \
    "--zrt-port <n>" "ZRT's proxy on this loopback port (default: zrt config get proxy.port, else 8080)" \
    "--revision <rev>" "model: serve this revision of the device's model (e.g. main), downloading it if needed" \
    "--timeout <time>" "model: stop waiting after this long (e.g. 20m). Default: 15m Nano, 8m Fury," \
    "" "then on only while the model still loads, 60m at most" \
    "--instance <name>" "a second instance, its own containers and data (~/.local/share/<name>); give" \
    "" "setup, local, status, open, stop, uninstall and fresh the same --instance" \
    "--api-port <n>" "the API's port on this device (default 8100)" \
    "--web-port <n>" "the web port on this device (default 8180)" \
    "--all" "uninstall: also the model's settings (~/.config/aware-care-demo) and demo.sh's logs" \
    "--with-model" "uninstall --all: also the downloaded model in ZRT's cache (zrt remove)" \
    "--mock" "setup: mock mode instead (no Docker, no model)" \
    "--rebuild" "setup: build and deploy again even when the app already runs this commit" \
    "--replace" "setup, local: replace the demo that runs here (anyone's): its containers go, its data stays" \
    "--dry-run" "print what it would do; changes nothing (every command)" \
    "--yes, -y" "answer yes to the uninstall or fresh question" \
    "--no-color" "plain output (NO_COLOR=1 does the same; FORCE_COLOR=1 forces color)" \
    "-h, --help" "this help"
  printf '\n%sEnvironment%s\n' "$HEAD" "$X"
  HELP_W=24 help_rows \
    "AWARECARE_DEMO_INSTANCE" "as --instance (default aware-care-demo)" \
    "AWARECARE_DEMO_DATA_ROOT" "local: the data directory (default ~/.local/share/<instance>)" \
    "AWARECARE_DEMO_API_PORT" "as --api-port" \
    "AWARECARE_DEMO_WEB_PORT" "as --web-port" \
    "AWARECARE_ZRT_URL" "ZRT's address (after --zrt-url and --zrt-port)"
  printf '\n%sLogs go to runtime-data/demo-logs/; a failed step prints its path and last lines.\n' "$D"
  printf 'It never runs a GitHub workflow.%s\n' "$X"
}

# ------------------------------------------------------------------ version

version_line() {
  local sha tag
  sha=$(git -C "$ROOT" rev-parse --short=12 HEAD 2>/dev/null || echo unknown)
  tag=$(git -C "$ROOT" describe --tags --exact-match HEAD 2>/dev/null || true)
  if [ -n "$tag" ]; then echo "$tag (commit $sha)"
  else echo "commit $sha ($(git -C "$ROOT" describe --tags 2>/dev/null || echo 'no tag'))"; fi
}
release_tag() { git -C "$ROOT" describe --tags 2>/dev/null || echo local; }
dirty() { [ -n "$(git -C "$ROOT" status --porcelain --untracked-files=no 2>/dev/null)" ]; }

# ------------------------------------------------------------------ device and model

# #537: "generic" is any other NVIDIA machine; its model is the catalogue entry hw_choose found (M_LABEL, M_HF).
device_model() { if [ "$1" = generic ]; then echo "$M_LABEL"; else sed -n 's/^LABEL=//p' "$ROOT/infra/$1/zrt/serve-model.sh"; fi; }
device_hf() {  # the pinned hf:<repo>@<revision>
  if [ "$1" = generic ]; then echo "$M_HF"; else sed -n 's/^MODEL=//p' "$ROOT/infra/$1/zrt/serve-model.sh"; fi
}
device_repo() { local r; r=$(device_hf "$1"); r=${r#hf:}; echo "${r%@*}"; }
qualified_rev() { local r; r=$(device_hf "$1"); echo "${r##*@}"; }
served_models() { curl -s --noproxy '*' -m 5 "$ZRT_URL/models" 2>/dev/null; }
model_ids() { python3 -I "$ROOT/apps/api/app/runtime/model_ids.py" "$@"; }
hardware() { python3 -I "$ROOT/apps/api/app/runtime/hardware.py" "$@"; }
find_zrt() {
  local c
  for c in "$(command -v zrt)" /snap/bin/zrt /snap/zrt/current/bin/zrt; do
    if [ -n "$c" ] && [ -x "$c" ]; then echo "$c"; return 0; fi
  done
  return 1
}

# match_model <device>: whether ZRT serves the device's model under any of its names (#528): our label, the Hugging
# Face repository id in any case, with any @revision or the hf: scheme. Sets MATCH_ID (the ID ZRT serves; the app
# uses it) and MATCH_NOTE (set when the served revision is not the qualified one, or ZRT does not say).
zrt_arg() { local z; ZRT_ARG=(); if z=$(find_zrt); then ZRT_ARG=(--zrt "$z" --zrt-mode "${ZRT_MODE:-system}"); fi; }
# zrt_mode: ZRT's mode for every zrt call (#537): --zrt-mode, AWARECARE_ZRT_MODE, `zrt config get mode`, else system.
zrt_mode() {
  [ -z "$ZRT_MODE" ] || return 0
  local z m=""
  if [ -n "$ZRT_MODE_OPT" ]; then ZRT_MODE=$ZRT_MODE_OPT ZRT_MODE_FROM="--zrt-mode"; return 0; fi
  if [ -n "${AWARECARE_ZRT_MODE:-}" ]; then ZRT_MODE=$AWARECARE_ZRT_MODE ZRT_MODE_FROM="AWARECARE_ZRT_MODE"; return 0; fi
  if z=$(find_zrt); then m=$(timeout 10 "$z" config get mode 2>/dev/null | tr -d '[:space:]'); fi
  case "$m" in
    user|system) ZRT_MODE=$m ZRT_MODE_FROM="zrt config get mode" ;;
    *) ZRT_MODE=system ZRT_MODE_FROM="ZRT's default" ;;
  esac
}
zrt_run() { local z; z=$(find_zrt) || return 127; "$z" -m "${ZRT_MODE:-system}" "$@"; }
# zrt_address (#549): ZRT's address, after zrt_mode: --zrt-url, --zrt-port, AWARECARE_ZRT_URL, then ZRT's proxy on the
# port ZRT is set to (`zrt config get proxy.port`; ZRT_CONFIG_PORT), else 8080. Sets ZRT_URL and ZRT_URL_FROM.
zrt_address() {
  local z p=""
  if z=$(find_zrt); then p=$(timeout 10 "$z" -m "${ZRT_MODE:-system}" config get proxy.port 2>/dev/null | tr -d '[:space:]'); fi
  if port_ok "$p"; then ZRT_CONFIG_PORT=$p; else ZRT_CONFIG_PORT=""; fi
  if [ -n "$ZRT_URL_OPT" ]; then ZRT_URL=$ZRT_URL_OPT ZRT_URL_FROM="--zrt-url"
  elif [ -n "$ZRT_PORT_OPT" ]; then ZRT_URL="http://127.0.0.1:$ZRT_PORT_OPT/v1" ZRT_URL_FROM="--zrt-port"
  elif [ -n "$ZRT_URL_ENV" ]; then ZRT_URL=$ZRT_URL_ENV ZRT_URL_FROM="AWARECARE_ZRT_URL"
  elif [ -n "$ZRT_CONFIG_PORT" ]; then ZRT_URL="http://127.0.0.1:$ZRT_CONFIG_PORT/v1" ZRT_URL_FROM="zrt config get proxy.port"
  else ZRT_URL=http://127.0.0.1:8080/v1 ZRT_URL_FROM="ZRT's default port"; fi
  ZRT_URL=${ZRT_URL%/}
}
zrt_explicit() { [ -n "$ZRT_URL_OPT" ] || [ -n "$ZRT_PORT_OPT" ]; }  # an address the user named: no discovery

# hw_choose: this machine and its catalogue model (hardware.py choose, once): HW_* (product, GPUs, memory, CUDA,
# architecture) and M_* (label, hf ref, size, tier, profile nano|fury|generic, status, tensor parallel, settings).
HW_KEYS="HW_PRODUCT HW_NAME HW_SHORT HW_ARCH HW_PLATFORM HW_CLASS HW_UNIFIED HW_GPU_COUNT HW_GPUS HW_GPU_NAME HW_USABLE_GB
  HW_MEM_GB HW_DRIVER HW_CUDA HW_TOOLKIT HW_TOOLKIT_VERSION M_LABEL M_REPO M_REVISION M_HF M_SIZE_GB M_TIER M_PROFILE
  M_STATUS M_TP M_SETTINGS M_QUALIFIED_ON M_REASON"
for k in $HW_KEYS; do printf -v "$k" '%s' ""; done
hw_choose() {
  [ "$CHOSEN" = 0 ] || return 0
  CHOSEN=1
  local args=(choose) k v
  [ -z "$MODEL_OPT" ] || args+=(--model "$MODEL_OPT")
  case "$DEVICE" in nano|fury) args+=(--device "$DEVICE") ;; esac
  while IFS='=' read -r k v; do
    case " ${HW_KEYS//$'\n'/ } " in *" $k "*) printf -v "$k" '%s' "$v" ;; esac
  done < <(hardware "${args[@]}" 2>/dev/null)
}
build_platform() { if [ "$DEVICE" = generic ]; then echo "${HW_PLATFORM:-linux/amd64}"; else echo linux/arm64; fi; }
model_label() {  # what the machine serves, for messages
  local m; m=$(device_model "$DEVICE")
  if [ "$DEVICE" = generic ]; then echo "$m ($M_STATUS on this hardware)"; else echo "$m"; fi
}

match_model() {
  local out
  zrt_arg
  out=$(served_models | model_ids match --model "$(device_model "$1")" --repo "$(device_hf "$1")" --models - \
    --proxy-json "$ZRT_HOME/proxy.json" "${ZRT_ARG[@]}") || return 1
  { read -r MATCH_ID; read -r _; read -r MATCH_NOTE; } <<< "$out"
  [ -n "$MATCH_ID" ]
}
served_as() {  # "<model>" or "<model> as <served id>"
  if [ "$MATCH_ID" = "$(device_model "$1")" ]; then echo "$MATCH_ID"; else echo "$(device_model "$1") as $MATCH_ID"; fi
}
note_revision() { [ -z "${MATCH_NOTE:-}" ] || note "${MATCH_NOTE^}" "nothing to do (it works)"; }
served_list() { served_models | model_ids ids --models - | paste -sd, - | sed 's/,/, /g'; }

# zrt_rows <device>: the rows of `zrt services`, tab-separated (model_ids.py services, #535): 1 when it is the
# device's model (else 0), PID, status, endpoint, its loopback <endpoint>/v1 (else -), uptime in seconds, name and
# (#702) its model URI.
zrt_rows() {
  local z
  z=$(find_zrt) || return 0
  timeout 30 "$z" -m "${ZRT_MODE:-system}" services 2>/dev/null | model_ids services --model "$(device_model "$1")" --repo "$(device_hf "$1")" --services -
}
# zrt_resolve <device>: whether ZRT serves the device's model on ZRT_URL (match_model). If not, and no --zrt-url was
# given, a Ready ZRT service for the model whose own loopback endpoint lists it takes ZRT_URL's place, and ZRT_FOUND
# keeps the address it replaced (#535: on an HP Z8, the proxy on 8080 served another model, the model ran on 9093).
# #632: else any other loopback port that is listening and lists the model (on a shared Fury, another account's ZRT
# served it on 8080 while this user's own ZRT proxy was set to 8000, and its `zrt services` listed nothing).
zrt_resolve() {
  match_model "$1" && return 0
  ! zrt_explicit || return 1
  local was=$ZRT_URL hit _pid status _ep url _rest
  while IFS=$'\t' read -r hit _pid status _ep url _rest; do
    if [ "$hit" != 1 ] || [ "$status" != Ready ] || [ "$url" = - ] || [ "$url" = "$was" ]; then continue; fi
    ZRT_URL=$url
    if match_model "$1"; then ZRT_FOUND=$was ZRT_FOUND_ON=""; return 0; fi
  done < <(zrt_rows "$1")
  local port
  for port in $(listening_ports); do
    ZRT_URL="http://127.0.0.1:$port/v1"
    [ "$ZRT_URL" != "$was" ] || continue
    curl -s --noproxy '*' --connect-timeout 1 -m 2 "$ZRT_URL/models" 2>/dev/null | grep -q '"data"' || continue
    if match_model "$1"; then ZRT_FOUND=$was ZRT_FOUND_ON=port; return 0; fi
  done
  ZRT_URL=$was
  return 1
}
# listening_ports: the TCP ports listening on loopback or on every address (at most 64), ZRT's 8080 and 8000 first.
listening_ports() {
  ss -Hltn 2>/dev/null | awk '{ print $4 }' | sed -nE 's/^(127\.0\.0\.1|0\.0\.0\.0|\*|\[::1?\]):([0-9]+)$/\2/p' \
    | sort -nu | awk '$1 == 8080 { print 0, $1; next } $1 == 8000 { print 1, $1; next } { print 2, $1 }' \
    | sort -n -k1,1 -k2,2 | awk '{ print $2 }' | head -n 64
}
url_port() { local u=${1#*://}; u=${u%%/*}; echo "${u##*:}"; }
# others_model (#651), after zrt_resolve: the model runs on another listening port (#632: another account's ZRT, as a
# rule) and this account's model unit is not enabled, so serving it, lingering and its watchdog are not yours to do
others_model() { [ "$ZRT_FOUND_ON" = port ] && [ "$(systemctl --user is-enabled "$UNIT" 2>/dev/null)" != enabled ]; }
note_zrt_url() {  # the note when ZRT_URL is a service endpoint
  [ -n "$ZRT_FOUND" ] || return 0
  if [ "$ZRT_FOUND_ON" = port ]; then
    note "Nothing on port $(url_port "$ZRT_FOUND") lists the model; port $(url_port "$ZRT_URL") serves it (another account's ZRT?), so demo.sh uses $ZRT_URL" \
      "nothing to do; do not serve it again. Next time you can name it: --zrt-port $(url_port "$ZRT_URL")"
    return 0
  fi
  note "ZRT's proxy on $(url_port "$ZRT_FOUND") does not list the model; using the service endpoint $ZRT_URL" \
    "nothing now. That endpoint can change when the service restarts: serve the model through the proxy" \
    "(./demo.sh model), or name it: --zrt-port $(url_port "$ZRT_URL")"
}
# zrt_endpoint_lines <device>: the services `zrt services` lists, for a fix text.
zrt_endpoint_lines() {
  local rows
  rows=$(zrt_rows "$1" | awk -F'\t' '{ printf "%s%s (%s, %s%s)", (NR > 1 ? "; " : ""), $4, $7, $3, $1 == 1 ? ", this model" : "" }')
  if [ -n "$rows" ]; then echo "zrt services lists: $rows"; fi
  echo "ZRT serves it on another port? \$ ./demo.sh $CMD --zrt-port <port>"
}

# zrt_store, zrt_run_dir (#644): the model cache and the run directory (its logs) of ZRT in the mode demo.sh uses: in
# user mode the user's own (~/.local/share/zrt), in system mode $ZRT_HOME (/opt/hp/zrt).
zrt_user_home() { echo "$HOME/.local/share/zrt"; }
zrt_store() { if [ "${ZRT_MODE:-system}" = user ]; then echo "$(zrt_user_home)/models"; else echo "$ZRT_HOME/models"; fi; }
zrt_run_dir() { if [ "${ZRT_MODE:-system}" = user ]; then echo "$(zrt_user_home)/run"; else echo "$ZRT_HOME/run"; fi; }
# local_copy <device> [revision]: the revision of an already downloaded copy of the device's model in ZRT's cache
# (`zrt models` and zrt_store), the qualified one first, then main, then any; empty when there is none. #644: in user
# mode only the user's own cache: user mode cannot serve a copy in the system ZRT's.
local_copy() {
  zrt_arg
  model_ids local --repo "$(device_hf "$1")" --store "$(zrt_store)" "${ZRT_ARG[@]}" --revision "${2:-}" 2>/dev/null
}
# system_copy <device> [revision] (#644): in user mode, the revision of a copy in the system ZRT's cache
# ($ZRT_HOME/models), "?" when its folder shows but cannot be listed; empty (status 1) when none, or in system mode.
system_copy() {
  [ "${ZRT_MODE:-system}" = user ] || return 1
  model_ids shared --repo "$(device_hf "$1")" --store "$ZRT_HOME/models" --revision "${2:-}" 2>/dev/null
}
in_zrt_group() { id -nG 2>/dev/null | tr ' ' '\n' | grep -qx zrt; }
# system_copy_fix <revision>: the stop before a download that the system ZRT does not need (#644: 65 minutes on the Fury)
system_copy_fix() {
  local what; what=$(device_repo "$DEVICE")
  if [ "$1" = "?" ]; then what+=" (its revisions are not readable for you)"; else what+="@$1"; fi
  local what_happened="The system ZRT already has this model: $what in $ZRT_HOME/models, so demo.sh does not download it again"
  local again=${CMD:-setup}; [ "$again" != doctor ] || again=setup  # #659: doctor serves nothing
  if in_zrt_group; then
    "${2:-fail}" "$what_happened" "Your ZRT runs in user mode, with its own cache. Serve the system ZRT's copy instead:" \
      "\$ ./demo.sh $again --zrt-mode system"
  else
    "${2:-fail}" "$what_happened" "Your ZRT runs in user mode, and only the zrt group may read the system ZRT's models." \
      "Ask an administrator: sudo usermod -aG zrt ${USER:-$(id -un)}, log in again, then rerun with --zrt-mode system:" \
      "\$ ./demo.sh $again --zrt-mode system"
  fi
}

# find_device: sets DEVICE quietly (so the header can name it) and DEVICE_LINE, or DEVICE_GPU when it cannot tell;
# device_line then prints the result under Checks, or fails.
find_device() {
  DEVICE_LINE="" DEVICE_GPU="" DEVICE_WHY=""
  hw_choose
  if [ -n "$DEVICE" ]; then DEVICE_LINE="Device: ZGX ${DEVICE^} (--device)"; return; fi
  # #537: a catalogue model by name, or any NVIDIA machine other than a GB10 or GB300 (a Z8, an RTX workstation ...)
  if [ -n "$MODEL_OPT" ] || [ "$HW_CLASS" = discrete ] || [ "$HW_CLASS" = grace ]; then
    if [ -z "$M_LABEL" ]; then DEVICE_WHY=$M_REASON; return; fi
    DEVICE=$M_PROFILE
    if [ "$DEVICE" = generic ]; then DEVICE_LINE="Device: $HW_NAME (GPU ${HW_GPUS}; $HW_USABLE_GB GB usable)"
    else DEVICE_LINE="Device: ZGX ${DEVICE^} (--model $MODEL_OPT)"; fi
    return
  fi
  # #646: the Nano and the Fury serve the same model, so the served model tells them apart only where the GPU does not:
  # a GB300 is a Fury and a GB10 a Nano whatever ZRT serves; with another GPU name, nano, then fury
  local d gpu=$HW_GPU_NAME devices=(nano fury)
  case "$gpu" in *GB300*) devices=(fury) ;; *GB10*) devices=(nano) ;; esac
  for d in "${devices[@]}"; do
    if match_model "$d"; then DEVICE=$d; DEVICE_LINE="Device: ZGX ${d^} (ZRT serves $MATCH_ID)"; return; fi
  done
  for d in "${devices[@]}"; do  # #535: on a ZRT service's own endpoint
    if zrt_resolve "$d"; then DEVICE=$d; DEVICE_LINE="Device: ZGX ${d^} (ZRT serves $MATCH_ID)"; return; fi
  done
  case "$gpu" in
    *GB10*) DEVICE=nano ;;
    *GB300*) DEVICE=fury ;;
    *) DEVICE_GPU=${gpu:-none found}; DEVICE_WHY=${M_REASON:-GPU $DEVICE_GPU}; return ;;
  esac
  DEVICE_LINE="Device: ZGX ${DEVICE^} (GPU $gpu)"
}
device_line() {
  [ -n "$DEVICE" ] || fail "No local model for this machine: ${DEVICE_WHY:-GPU $DEVICE_GPU}" \
    "Try the demo without a model:" "\$ ./demo.sh mock" \
    "What this machine has and which models fit: ./demo.sh doctor. On a ZGX device: --device nano (or fury);" \
    "a catalogue model: --model <label>"
  ok "$DEVICE_LINE"
  if [ "$DEVICE" = generic ]; then
    if [ "$M_STATUS" = qualified ]; then ok "Model: $M_LABEL (qualified on this hardware), $M_SETTINGS"
    else note "Model: $M_LABEL, a candidate on this hardware (${M_TIER}; qualified: ${M_QUALIFIED_ON:-nowhere yet})" \
      "optional: ./demo.sh check-model checks it once it runs"
      info "Serving: $M_SETTINGS"
    fi
  fi
}
on_device() {
  case "$DEVICE" in '') ;; generic) echo " on $HW_NAME" ;; *) echo " on HP ZGX ${DEVICE^}" ;; esac
}

model_fix_lines() {
  local hf repo zrt have
  local how="--device $DEVICE"
  hf=$(device_hf "$DEVICE"); repo=$(device_repo "$DEVICE"); zrt="infra/$DEVICE/zrt"
  [ "$DEVICE" != generic ] || how=${MODEL_OPT:+--model $MODEL_OPT}
  have=$(local_copy "$DEVICE")
  if [ -n "$have" ]; then echo "ZRT already has $repo downloaded (revision $have): serve that copy, no download:"
  else echo "Serve it (a download the first time; see first with --dry-run):"; fi
  echo "\$ ./demo.sh model $how"
  if [ -z "$have" ]; then
    echo "By hand, from $ROOT: zrt $([ "${ZRT_MODE:-system}" = system ] || echo "-m $ZRT_MODE ")pull $hf, then the unit in $zrt/"
  fi
  if [ "$DEVICE" = generic ]; then
    echo "Already set up? It may still be starting: systemctl --user status $UNIT"; return
  fi
  echo "Already set up? It may still be starting (6 minutes on a Nano, 2 on a Fury; a first start up to 25): systemctl --user status $UNIT"
}

# ------------------------------------------------------------------ tunnel

device_address() {
  # The address and port you used to log in, when this runs in an SSH session.
  if [ -n "${SSH_CONNECTION:-}" ]; then
    # shellcheck disable=SC2086  # split "client cport server sport"
    set -- $SSH_CONNECTION
    echo "$3 $4"; return
  fi
  local ip
  ip=$(hostname -I 2>/dev/null | awk '{print $1}')
  echo "${ip:-<device-host>} <ssh-port>"
}
# open_it <browser port> <device port>: the most important output, in a box of its own.
open_it() {
  local browser=$1 device_port=$2 addr host sport rule
  addr=$(device_address); host=${addr% *}; sport=${addr#* }
  rule=$(printf '\342\224\200%.0s' {1..64})
  printf '\n%sOpen it%s\n' "$B$GRN" "$X"
  printf '  %s\342\224\214%s%s\n' "$GRN" "$rule" "$X"
  printf '  %s\342\224\202%s On your computer, keep this tunnel open:\n' "$GRN" "$X"
  printf '  %s\342\224\202%s   %s%s%s\n' "$GRN" "$X" "$B$CYN" "ssh -N -p $sport -L $browser:127.0.0.1:$device_port ${USER:-<user>}@$host" "$X"
  printf '  %s\342\224\202%s Then open:  %s%s%s\n' "$GRN" "$X" "$B$CYN" "http://127.0.0.1:$browser" "$X"
  # #690: localhost redirects to 127.0.0.1 now; #689: the home page offers Presenter first, then Patient
  printf '  %s\342\224\202%s %s(localhost works too; then choose Presenter or Patient)%s\n' "$GRN" "$X" "$D" "$X"
  printf '  %s\342\224\224%s%s\n' "$GRN" "$rule" "$X"
}
next_steps() { printf '  %s%s%s\n' "$D" "$*" "$X"; }

wait_ready() {  # wait_ready <url> <seconds>
  local url=$1 n
  for ((n = 0; n < $2; n += 2)); do
    if curl -s --noproxy '*' -m 3 "$url" 2>/dev/null | grep -q '"readiness":"ready"'; then return 0; fi
    sleep 2
  done
  return 1
}
port_busy() { ss -Hltn "sport = :$1" 2>/dev/null | grep -q .; }

# ------------------------------------------------------------------ mock

mock_running() {
  [ -f "$MOCK_STATE" ] || return 1
  local API_PID="" WEB_PID=""
  # shellcheck disable=SC1090
  . "$MOCK_STATE"
  kill -0 "${API_PID:-0}" 2>/dev/null || kill -0 "${WEB_PID:-0}" 2>/dev/null
}

cmd_mock() {
  start_log mock
  header "mock mode (no model, scripted synthetic results)" dry
  section "Checks"
  command -v uv >/dev/null || fail "uv is missing" "Mock mode runs the API with uv. Install it as your user:" \
    "\$ curl -LsSf https://astral.sh/uv/install.sh | sh" "then open a new shell and rerun ./demo.sh mock."
  { command -v npm >/dev/null && command -v node >/dev/null; } || fail "Node 24 and npm are missing" \
    "Mock mode runs the web app with Node. Install them as your user, for example with nvm (https://github.com/nvm-sh/nvm):" \
    "\$ nvm install 24"
  ok "Tools: uv $(uv --version 2>/dev/null | awk '{print $2}'), Node $(node --version 2>/dev/null)"

  if mock_running; then [ "$DRY" = 1 ] || stop_mock quiet; fi

  local web=${PORT:-5173} browser=${PORT:-15173} api=8000
  if [ "$DRY" = 0 ]; then
    port_busy "$web" && fail "Port $web is in use on this device" "Another program holds it (see which: ss -ltnp | grep :$web). Use another port:" \
      "\$ ./demo.sh mock --port <n>"
    while port_busy "$api" && [ "$api" -lt 8099 ]; do api=$((api + 1)); done
    ok "Ports: web 127.0.0.1:$web, API 127.0.0.1:$api"
  fi

  section "Dependencies"
  # uv sync is quick when nothing changed, and brings apps/api/.venv in line after ./demo.sh update.
  (cd "$ROOT/apps/api" && long_run "Installing the API dependencies (uv sync)" "Installing the API dependencies (uv sync) ..." \
    uv sync --python 3.12.15) || exit 1
  [ "$DRY" = 1 ] || ok "API dependencies (apps/api/.venv)"
  local nm="$ROOT/apps/web/node_modules" lock_sum
  lock_sum=$(sha256sum "$ROOT/apps/web/package-lock.json" | cut -c1-64)
  if [ -L "$nm" ]; then
    ok "Web dependencies (apps/web/node_modules is a link; not reinstalled)"
  elif [ "$DRY" = 1 ] || [ ! -f "$nm/.demo-lock-sha" ] || [ "$(cat "$nm/.demo-lock-sha")" != "$lock_sum" ]; then
    (cd "$ROOT/apps/web" && long_run "Installing the web dependencies (npm ci)" "Installing the web dependencies (npm ci, a minute or two) ..." \
      npm ci --no-audit --no-fund) || exit 1
    [ "$DRY" = 1 ] || { echo "$lock_sum" > "$nm/.demo-lock-sha"; ok "Web dependencies installed (apps/web/node_modules)"; }
  else
    ok "Web dependencies (apps/web/node_modules)"
  fi

  section "Start"
  local key="$ROOT/runtime-data/presenter-dev.key"
  if [ "$DRY" = 0 ] && [ ! -s "$key" ]; then
    mkdir -p "$ROOT/runtime-data"
    (umask 077 && python3 -c 'import secrets; print(secrets.token_hex(32))' > "$key")
  fi
  local origin="http://127.0.0.1:$browser"
  if [ "$DRY" = 1 ]; then
    cmdline "(cd apps/api && AWARECARE_ALLOWED_ORIGINS=$origin AWARECARE_PRESENTER_KEY_FILE=$key uv run uvicorn app.main:app --host 127.0.0.1 --port $api) &"
    cmdline "(cd apps/web && AWARECARE_WEB_PORT=$web AWARECARE_API_TARGET=http://127.0.0.1:$api AWARECARE_PRESENTER_KEY_FILE=$key npm run dev) &"
    note "Dry run: nothing was installed or started."
    open_it "$browser" "$web"; return 0
  fi
  local api_log="$LOG_DIR/api.log" web_log="$LOG_DIR/web.log" api_pid web_pid
  (cd "$ROOT/apps/api" && AWARECARE_ALLOWED_ORIGINS=$origin AWARECARE_PRESENTER_KEY_FILE=$key \
    exec setsid uv run uvicorn app.main:app --host 127.0.0.1 --port "$api" > "$api_log" 2>&1 < /dev/null) &
  api_pid=$!
  (cd "$ROOT/apps/web" && AWARECARE_WEB_PORT=$web AWARECARE_API_TARGET=http://127.0.0.1:$api \
    AWARECARE_PRESENTER_KEY_FILE=$key exec setsid npm run dev > "$web_log" 2>&1 < /dev/null) &
  web_pid=$!
  printf 'API_PID=%s\nWEB_PID=%s\nAPI_PORT=%s\nWEB_PORT=%s\nBROWSER_PORT=%s\n' \
    "$api_pid" "$web_pid" "$api" "$web" "$browser" > "$MOCK_STATE"
  ok "Started the API (127.0.0.1:$api) and the web server (127.0.0.1:$web); logs in runtime-data/demo-logs/"
  doing "Waiting for the app to answer ready (up to 2 minutes) ..."
  if ! progress wait_ready "http://127.0.0.1:$web$READY_PATH" "${AWARECARE_DEMO_READY_SECONDS:-120}"; then
    stop_mock quiet  # a failed start stops what it started
    LOG=$api_log
    fail "The app did not become ready within 2 minutes, so demo.sh stopped what it started" \
      "Its logs say why: $api_log and $web_log. Fix that, then rerun (another port: --port <n>):" "\$ ./demo.sh mock"
  fi
  ok "Ready: http://127.0.0.1:$web$READY_PATH answers ready (mock mode, $TOOK)"
  open_it "$browser" "$web"
  next_steps "Stop: ./demo.sh stop    Reset all data: ./demo.sh stop, then rm -rf runtime-data/api"
}

stop_mock() {
  local API_PID="" WEB_PID="" p
  # shellcheck disable=SC1090
  . "$MOCK_STATE"
  if [ "$DRY" = 1 ]; then cmdline "kill -TERM -- -$WEB_PID -$API_PID   # the mock development servers"; return 0; fi
  for p in "$WEB_PID" "$API_PID"; do
    [ -n "$p" ] || continue
    kill -TERM -- "-$p" 2>/dev/null || kill -TERM "$p" 2>/dev/null || true
  done
  rm -f "$MOCK_STATE"
  [ "${1:-}" = quiet ] || ok "Stopped the mock development servers (data kept in runtime-data/api)"
}

# ------------------------------------------------------------------ local

# #696: without a device (no model for this machine) the Nano's configuration names the ports (the same on every one)
config_file() { case "$DEVICE" in generic) echo infra/deploy/demo-generic.json ;; '') echo infra/deploy/demo-zgx-nano.json ;;
  *) echo "infra/deploy/demo-zgx-$DEVICE.json" ;; esac; }
config_value() { python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(eval("d"+sys.argv[2]))' "$(config_file)" "$1"; }
deploy_tool() {  # the deploy tool with this instance's overrides (instance, data root, ports, origin)
  # #535: one address for ZRT: the one demo.sh checked (--zrt-url, AWARECARE_ZRT_URL or a service endpoint) replaces
  # the config's zrt.base_url; the API gets it as AWARECARE_MODEL_BASE_URL.
  DEPLOY=(python3 infra/deploy/nano_deploy.py --config "$(config_file)" --zrt-base-url "$ZRT_URL")
  [ "$INSTANCE" = aware-care-demo ] || DEPLOY+=(--instance "$INSTANCE")
  [ "$DATA_ROOT" = "$DEFAULT_DATA_ROOT" ] || DEPLOY+=(--data-root "$DATA_ROOT")
  [ -z "${AWARECARE_DEMO_API_PORT:-}" ] || DEPLOY+=(--api-port "$AWARECARE_DEMO_API_PORT")
  [ -z "${AWARECARE_DEMO_WEB_PORT:-}" ] || DEPLOY+=(--web-port "$AWARECARE_DEMO_WEB_PORT")
  [ -z "$PORT" ] || DEPLOY+=(--origin "http://127.0.0.1:$PORT")
  # #537: any other machine is named from DMI (hardware.py makes the name safe for the gateway)
  [ "$DEVICE" != generic ] || DEPLOY+=(--device-name "$HW_NAME" --device-short-name "$HW_SHORT")
}

# #644 (owner decision, 28 Oct 2026): there is no main instance. Container names are the same for every account on a
# machine, so this instance's containers may run the maintainer's workflow release, another account's ./demo.sh
# instance, or your own with its data elsewhere. Anyone may use it, or stop it and run their own (setup or local
# --replace; stop; uninstall). Its data always stays: demo.sh only ever deletes paths of your own data root.
# instance_root [instance] (#634): the data root the instance's API container mounts (<root>/data/<mode>).
instance_root() {
  local src
  src=$(docker container inspect -f \
    '{{range .Mounts}}{{if eq .Destination "/var/lib/aware-care/data"}}{{.Source}}{{end}}{{end}}' "${1:-$INSTANCE}-api" \
    2>/dev/null) || return 1
  [ -n "$src" ] || return 1
  echo "${src%/data/*}"
}
# running_other: whether this instance's containers run someone else's demo: anything but your own ./demo.sh instance
# in your own data root. Sets OTHER (whose it is, for messages) and OTHER_KEPT (where its data stays: its data root,
# when the container names one).
running_other() {
  local inst=$INSTANCE img root who="" release
  OTHER="" OTHER_KEPT="" OTHER_ROOT=""
  img=$(docker container inspect -f '{{.Config.Image}}' "$inst-api" 2>/dev/null) || return 1
  root=$(instance_root "$inst") || root=""
  if [ "$img" = "$inst-api:local" ] && { [ -z "$root" ] || [ "$(canon "$root")" = "$(canon "$DATA_ROOT")" ]; }; then
    return 1
  fi
  if [ -n "$root" ]; then who=$(stat -c %U -- "$root" 2>/dev/null) || who=""; fi
  if [ -z "$who" ] && [[ $root =~ ^/home/([^/]+)/ ]]; then who=${BASH_REMATCH[1]}; fi
  if [ "$img" != "$inst-api:local" ]; then
    release=$(docker container inspect -f '{{index .Config.Labels "aware-care.release"}}' "$inst-web" 2>/dev/null)
    OTHER="the release ${release:-$img} from the deploy workflow"
    if [ -n "$who" ] && [ "$who" != "${USER:-}" ]; then OTHER+=", run by $who"; fi  # #661: no nested parentheses
  elif [ -n "$who" ] && [ "$who" = "${USER:-}" ]; then OTHER="your own instance with its data in $root"
  else OTHER="the ./demo.sh instance of ${who:-another account}"; fi
  if [ -n "$root" ]; then OTHER_KEPT="its data stays in $root"; else OTHER_KEPT="its data stays where it is"; fi
  OTHER_ROOT=$root
}
# beside_running (local, setup): when this instance's containers run someone else's demo, say "It's already running:
# open it here" with the tunnel and the address (#696, owner decision T3), then exit 0; with --replace, say what happens
# to it and go on (build_deploy removes its containers just before the deploy, so a failed build leaves it running).
# #696: --replace stays available but is not offered here. Without Docker access (outside the docker group) the
# containers cannot be read, so a demo that answers on this instance's web port counts as running.
beside_running() {
  REPLACING=0
  if ! docker info >/dev/null 2>&1; then
    [ "$REPLACE" = 0 ] || return 0
    local web; web=${AWARECARE_DEMO_WEB_PORT:-$(config_value "['network']['web_port']")}
    [ -n "$(readiness_of "$web")" ] || return 0
    already_running "$web" "$(url_port "$(config_value "['network']['browser_origin']")")" \
      "A demo answers on 127.0.0.1:$web (Docker is not usable for you, so demo.sh cannot tell whose it is)"
  fi
  running_other || return 0
  if [ "$REPLACE" = 1 ]; then
    [ "$CMD" != setup ] || section "Replace"  # #661: after setup's checks, a section of its own (local: under Checks)
    note "--replace: $INSTANCE-api and $INSTANCE-web run $OTHER"
    info "Its containers are removed just before your deploy; $OTHER_KEPT (nothing of it is deleted)."
    REPLACING=1
    return 0
  fi
  running_ports
  local whose="${OTHER^} ($INSTANCE-api, $INSTANCE-web)"
  already_running "$RUN_WEB" "$RUN_BROWSER" "$whose"
}
# running_ports: the running demo's device web port (RUN_WEB) and browser port (RUN_BROWSER: its own origin, the only
# address its Origin checks accept), from its web container, else this instance's configuration.
running_ports() {
  local env origin
  env=$(docker container inspect -f '{{json .Config.Env}}' "$INSTANCE-web" 2>/dev/null)
  RUN_WEB=$(sed -n 's/.*"AWARECARE_WEB_PORT=\([0-9]*\)".*/\1/p' <<< "$env")
  origin=$(sed -n 's/.*"AWARECARE_ORIGIN=\([^"]*\)".*/\1/p' <<< "$env")
  RUN_WEB=${RUN_WEB:-${AWARECARE_DEMO_WEB_PORT:-$(config_value "['network']['web_port']")}}
  RUN_BROWSER=$(url_port "${origin:-$(config_value "['network']['browser_origin']")}")
}
readiness_of() {  # readiness_of <web port>: what the demo there answers (ready, degraded, ...), empty when nothing
  curl -s --noproxy '*' -m 5 "http://127.0.0.1:$1$READY_PATH" 2>/dev/null | sed -n 's/.*"readiness":"\([a-z_]*\)".*/\1/p'
}
# ready_line <web port>: whether the demo there answers ready, in one line (with what to do when it does not)
ready_line() {
  local ready; ready=$(readiness_of "$1")
  case "$ready" in
    ready) ok "It answers ready on 127.0.0.1:$1" ;;
    "") note "It does not answer on 127.0.0.1:$1 yet" "it may still be starting: try again in 2 minutes (./demo.sh open)" ;;
    # #654: degraded: it runs, but ZRT does not serve its model; waiting does not help
    degraded) note "It answers degraded on 127.0.0.1:$1, not ready: it runs, but its model does not answer" \
      "./demo.sh status shows whether ZRT serves the model;" "the account that serves it starts it again with ./demo.sh model" ;;
    *) note "It answers $ready on 127.0.0.1:$1, not ready" "docs/wiki/Troubleshooting.md: the row \"Readiness $ready\" says why" ;;
  esac
}
# already_running <web port> <browser port> <whose> (#696, T3): the demo that runs here, the way in, and exit 0
already_running() {
  section "Already running"
  ok "It's already running: open it here"
  info "$3"
  ready_line "$1"
  open_it "$2" "$1"
  next_steps "Nothing else to do: use it as it is (everyone who opens it shares its data)."
  next_steps "Your own copy instead: README, \"Several people on one machine\"."
  exit 0
}
# replace_running (build_deploy, after the build): remove the containers beside_running named (--replace).
replace_running() {
  [ "${REPLACING:-0}" = 1 ] || return 0
  local role names=()
  for role in api web; do
    if docker container inspect "$INSTANCE-$role" >/dev/null 2>&1; then names+=("$INSTANCE-$role"); fi
  done
  [ ${#names[@]} = 0 ] && return 0
  run "Removing the running demo's containers" docker rm -f "${names[@]}"
  [ "$DRY" = 1 ] || ok "Removed $(and_list "${names[@]}") ($OTHER); $OTHER_KEPT"
}

# docker_cli (#549): DOCKER_BIN, the docker program on PATH; DOCKER_ENV, "the conda environment <name>" or "the
# virtualenv <dir>" when it comes from one; DOCKER_OTHER, a docker it hides (later on PATH, else /usr/bin/docker). On
# the manager's HP Z8 a conda shell's "(base)" put another Docker CLI first, and `docker buildx version` failed there.
docker_cli() {
  local p
  DOCKER_BIN=$(command -v docker) DOCKER_ENV="" DOCKER_OTHER=""
  [ -n "$DOCKER_BIN" ] || return 1
  if [ -n "${CONDA_PREFIX:-}" ] && [[ $DOCKER_BIN == "$CONDA_PREFIX"/* ]]; then
    DOCKER_ENV="the conda environment ${CONDA_DEFAULT_ENV:-$CONDA_PREFIX}"
  elif [[ $DOCKER_BIN =~ /(ana|mini|micro)?(conda|forge|mamba)[^/]*/ ]]; then DOCKER_ENV="a conda installation"
  elif [ -n "${VIRTUAL_ENV:-}" ] && [[ $DOCKER_BIN == "$VIRTUAL_ENV"/* ]]; then DOCKER_ENV="the virtualenv $VIRTUAL_ENV"
  fi
  while read -r p; do
    if [ "$p" != "$DOCKER_BIN" ]; then DOCKER_OTHER=$p; break; fi
  done < <(type -ap docker)
  if [ -z "$DOCKER_OTHER" ] && [ -x /usr/bin/docker ] && [ "$DOCKER_BIN" != /usr/bin/docker ]; then DOCKER_OTHER=/usr/bin/docker; fi
}
# docker_cli_lines: the Docker CLI line (doctor), or only the warning when an environment's CLI comes first (local).
docker_cli_lines() {
  docker_cli || return 0
  if [ -z "$DOCKER_ENV" ]; then [ "${1:-}" != all ] || ok "Docker CLI: $DOCKER_BIN"; return 0; fi
  local what="Docker CLI: $DOCKER_BIN, from $DOCKER_ENV"
  [ -z "$DOCKER_OTHER" ] || what+=", comes before $DOCKER_OTHER on PATH"
  note "$what" "conda deactivate (or deactivate a virtualenv), then rerun: its docker may not find the system's" \
    "plugins (docker buildx). Or put the system's first: PATH=$(dirname "${DOCKER_OTHER:-/usr/bin/docker}"):\$PATH ./demo.sh ${CMD:-setup}"
}
# buildx_line: the buildx this machine has (infra/deploy/find_buildx.sh, the same build_images.sh uses), or fail/bad.
buildx_line() {
  # shellcheck disable=SC1091  # infra/deploy/find_buildx.sh is checked on its own
  . "$ROOT/infra/deploy/find_buildx.sh"
  if find_buildx; then ok "$BUILDX_HOW"; return 0; fi
  "${1:-fail}" "docker buildx is missing" "The build needs it. Tried: $BUILDX_TRIED. An administrator installs the plugin" \
    "(or a standalone docker-buildx on your PATH):" "\$ sudo apt-get install docker-buildx-plugin"
}

# admin_check <check...> (#694, owner decision T1): before any download, everything only an administrator can do, once,
# for this account: docker (the docker group); zrt (the zrt group, when ZRT runs in user mode and the system ZRT holds
# the model, or may: #702, its cache is readable only for the zrt group); linger (lingering, when this account serves
# the model); and session (an SSH login, not sudo then su: the account's own step). The administrator's commands come
# in one copy-paste block with the account's name, then setup stops (fail; ADMIN_HOW=bad in doctor: no stop). Sets
# ADMIN_RERUN (the options a rerun needs, e.g. --zrt-mode system).
system_cache_hidden() {  # #702 (case 3): user mode, outside the zrt group, and the system ZRT's model cache unreadable
  [ "${ZRT_MODE:-system}" = user ] && ! in_zrt_group && [ -e "$ZRT_HOME" ] \
    && ! { [ -r "$ZRT_HOME/models" ] && [ -x "$ZRT_HOME/models" ]; }
}
# serves_here: this account serves the device's model (or will): it is not served by another account's ZRT on another
# port (others_model, after zrt_resolve)
serves_here() { ! { zrt_resolve "$DEVICE" && others_model; }; }
admin_check() {
  local me=${USER:-$(id -un)} c out groups=() why=() cmds=() session=1 sys=""
  ADMIN_RERUN="" ADMIN_NEEDED=0
  for c in "$@"; do
    case "$c" in
      docker)
        if command -v docker >/dev/null && ! out=$(docker info 2>&1) && grep -qi 'permission denied' <<< "$out"; then
          groups+=(docker); why+=("Docker: $me is not in the docker group, and demo.sh never uses sudo.")
        fi ;;
      session) systemctl --user show-environment >/dev/null 2>&1 || session=0 ;;
      zrt)
        if [ "${ZRT_MODE:-system}" != user ] || in_zrt_group || [ -z "$DEVICE" ]; then continue; fi
        zrt_resolve "$DEVICE" && continue  # served already: nothing to download
        if sys=$(system_copy "$DEVICE" "$REVISION"); then
          groups+=(zrt); ADMIN_RERUN=" --zrt-mode system"
          local what; what=$(device_repo "$DEVICE"); [ "$sys" != "?" ] || what+=" (its revisions are not readable for you)"
          why+=("ZRT: the system ZRT already has $what in $ZRT_HOME/models, readable only for the zrt group;" \
            "your ZRT runs in user mode and would download it again (about $(catalog_size "$(device_model "$DEVICE")") GB).")
        elif system_cache_hidden; then
          groups+=(zrt); ADMIN_RERUN=" --zrt-mode system"
          why+=("ZRT: your ZRT runs in user mode, and only the zrt group may read the system ZRT's models ($ZRT_HOME/models)," \
            "which may hold $(device_repo "$DEVICE") already; demo.sh does not download a second copy (about $(catalog_size "$(device_model "$DEVICE")") GB).")
        fi ;;
      linger)
        [ -n "$DEVICE" ] || continue
        if ! linger_on && serves_here; then
          cmds+=("sudo loginctl enable-linger $me"); why+=("Lingering: off, so the model you serve stops when $me logs out.")
        fi ;;
    esac
  done
  if [ ${#groups[@]} -gt 0 ]; then cmds=("sudo usermod -aG $(IFS=,; echo "${groups[*]}") $me" "${cmds[@]}"); fi
  if [ ${#cmds[@]} = 0 ]; then
    [ "$session" = 1 ] || check_session "${ADMIN_HOW:-fail}"
    return 0
  fi
  local n=${#cmds[@]} what="1 thing" again
  ADMIN_NEEDED=1
  [ "$n" = 1 ] || what="$n things"
  local cmd=${CMD:-setup}; [ "$cmd" != doctor ] || cmd=setup  # doctor checks for setup
  again="./demo.sh $cmd$ADMIN_RERUN$(instance_args)"
  "${ADMIN_HOW:-fail}" "An administrator must do $what for $me, once, before $cmd can go on" "${why[@]}" \
    "Copy this block to an administrator:" "${cmds[@]/#/> }" \
    "Then log out, log in again over SSH as $me (ssh $me@<this machine>; not sudo then su), and rerun:" "\$ $again"
}

admin_ok() {  # the line when nothing is left for an administrator (setup, model)
  local what="login session"
  [ "$CMD" != setup ] || what="docker group, login session"
  linger_on && what+=", lingering"
  [ "${ZRT_MODE:-system}" != user ] || ! in_zrt_group || what+=", zrt group"
  ok "Nothing for an administrator to do ($what)"
}
admin_show() {  # doctor: the administrator block like bad's ✗, not counted again
  printf '  %s\342\234\227%s %s%s%s\n' "$RED$B" "$X" "$B" "$1" "$X"; shift
  err_lines "$@"
}

# check_session [fail|bad] (#644): systemctl --user reaches this user's own systemd session, which the model unit and its
# watchdog need. `sudo` then `su <user>` has none, so every systemctl --user call fails ("Failed to connect to bus:
# Permission denied"); on the Fury that showed only after a 65-minute download. setup, model and local check it first.
check_session() {
  local why me=${USER:-$(id -un)}
  if why=$(systemctl --user show-environment 2>&1 >/dev/null); then
    ok "Login session: systemctl --user reaches your systemd session"; return 0
  fi
  "${1:-fail}" "systemctl --user cannot reach your systemd session ($(head -n1 <<< "${why:-no answer}"))" \
    "The model runs as your own systemd unit, and sudo then su starts no session. Log in over SSH as $me, not with sudo then su:" \
    "\$ ssh $me@localhost" "then rerun ./demo.sh ${CMD:-setup} there."
}
# linger_lines: lingering off means the model (a user unit) stops when this user logs out (doctor, setup, model).
linger_lines() {
  if linger_on; then [ "${1:-}" = quiet ] || ok "Lingering on: the model keeps running after you log out"; return 0; fi
  note "Lingering is off: the model stops when you log out" \
    "an administrator runs, once: sudo loginctl enable-linger ${USER:-$(id -un)}"
}

check_docker() {
  command -v docker >/dev/null || fail "Docker is not installed" "The app runs in 2 containers. An administrator installs Docker Engine with the buildx plugin."
  docker_cli_lines
  local out
  if ! out=$(docker info 2>&1); then
    if grep -qi 'permission denied' <<< "$out"; then
      # #653: the name, not $USER: an administrator runs it, and in their shell $USER is the administrator
      fail "Docker is not usable without sudo (your user is not in the docker group)" \
        "demo.sh never uses sudo. An administrator adds you to the docker group, once:" \
        "\$ sudo usermod -aG docker ${USER:-$(id -un)}" \
        "Then log out and back in (exit, then ssh again), check that docker ps works, and rerun ./demo.sh ${CMD:-setup}."
    fi
    fail "Docker does not answer: $(head -n1 <<< "$out")" "Its daemon is not running. Start it (or ask an administrator):" "\$ sudo systemctl start docker"
  fi
  DOCKER_INFO=$out
  ok "Docker usable without sudo"
  # #535, #549: the plugin, the standalone program, the plugin binary run directly, or `docker docker-buildx`
  buildx_line
}

proxy_fix_lines() {
  local p=${1:-<proxy>}
  printf '%s\n' "The build needs the internet. Ask your IT for the proxy address." \
    "Your shell (also in ~/.bashrc):" \
    "\$ export HTTP_PROXY=$p HTTPS_PROXY=$p NO_PROXY=localhost,127.0.0.1 http_proxy=$p https_proxy=$p no_proxy=localhost,127.0.0.1" \
    "The Docker daemon (once, with sudo): /etc/systemd/system/docker.service.d/http-proxy.conf holds" \
    "  [Service]" \
    "  Environment=\"HTTP_PROXY=$p\" \"HTTPS_PROXY=$p\" \"NO_PROXY=localhost,127.0.0.1\"" \
    "\$ sudo systemctl daemon-reload && sudo systemctl restart docker" \
    "Then rerun ./demo.sh ${CMD:-setup}."
}

check_network() {
  local shell_proxy=${HTTPS_PROXY:-${https_proxy:-}}
  local daemon_proxy
  daemon_proxy=$(sed -n 's/^ *HTTPS Proxy: *//p' <<< "${DOCKER_INFO:-}" | head -n1)
  if curl -s --noproxy '*' -m 6 -o /dev/null "$PROBE_URL" 2>/dev/null; then
    ok "Internet: ghcr.io reachable directly"; return
  fi
  if [ -z "$shell_proxy" ]; then
    local IFS=$'\n'
    # shellcheck disable=SC2046
    fail "ghcr.io does not answer (timeout) and no proxy is set (HTTPS_PROXY)" $(proxy_fix_lines)
  fi
  if ! curl -s -m 10 -o /dev/null "$PROBE_URL" 2>/dev/null; then
    fail "ghcr.io does not answer through your proxy $shell_proxy" \
      "The proxy address may be wrong: check it with your IT, then:" \
      "\$ export HTTPS_PROXY=<proxy> https_proxy=<proxy>"
  fi
  if [ -z "$daemon_proxy" ]; then
    local IFS=$'\n'
    # shellcheck disable=SC2046
    fail "Your shell uses the proxy $shell_proxy, but the Docker daemon has none, so the build cannot pull its base images" \
      $(proxy_fix_lines "$shell_proxy")
  fi
  ok "Internet through the proxy $shell_proxy (shell and Docker daemon); the build uses it"
}

# check_ports: the device ports of this instance are free (unless its own containers hold them), before the build.
check_ports() {
  docker container inspect "$INSTANCE-api" >/dev/null 2>&1 && return 0
  local api web p busy=""
  api=${AWARECARE_DEMO_API_PORT:-$(config_value "['network']['api_port']")}
  web=${AWARECARE_DEMO_WEB_PORT:-$(config_value "['network']['web_port']")}
  for p in "$api" "$web"; do if port_busy "$p"; then busy+="${busy:+ and }$p"; fi; done
  case "$busy" in "") ;; *and*) busy="Ports $busy are" ;; *) busy="Port $busy is" ;; esac
  [ -z "$busy" ] || fail "$busy in use on this device (local uses API $api, web $web)" \
    "Another program holds it (see which: ss -ltnp | grep -E ':($api|$web) '). Run a second instance on other ports:" \
    "\$ ./demo.sh ${CMD:-local} --instance my-demo --api-port 28100 --web-port 28180"
  ok "Ports free: API 127.0.0.1:$api, web 127.0.0.1:$web"
}

check_model() {
  MODEL=$(device_model "$DEVICE")
  [ -n "$MODEL" ] || fail "No model chosen for this machine" "doctor says why:" "\$ ./demo.sh doctor"
  if zrt_resolve "$DEVICE"; then
    ok "ZRT serves $(served_as "$DEVICE") on $ZRT_URL"; note_revision; note_zrt_url; return
  fi
  local IFS=$'\n'
  # shellcheck disable=SC2046
  fail "ZRT does not serve $MODEL ($(device_repo "$DEVICE"), any revision) on $ZRT_URL" \
    "ZRT serves: $(served_list | grep . || echo nothing)" $(zrt_endpoint_lines "$DEVICE") $(model_fix_lines)
}

cmd_local() {
  start_log local
  find_device
  header "local mode$(on_device)" dry
  section "Checks"
  device_line
  dirty && note "The checkout has local changes; the images include them" "nothing, if you meant it (git -C $ROOT status shows them)"
  command -v python3 >/dev/null || fail "python3 is missing" "The deploy tool is a Python script; the system python3 is fine." "\$ sudo apt-get install python3"
  admin_check docker session  # #694
  check_session
  check_docker
  beside_running
  check_ports
  check_network
  section "Model"
  check_model
  deploy_tool
  build_deploy
}
# build_deploy: build the images and deploy them (local; setup's step 4), then the Open it box.
build_deploy() {
  local commit tag api_img web_img meta
  commit=$(git -C "$ROOT" rev-parse HEAD); tag=$(release_tag)
  api_img="$INSTANCE-api:local"; web_img="$INSTANCE-web:local"; meta="$LOG_DIR/build"; meta=${meta#"$ROOT"/}

  section "Build"
  long_run "Building the images" "Building the images (a few minutes the first time) ..." \
    infra/deploy/build_images.sh --platform "$(build_platform)" --commit "$commit" \
    --api-ref "$api_img" --web-ref "$web_img" --metadata-dir "$meta" --load
  [ "$DRY" = 1 ] || ok "Built $api_img and $web_img from commit ${commit:0:12} ($TOOK)"

  section "Deploy"
  replace_running
  local extra=()
  if [ "$DEVICE" = generic ]; then
    # #537: this machine's detected inventory and neutral prices for the API (mounted read-only), and its architecture
    run "Writing this machine's device files" python3 -I apps/api/app/runtime/hardware.py device-files \
      --model "$MODEL" --out "$DATA_ROOT/device"
    [ "$DRY" = 1 ] || ok "Device files ($DATA_ROOT/device: detected inventory, neutral prices)"
    DEPLOY+=(--device-files "$DATA_ROOT/device")
    extra=(--expected-arch "${HW_PLATFORM#linux/}")
  fi
  run "Creating the presenter key" "${DEPLOY[@]}" presenter-key
  [ "$DRY" = 1 ] || ok "Presenter key ($DATA_ROOT/secrets/presenter.key)"
  local deploy_args=(deploy --mode local --model-id "$MODEL" --release-tag "$tag" --app-commit "$commit"
    --api-image "$api_img" --web-image "$web_img" --no-pull --allow-unpinned "${extra[@]}")
  if [ "$DRY" = 1 ]; then
    run "Deploying" "${DEPLOY[@]}" "${deploy_args[@]}"
    info "Dry run: these commands were printed, not run."
  else
    doing "Deploying and running one synthetic consultation on the model (1 to 3 minutes) ..."
    printf '\n$ %s\n' "$(quote "${DEPLOY[@]}" deploy ...)" >> "$LOG"
    progress "${DEPLOY[@]}" "${deploy_args[@]}"
    local rc=$? outcome
    outcome=$(sed -n 's/^\[nano-deploy\] outcome: //p' "$LOG" | tail -n1)
    [ "$rc" = 0 ] || fail "Deploy failed: outcome ${outcome:-unknown}" \
      "The last lines of its log, below, name the failed step (docs/wiki/Troubleshooting.md has the usual ones). Then:" \
      "\$ ./demo.sh $CMD"
    ok "outcome: $outcome ($tag, commit ${commit:0:12}, model $MODEL, $TOOK)"
  fi
  open_app
}
# keep_sampler (#678; owner decision, 28 Oct 2026): the telemetry page measures the GPU's energy, and so the device's
# cost per consultation, only while the GPU power sampler runs. setup and local keep it running themselves: the deploy
# tool copies it, adds the one user crontab line that keeps this data root's sampler running (the runbook's line,
# section 10b: cron starts it within a minute, also after a reboot or without a login session; flock keeps one) and
# starts it now. A line already there is kept, so a rerun changes nothing. One per instance: each API reads its own
# data root. A local-mode deploy adds the line too (so does the deploy workflow on the maintainer's devices). A dry run
# prints the command and the line it would add.
json_field() { python3 -c 'import json, sys
try:
    print(json.load(sys.stdin).get(sys.argv[1]) or "")
except Exception:
    pass' "$1"; }
keep_sampler() {
  section "Telemetry"
  local out sampler=(python3 infra/deploy/nano_deploy.py --data-root "$DATA_ROOT" power-sampler)
  if [ "$DRY" = 1 ]; then
    cmdline "$(quote "${sampler[@]}")"
    out=$("${sampler[@]}" --dry-run 2>/dev/null)
    if grep -q '"would": "nothing"' <<< "$out"; then
      info "Your crontab already has the power sampler's line; nothing to add."
    else
      info "It adds this line to your crontab once (it keeps the GPU power sampler running for the telemetry page):"
      info "$(json_field line <<< "$out")"
    fi
    return 0
  fi
  if out=$("${sampler[@]}" 2>>"$LOG"); then
    if grep -q '"added": true' <<< "$out"; then
      ok "Power sampler on: a crontab line now keeps it running (a GPU power reading every second for the telemetry page)"
    else ok "Power sampler on: a crontab line keeps it running (a GPU power reading every second for the telemetry page)"; fi
  else
    note "Power sampler off: its crontab line could not be added ($(json_field error <<< "$out")), so the telemetry page shows the energy and the device's cost as not measured" \
      "make crontab usable for ${USER:-$(id -un)} (an administrator installs cron), then rerun ./demo.sh ${CMD:-setup}"
  fi
}
# sampler_line (#678; status, doctor): this data root's power sampler in one line: kept running by a crontab line, and
# its last reading (the telemetry page counts it active within 15 s), or off. Reads only.
sampler_line() {
  local dr kept=0 newest="" age=""
  dr=$(realpath -m -- "$DATA_ROOT" 2>/dev/null || echo "$DATA_ROOT")
  if crontab -l 2>/dev/null | grep -v '^[[:space:]]*#' | grep -qF " $dr/telemetry/power_sampler.py "; then kept=1; fi
  newest=$(find "$dr/data/local/power" -maxdepth 1 -name '*.csv' -printf '%T@\n' 2>/dev/null | sort -n | tail -n1)
  [ -z "$newest" ] || age=$(( $(date +%s) - ${newest%.*} ))
  if [ "$kept" = 0 ]; then
    info "Power sampler: off, so the telemetry page shows energy as not measured (./demo.sh setup or local turns it on)"
  elif [ -n "$age" ] && [ "$age" -le 15 ]; then
    ok "Power sampler: on (a crontab line keeps it running; last reading ${age} s ago)"
  elif [ -n "$age" ]; then
    note "Power sampler: its crontab line is there, but its last reading is $(elapsed "$age") old" \
      "cron starts it within a minute; if this stays, $dr/telemetry/sampler.log says why"
  else
    note "Power sampler: its crontab line is there, but it has written no reading yet" \
      "cron starts it within a minute; if this stays, $dr/telemetry/sampler.log says why"
  fi
}
open_app() {  # the Open it box for the deployed app (local, setup)
  keep_sampler
  local web browser
  web=${AWARECARE_DEMO_WEB_PORT:-$(config_value "['network']['web_port']")}
  browser=${PORT:-$(config_value "['network']['browser_origin']" | sed 's/.*://')}
  open_it "$browser" "$web"
  local where
  where=$(instance_args)
  if [ -n "$where" ]; then next_steps "Status: ./demo.sh status$where"; next_steps "Stop: ./demo.sh stop local$where"  # #665
  else next_steps "Status: ./demo.sh status    Stop: ./demo.sh stop"; fi
}
instance_args() {  # #560: the options that name a second instance (empty for the default one), for printed commands
  local out=""
  [ "$INSTANCE" = "$DEFAULT_INSTANCE" ] || out+=" --instance $INSTANCE"
  [ -z "${AWARECARE_DEMO_API_PORT:-}" ] || out+=" --api-port $AWARECARE_DEMO_API_PORT"
  [ -z "${AWARECARE_DEMO_WEB_PORT:-}" ] || out+=" --web-port $AWARECARE_DEMO_WEB_PORT"
  printf '%s' "$out"
}

# ------------------------------------------------------------------ setup (#549)

# setup: everything after the clone, in order, with the code paths of doctor, model and local; the first ✗ stops it
# with its fix. 1. the doctor checks; 2. the model: nothing when ZRT serves it, else a copy ZRT has downloaded, else
# the download (its size first), then the unit; 3. the wait until ZRT lists it; 4. the build and deploy, skipped when
# the app already runs this commit (a clean checkout) with this model and ZRT address and answers ready (--rebuild
# builds and deploys anyway); 5. the Open it box. A rerun skips what is done. --mock: mock mode instead (no Docker, no
# model); --dry-run: prints what it would do and changes nothing.
cmd_setup() {
  if [ "$MOCK_OPT" = 1 ]; then setup_mock; return; fi
  start_log setup
  find_device
  header "setup$(on_device)" dry
  DOC_STRICT=1
  # #644, #696: beside someone else's running demo, setup says how to open it before any check (--replace goes on)
  [ "$REPLACE" = 1 ] || beside_running
  # #694: everything an administrator must do once, in one block, before any download
  section "Administrator"
  admin_check docker session zrt linger
  admin_ok
  doctor_checks
  [ -n "$DEVICE" ] || device_line  # no model for this machine: stops with the fix
  dirty && note "The checkout has local changes; the images include them" "nothing, if you meant it (git -C $ROOT status shows them)"
  [ "$REPLACE" = 0 ] || beside_running
  model_steps "Serve the model"
  MODEL=$(device_model "$DEVICE")
  deploy_tool
  if [ "$REBUILD" = 0 ] && [ "${REPLACING:-0}" = 0 ] && app_current; then
    section "App"
    ok "$APP_LINE; nothing to build or deploy (--rebuild builds and deploys again)"
    open_app
    return 0
  fi
  build_deploy
}
# app_current: whether the deployment runs this checkout's commit (no local changes) in local mode with this model and
# ZRT address, both containers run and it answers ready (nano_deploy.py status, read-only). Sets APP_LINE.
app_current() {
  local json
  ! dirty || return 1
  json=$("${DEPLOY[@]}" status 2>/dev/null) || return 1
  APP_LINE=$(python3 - "$json" "$(git -C "$ROOT" rev-parse HEAD 2>/dev/null)" "$MODEL" "$ZRT_URL" <<'PY'
import json, sys
s, head, model, zrt = json.loads(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]
cur, cons = s.get("current") or {}, s.get("containers") or {}
if not (head and cur.get("mode") == "local" and cur.get("app_commit") == head and cur.get("model_id") == model
        and all((cons.get(role) or {}).get("running") for role in ("api", "web"))
        and (s.get("readiness") or {}).get("readiness") == "ready"
        and (s.get("model_base_url") or "").rstrip("/") == zrt.rstrip("/")):
    sys.exit(1)
print(f"The app already runs commit {head[:12]} with {model} on {zrt.rstrip('/')} and answers ready")
PY
  )
}
# setup --mock: mock mode (cmd_mock), or nothing when it already runs and answers ready on the same ports.
setup_mock() {
  if mock_running && [ "$DRY" = 0 ]; then
    local API_PORT="" WEB_PORT="" BROWSER_PORT=""
    # shellcheck disable=SC1090
    . "$MOCK_STATE"
    if { [ -z "$PORT" ] || [ "$PORT" = "$BROWSER_PORT" ]; } \
       && curl -s --noproxy '*' -m 3 "http://127.0.0.1:$WEB_PORT$READY_PATH" 2>/dev/null | grep -q '"readiness":"ready"'; then
      header "setup · mock mode (no model, scripted synthetic results)"
      section "Mock"
      ok "Mock mode already runs (API 127.0.0.1:$API_PORT, web 127.0.0.1:$WEB_PORT) and answers ready; nothing to do"
      open_it "$BROWSER_PORT" "$WEB_PORT"
      next_steps "Stop: ./demo.sh stop"
      return 0
    fi
  fi
  CMD=mock
  cmd_mock
}

# ------------------------------------------------------------------ model

# The revision the unit serves lives in ~/.config/aware-care-demo/model.env (AWARECARE_MODEL_REVISION, read by the
# unit and the serve script), so another downloaded revision needs no edit of the script (#528).
MODEL_ENV="$HOME/.config/aware-care-demo/model.env"
POLL=${AWARECARE_DEMO_POLL_SECONDS:-5}  # how often the model wait looks (tests shorten it)

env_value() { sed -n "s/^$1=//p" "$MODEL_ENV" 2>/dev/null | tail -n1; }
# write_model_env <NAME=value | -NAME>...: model.env with each NAME set to its value (or its line dropped, -NAME) and
# every other line kept. #609: written whole to a new file beside it and moved over it, every step checked, so model.env
# changes completely or not at all; it returns non-zero (the old file untouched) when any step fails.
write_model_env() {
  local spec pats=() tmp dir
  dir=$(dirname "$MODEL_ENV")
  mkdir -p "$dir" 2>/dev/null || return 1
  for spec in "$@"; do spec=${spec#-}; pats+=(-e "^${spec%%=*}="); done
  tmp=$(mktemp "$MODEL_ENV.XXXXXX" 2>/dev/null) || return 1
  if [ -e "$MODEL_ENV" ] || [ -L "$MODEL_ENV" ]; then
    grep -v "${pats[@]}" "$MODEL_ENV" > "$tmp" 2>/dev/null
    [ $? -le 1 ] || { rm -f "$tmp"; return 1; }  # 1: no other line; 2: unreadable or not a file
  fi
  for spec in "$@"; do
    [[ $spec == -* ]] || printf '%s\n' "$spec" >> "$tmp" || { rm -f "$tmp"; return 1; }
  done
  if ! chmod 644 "$tmp" || ! mv -fT "$tmp" "$MODEL_ENV" 2>/dev/null; then rm -f "$tmp"; return 1; fi
}
catalog_size() {  # catalog_size <label>: the download size in GB from infra/models/catalog.json
  python3 -c 'import json,sys
for e in json.load(open(sys.argv[1]))["models"]:
    if e["label"] == sys.argv[2]: print(e["size_gb"])' "$ROOT/infra/models/catalog.json" "$1" 2>/dev/null
}
# model_timeout: the usual wait for the model (--timeout, else 15 min on a Nano, 8 on a Fury; tests: AWARECARE_DEMO_MODEL_WAIT)
model_timeout() {
  if [ -n "$TIMEOUT" ]; then echo "$TIMEOUT"
  elif [ -n "${AWARECARE_DEMO_MODEL_WAIT:-}" ]; then echo "$AWARECARE_DEMO_MODEL_WAIT"
  elif [ "$DEVICE" = fury ]; then echo 480; else echo 900; fi
}
# model_starting (#704, case 8): demo.sh's model unit is starting (or active) and ZRT's service for the model is alive but not
# Ready yet; prints how far it is. Status 2: ZRT's service loads outside the unit.
model_starting() {
  local svc pid status up active
  active=$(unit_prop ActiveState)
  svc=$(zrt_service); pid=${svc%%|*}; status=$(cut -d'|' -f2 <<< "$svc"); up=${svc##*|}
  if [ -n "$pid" ] && ps -p "$pid" >/dev/null 2>&1 && [ "$status" != Ready ]; then
    if [ "$active" = activating ] || [ "$active" = active ]; then
      echo "ZRT's service for it (PID $pid, $status) has run for $(elapsed "${up:-0}"); demo.sh waits for it instead of starting it again"
      return 0
    fi
    case "$active" in inactive|"") echo "PID $pid, $status, for $(elapsed "${up:-0}")"; return 2 ;; esac
  fi
  return 1
}
# start_usual (#697): how long the model usually takes to start here, in words
start_usual() { case "$DEVICE" in nano) echo "about 6 min" ;; fury) echo "about 2 min" ;; *) echo "several minutes" ;; esac; }
# download_hint <seconds> (#697): the download's progress from the size of ZRT's copy (DL_DIR, minus what was there,
# DL_BASE) against the catalogue's size (DL_GB): "12.3 of 37.5 GB, about 10 min left"
download_hint() {
  local now done_b total_b left
  now=$(du -sb -- "$DL_DIR" 2>/dev/null | cut -f1)
  done_b=$(( ${now:-0} - ${DL_BASE:-0} )); [ "$done_b" -ge 0 ] || done_b=0
  total_b=$(awk -v g="${DL_GB:-0}" 'BEGIN { printf "%d", g * 1e9 }')
  if [ "$done_b" -le 0 ] || [ "$1" -le 0 ]; then echo "Download: starting (about ${DL_GB} GB)"; return; fi
  if [ "$total_b" -le 0 ]; then echo "Download: $(awk -v b="$done_b" 'BEGIN { printf "%.1f", b / 1e9 }') GB so far"; return; fi
  left=$(awk -v d="$done_b" -v t="$total_b" -v s="$1" 'BEGIN { r = d / s; x = (t - d) / r; if (x < 0) x = 0; printf "%d", x / 60 + 0.5 }')
  awk -v d="$done_b" -v g="$DL_GB" -v m="$left" 'BEGIN { printf "Download: %.1f of %s GB, about %s left\n", d / 1e9, g,
    (m < 1 ? "1 min" : m " min") }'
}
# gpu_fraction (#702, case 6): the share of the GPU's memory the serve settings ask for (the device's serve script, or
# the catalogue's settings on another machine); empty when unknown
gpu_fraction() {
  if [ "$DEVICE" = generic ]; then
    hardware serve-args --model "$(device_model "$DEVICE")" --tp "${M_TP:-1}" 2>/dev/null | sed -n 's/^--gpu-memory-fraction=//p' | head -n1
  else
    grep -o -- '--gpu-memory-fraction[ =][0-9.]*' "$ROOT/infra/$DEVICE/zrt/serve-model.sh" 2>/dev/null | head -n1 | tr -dc '0-9.'
  fi
}
# check_gpu_room (#702, case 6): before a download or a start, the GPU has the memory the model asks for. Another
# model filled it on the Fury (151.6 of 256.7 GB on port 8000): the download ran, then the start would fail. A GPU
# that reports no memory figures (a GB10's unified memory) is not checked.
check_gpu_room() {
  local frac row total used free need others="" fix="" me=${USER:-$(id -un)} pid name mem owner svc
  frac=$(gpu_fraction); [ -n "$frac" ] || return 0
  row=$(nvidia-smi --query-gpu=memory.total,memory.used --format=csv,noheader,nounits 2>/dev/null | head -n1 | tr -d ' ')
  total=${row%%,*}; used=${row##*,}
  case "$total$used" in ''|*[!0-9]*) return 0 ;; esac
  free=$(( (total - used + 512) / 1024 )); need=$(awk -v f="$frac" -v t="$total" 'BEGIN { printf "%d", f * t / 1024 + 0.999 }')
  if [ "$free" -ge "$need" ]; then
    ok "GPU memory: $free GB free; the model asks for about $need GB ($frac of $((total / 1024)) GB)"; return 0
  fi
  while IFS=, read -r pid name mem; do
    pid=${pid// /}; [ -n "$pid" ] || continue
    owner=$(ps -o user= -p "$pid" 2>/dev/null | tr -d ' ')
    others+="${others:+; }PID $pid${name:+ ($(basename "${name# }"))}${mem:+,${mem}}${owner:+, run by $owner}"
  done < <(nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader 2>/dev/null)
  # a model of your own ZRT that is not this one: stop it (zrt services names its URI)
  svc=$(zrt_rows "$DEVICE" | awk -F'\t' '$1 == 0 && $8 != "" && $8 != "-" { print $8; exit }')
  if [ -n "$svc" ]; then fix="\$ zrt -m ${ZRT_MODE:-system} service stop $svc"; fi
  local IFS=$'\n'
  # shellcheck disable=SC2046
  fail "The GPU has $free GB free, and $(device_model "$DEVICE") asks for about $need GB ($frac of $((total / 1024)) GB), so it would not start" \
    "Other processes fill it${others:+: $others}." \
    $(if [ -n "$fix" ]; then echo "Your ZRT serves another model ($svc). Stop it first (nothing is downloaded until there is room):"; echo "$fix"
      else echo "They are not yours to stop: ask whoever runs them (${others:+see above; }nvidia-smi shows them), then rerun ./demo.sh ${CMD:-setup}."; fi)
}
# adopt_model (#702, case 5): the model is served by a ZRT service process of this account, but not through demo.sh's
# unit: it was started by hand (zrt service start). It has no unit and no watchdog, so it
# does not come back after a crash or a reboot. Install them; start the unit only when its serve script will see the
# model served (it then exits at once), so a second copy is never started.
# started_by_hand (after zrt_resolve): ZRT serves the model through a service process of this account (vLLM runs as
# the account that started it, also in system mode), and demo.sh's unit is not enabled
started_by_hand() {
  local pid
  others_model && return 1
  [ "$(systemctl --user is-enabled "$UNIT" 2>/dev/null)" = enabled ] && return 1
  pid=$(zrt_service); pid=${pid%%|*}
  [ -n "$pid" ] && [ "$(ps -o user= -p "$pid" 2>/dev/null | tr -d ' ')" = "$(id -un)" ]
}
adopt_model() {
  started_by_hand || return 0
  local zrt="infra/$DEVICE/zrt" label repo id=${MATCH_ID:-}
  label=$(device_model "$DEVICE"); repo=$(device_repo "$DEVICE")
  section "Unit"
  note "ZRT serves the model, but it was started outside demo.sh: no unit and no watchdog, so it would not come back after a crash or a reboot" \
    "nothing: demo.sh adds its unit and watchdog now (the model keeps running)"
  run "Installing the unit" install -D -m 644 "$zrt/$UNIT" "$HOME/.config/systemd/user/$UNIT"
  run "Installing the serve script" install -D -m 755 "$zrt/serve-model.sh" "$HOME/.local/share/aware-care-demo/zrt/serve-model.sh"
  install_watchdog
  run "systemctl daemon-reload" systemctl --user daemon-reload
  run "Enabling $UNIT" systemctl --user enable "$UNIT"
  shopt -s nocasematch
  if [[ $id =~ ^(hf:)?($label|$repo)(@.*)?$ ]]; then
    shopt -u nocasematch
    run "Starting $UNIT (the model is served, so it only records that)" systemctl --user start --no-block "$UNIT"
    start_watchdog
  else
    shopt -u nocasematch
    info "The unit starts the model at the next boot; ZRT serves it as $id now, so it is not started twice."
    start_watchdog
  fi
  [ "$DRY" = 1 ] || ok "Unit $UNIT and its watchdog keep the model running"
}

# #644: past the usual wait, a first start in a fresh ZRT still loads, then builds its GPU kernels (about 25 minutes on
# the Fury). wait_for_model keeps waiting while ZRT's service process for the model lives and ZRT's log for the model
# changes; it stops as stuck after STUCK seconds without a change, and at MAX_WAIT in all. --timeout stays a hard limit.
STUCK=${AWARECARE_DEMO_STUCK_SECONDS:-600} MAX_WAIT=${AWARECARE_DEMO_MAX_WAIT_SECONDS:-3600}
EVERY=${AWARECARE_DEMO_STATUS_SECONDS:-30}  # a status line this often (tests shorten it)
unit_prop() { systemctl --user show -p "$1" --value "$UNIT" 2>/dev/null; }
journal_tail() { journalctl --user -u "$UNIT" -n "$1" --no-pager -o cat 2>/dev/null; }
linger_on() { [ "$(loginctl show-user "$USER" -p Linger --value 2>/dev/null)" = yes ]; }

# The CUDA toolchain the serve script will use (#533): the script's own choice (`serve-model.sh cuda`), with the
# AWARECARE_CUDA_HOME of model.env.
cuda_choice() { AWARECARE_CUDA_HOME=$(env_value AWARECARE_CUDA_HOME) bash "$ROOT/infra/$DEVICE/zrt/serve-model.sh" cuda 2>/dev/null; }
cuda_preferred() {
  if [ "$DEVICE" = generic ]; then cuda_choice || echo "a CUDA toolkit"; return; fi
  echo "${AWARECARE_CUDA_ROOT:-/usr/local}/$(sed -n 's/^CUDA_PREFERRED=//p' "$ROOT/infra/$DEVICE/zrt/serve-model.sh")"
}
cuda_dirs() {
  local d out=""
  for d in "${AWARECARE_CUDA_ROOT:-/usr/local}"/cuda*; do
    [ -e "$d" ] || continue
    if [ -x "$d/bin/nvcc" ]; then out+="$d (nvcc), "; else out+="$d (no nvcc), "; fi
  done
  echo "${out%, }"
}
cuda_fix() {  # cuda_fix <dir>: how to point the unit at another toolchain
  printf '%s\n' "Point the unit at it, then restart the unit (systemctl --user restart $UNIT):" \
    "\$ echo AWARECARE_CUDA_HOME=$1 >> $MODEL_ENV"
}
# cuda_version <dir> (#644): the CUDA release of a toolchain, from its bin/nvcc --version ("release 13.0, V13.0.48")
cuda_version() { "$1/bin/nvcc" --version 2>/dev/null | sed -n 's/.*release \([0-9][0-9]*\.[0-9][0-9]*\).*/\1/p' | head -n1; }
# cuda_line (#644, doctor and setup): the CUDA the serve script will use and its version; a warning below 13 (the
# Nano's and the Fury's kernels need CUDA 13; /usr/bin/nvcc on the Fury is 12.0). Returns 1 when it chooses none.
cuda_line() {
  local cuda v
  cuda=$(cuda_choice) || return 1
  v=$(cuda_version "$cuda")
  if [ -z "$v" ]; then ok "CUDA for the serve script: $cuda (bin/nvcc --version names no release)"
  elif [ "${v%%.*}" -lt 13 ]; then
    note "CUDA for the serve script: $cuda is CUDA $v, older than 13 (the model's GPU kernels need CUDA 13)" \
      "point it at a CUDA 13 toolkit: echo AWARECARE_CUDA_HOME=<a cuda-13 directory> >> $MODEL_ENV" \
      "(none installed? an administrator installs the CUDA 13 toolkit)"
  else ok "CUDA for the serve script: $cuda (CUDA $v, from bin/nvcc --version)"; fi
}
check_cuda() {
  local cuda want
  want=$(cuda_preferred)
  if cuda=$(cuda_choice); then
    if [ "$cuda" = "$want" ]; then ok "CUDA toolchain: $cuda"
    else note "$want is not installed here; the serve script uses $cuda (found: $(cuda_dirs))" "nothing, if the model starts"; fi
    return 0
  fi
  local IFS=$'\n'
  # shellcheck disable=SC2046
  fail "No CUDA toolchain with bin/nvcc for the serve script (it wants $want; found: $(cuda_dirs | grep . || echo none))" \
    $(cuda_fix "<a CUDA 13 directory with bin/nvcc>") "No CUDA 13 at all? An administrator installs the CUDA 13 toolkit."
}

# zrt_service: "<pid>|<status>|<uptime seconds>" of the ZRT service that serves this device's model, from the table
# `zrt services` prints (zrt_rows; both of its layouts, #535).
zrt_service() { zrt_rows "$DEVICE" | awk -F'\t' '$1 == 1 { print $2 "|" $3 "|" $6; exit }'; }
unit_age() {  # seconds since the unit began activating
  local since
  since=$(unit_prop InactiveExitTimestamp)
  [ -n "$since" ] && since=$(date -d "$since" +%s 2>/dev/null) && echo $(($(date +%s) - since))
}

# model_log: ZRT's own log for the device's model, the newest vllm-*<repo>*.log in its run directory (ZRT names it
# vllm-hf-<org>-<name>-<revision>.log, lower case, each other character a "-"); empty when none can be read.
model_log() {
  local slug f best=""
  slug=$(device_repo "$DEVICE" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/-/g')
  for f in "$(zrt_run_dir)"/vllm-*"$slug"*.log; do
    [ -r "$f" ] || continue
    if [ -z "$best" ] || [ "$f" -nt "$best" ]; then best=$f; fi
  done
  echo "$best"
}
# log_mark <log>: what changes when ZRT's log for the model grows: the file's size and time, else (a run directory this
# account cannot read) the last lines `zrt logs tail` prints.
log_mark() {
  if [ -n "$1" ]; then stat -c '%s %Y' -- "$1" 2>/dev/null; return; fi
  timeout 10 "$(find_zrt || echo zrt)" -m "${ZRT_MODE:-system}" logs tail "$(device_model "$DEVICE")" --lines 20 2>/dev/null | cksum
}

# wait_for_model: polls until ZRT lists the model; stops early when the unit failed or stopped, when ZRT's service
# keeps restarting (its PID changes, or it is younger than the unit's start while not Ready), when the unit finished
# and no ZRT service process for the model is left (#636: ZRT 0.43 on the Fury lists a loading service as Dead after
# the oneshot unit finished; it served the model a minute later). #644: past the usual wait (model_timeout) it goes on
# only while that process lives and ZRT's log for the model changes: stuck after STUCK seconds without a change, never
# longer than MAX_WAIT; --timeout is a hard limit. Prints a status line every 30 seconds that says why it still waits.
# Sets TOOK, or WAIT_WHY on failure.
wait_for_model() {
  local start=$SECONDS limit t last=-$EVERY active sub restarts svc pid status up age seen="" changes=0 line i=0 k
  local frames=(⠋ ⠙ ⠹ ⠸ ⠼ ⠴ ⠦ ⠧ ⠇ ⠏) log mark="" was="" changed=0 alive why label
  limit=$(model_timeout); WAIT_WHY=""; label=$(device_model "$DEVICE")
  while :; do
    t=$((SECONDS - start))
    if zrt_resolve "$DEVICE"; then [ "$SPIN" = 0 ] || printf '\r\033[K'; TOOK=$(elapsed "$t"); return 0; fi
    active=$(unit_prop ActiveState); sub=$(unit_prop SubState); restarts=$(unit_prop NRestarts)
    svc=$(zrt_service); pid=${svc%%|*}; status=$(cut -d'|' -f2 <<< "$svc"); up=${svc##*|}
    if [ -n "$pid" ]; then
      if [ -n "$seen" ] && [ "$pid" != "$seen" ]; then changes=$((changes + 1)); fi
      seen=$pid
    fi
    alive=0; if [ -n "$pid" ] && ps -p "$pid" >/dev/null 2>&1; then alive=1; fi
    log=$(model_log); mark=$(log_mark "$log")
    if [ "$mark" != "$was" ]; then was=$mark; changed=$t; fi
    age=$(unit_age)
    if [ "$active" = failed ]; then WAIT_WHY="The unit $UNIT failed ($sub)"
    elif [ "$active" = inactive ] && [ "$t" -ge 15 ]; then WAIT_WHY="The unit $UNIT stopped (inactive, ${sub:-dead})"
    elif [ "${restarts:-0}" -ge 3 ]; then WAIT_WHY="The unit $UNIT restarted $restarts times"
    elif [ "$changes" -ge 2 ]; then WAIT_WHY="ZRT's service for the model keeps restarting (PID changed $changes times; now $pid, $status)"
    elif [ "$active" = activating ] && [ -n "$svc" ] && [ "$status" != Ready ] && [ -n "$age" ] \
         && [ "$age" -ge 300 ] && [ $((up + 120)) -lt "$age" ]; then
      WAIT_WHY="ZRT's service for the model keeps restarting: the unit has been starting for $(elapsed "$age"), but the service (PID $pid, $status) is only $(elapsed "$up") old"
    elif [ "$active" = active ] && [ "$sub" = exited ] && [ "$t" -ge "${AWARECARE_DEMO_FINISHED_GRACE:-60}" ] \
         && [ "$alive" = 0 ]; then
      WAIT_WHY="The unit $UNIT finished, but ZRT does not list $label"
    elif [ "$t" -ge "$limit" ]; then
      if [ -n "$TIMEOUT" ]; then WAIT_WHY="ZRT did not serve $label within $(elapsed "$limit") (--timeout)"
      elif [ "$alive" = 0 ]; then WAIT_WHY="ZRT did not serve $label within $(elapsed "$limit"), and no ZRT service process for it runs"
      elif [ "$t" -ge "$MAX_WAIT" ]; then WAIT_WHY="ZRT did not serve $label within $(elapsed "$MAX_WAIT"), the longest demo.sh waits"
      elif [ $((t - changed)) -ge "$STUCK" ]; then
        WAIT_WHY="ZRT's service for $label looks stuck: its log (${log:-zrt logs tail $label}) has not changed for $(elapsed $((t - changed)))"
      fi
    fi
    if [ -n "$WAIT_WHY" ]; then [ "$SPIN" = 0 ] || printf '\r\033[K'; return 1; fi
    if [ $((t - last)) -ge "$EVERY" ]; then
      [ "$SPIN" = 0 ] || printf '\r\033[K'
      line=$(journal_tail 1 | tail -n1 | cut -c1-90)
      # #697: how long it usually takes, how long it has run, and why it still waits
      if [ "$t" -lt "$limit" ]; then why="Model start: $(elapsed "$t") so far (usually $(start_usual) here)"
      else why="Model start: $(elapsed "$t") so far, past $(elapsed "$limit"), still loading: its process (PID $pid) runs and its log changed $(elapsed $((t - changed))) ago (a first start takes up to 25 min)"; fi
      info "$why; unit ${active:-unknown}${sub:+ ($sub)}${svc:+; ZRT service $status, PID $pid}${line:+; $line}"
      last=$t
    fi
    if [ "$SPIN" = 1 ]; then
      for ((k = 0; k < POLL * 5; k++)); do
        printf '\r\033[K    %s%s %s · Model start: %s%s' "$CYN" "${frames[i++ % 10]}" "$(elapsed $((SECONDS - start)))" \
          "$(start_usual)" "$X"; sleep 0.2
      done
    else
      sleep "$POLL"
    fi
  done
}

# model_diagnosis: the known causes found now, each with its fix (#533).
model_diagnosis() {
  local journal cuda want label
  journal=$(journal_tail 50)
  label=$(device_model "$DEVICE"); want=$(cuda_preferred)
  if ! cuda=$(cuda_choice); then
    echo "CUDA: no toolchain with bin/nvcc (wanted $want; found: $(cuda_dirs | grep . || echo none))."
    cuda_fix "<a CUDA 13 directory with bin/nvcc>"
  elif [ "$cuda" != "$want" ] || grep -qiE 'nvcc|cuda_home|cuda-1[0-9]' <<< "$journal"; then
    echo "CUDA: the serve script uses $cuda (qualified: $want; found: $(cuda_dirs)). If the journal shows CUDA errors, pick another one."
    cuda_fix "$cuda"
  fi
  # #644: the model's own processes (ZRT's service and its children, such as vLLM's VLLM::EngineCore) are never
  # "another process" to stop
  local svc row own="" others="" oom=0
  svc=$(zrt_service); svc=${svc%%|*}
  while IFS= read -r row || [ -n "$row" ]; do
    [ -n "$row" ] || continue
    if own_process "${row%%,*}" "$svc"; then own+="${own:+; }$row"; else others+="${others:+; }$row"; fi
  done < <(nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader 2>/dev/null)
  if grep -qiE 'out of memory|free memory on device|insufficient memory' <<< "$journal"; then oom=1; fi
  if [ -n "$others" ]; then
    echo "GPU memory: other processes use the GPU now: $others. If one is a model you do not need, stop it (zrt services, then zrt service stop <uri>)."
  elif [ "$oom" = 1 ]; then
    echo "GPU memory: the journal reports too little GPU memory, and no other process uses the GPU now${own:+ (only the processes of this model: $own)}."
  fi
  if ! curl -s --noproxy '*' -m 5 -o /dev/null "$ZRT_URL/models" 2>/dev/null || ! find_zrt >/dev/null; then
    if [ "${ZRT_MODE:-system}" = user ]; then
      echo "ZRT: nothing answers on $ZRT_URL yet (or zrt is missing). ZRT in user mode runs as you: check zrt -m user services."
    else
      echo "ZRT: its proxy does not answer on $ZRT_URL (or zrt is missing). Check: zrt services. ZRT runs as a system service: ask an administrator to start it."
    fi
  fi
  linger_on || echo "Lingering is off, so the model stops when you log out (an administrator runs, once: sudo loginctl enable-linger ${USER:-$(id -un)})."
  echo "ZRT's own log (zrt $([ "${ZRT_MODE:-system}" = system ] || echo "-m $ZRT_MODE ")logs tail $label --lines 50), its last lines:"  # #636: `zrt logs <model>` only prints help
  local z; if z=$(find_zrt); then timeout 10 "$z" -m "${ZRT_MODE:-system}" logs tail "$label" --lines 8 2>&1 | sed 's/^/  | /'; fi
  echo "More: systemctl --user status $UNIT; journalctl --user -u $UNIT -n 100. Fix the cause, then start it again:"
  echo "\$ ./demo.sh model"
}
# own_process <pid> <service pid> (#644): whether pid is ZRT's service process for the model or one of its descendants
own_process() {
  local p=$1 n
  [ -n "$2" ] || return 1
  for ((n = 0; n < 32; n++)); do
    [ "$p" != "$2" ] || return 0
    p=$(ps -o ppid= -p "$p" 2>/dev/null | tr -d ' ')
    case "$p" in ''|0|1) return 1 ;; esac
  done
  return 1
}
model_failed() {
  LOG="$LOG_DIR/model-journal-$(date +%Y%m%d-%H%M%S).log" TAIL_N=25
  LOG_TITLE="Journal (journalctl --user -u $UNIT -n 25)"
  journal_tail 25 > "$LOG"
  local IFS=$'\n'
  # shellcheck disable=SC2046
  fail "$WAIT_WHY" $(model_diagnosis)
}

cmd_model() {
  start_log model
  find_device
  header "serve the model with ZRT$(on_device)" dry
  section "Checks"
  device_line
  admin_check session zrt linger  # #694
  admin_ok
  model_steps Model
}
# model_steps <section>: serve the device's model (model; setup's step 2 and 3): nothing when ZRT serves it, else a
# downloaded copy or the download, the unit, its start and the wait until ZRT lists the model.
model_steps() {
  local model hf repo qualified zrt
  model=$(device_model "$DEVICE"); hf=$(device_hf "$DEVICE"); repo=$(device_repo "$DEVICE")
  qualified=$(qualified_rev "$DEVICE"); zrt="infra/$DEVICE/zrt"
  section "$1"
  if zrt_resolve "$DEVICE"; then
    ok "ZRT already serves $(served_as "$DEVICE") on $ZRT_URL; nothing to do"; note_revision
    [ "$DOC_STRICT" = 1 ] || note_zrt_url  # setup's checks said it already
    adopt_model  # #702 (case 5): a model started outside demo.sh gets its unit and watchdog
    # #640: the watchdog of a model unit installed earlier (one installed before the watchdog existed gets it now);
    # nothing when it is installed as this checkout has it and on (so a rerun of setup changes nothing)
    # #666: only for a unit that is enabled (a leftover, never enabled unit does not serve the model)
    if [ -e "$HOME/.config/systemd/user/$UNIT" ] && [ "$(systemctl --user is-enabled "$UNIT" 2>/dev/null)" = enabled ] \
       && ! watchdog_current; then
      section "Watchdog"
      install_watchdog
      run "systemctl daemon-reload" systemctl --user daemon-reload
      start_watchdog
    fi
    return 0
  fi
  # #704 (case 8): a rerun while the model still loads (a slow first start taken for a failure) waits for that start:
  # no GPU check (the memory in use is the model's own) and no restart (which would throw the load away)
  local starting rc=0
  starting=$(model_starting) || rc=$?
  [ "$rc" != 2 ] || fail "ZRT is already starting $model outside demo.sh's unit ($starting)" \
    "Starting it again would need the GPU memory twice. Wait until zrt services shows it Ready, then rerun:" "\$ ./demo.sh ${CMD:-setup}"
  if [ "$rc" = 0 ]; then
    ok "The model is still starting: $starting"
    info "Model start: $(start_usual) here; a first start in a fresh ZRT takes up to 25 min (it builds the GPU kernels)."
    if [ "$DRY" = 1 ]; then info "Dry run: demo.sh would wait for it; nothing is started again."; return 0; fi
    doing "Waiting for $model (it is not started again) ..."
    wait_for_model || model_failed
    ok "ZRT serves $(served_as "$DEVICE") on $ZRT_URL ($TOOK)"
    note_zrt_url
    return 0
  fi
  local z
  z=$(find_zrt) || { [ "$DRY" = 1 ] && z=zrt; } \
    || fail "The zrt command is missing" "ZRT serves the model. It is preinstalled on ZGX devices; elsewhere an administrator installs it."
  # #549: ZRT serves a model through its proxy, on the port ZRT is set to; another port asked for is ZRT's setting
  local want; want=$(url_port "$ZRT_URL")
  if [ -n "$ZRT_CONFIG_PORT" ] && [ "$want" != "$ZRT_CONFIG_PORT" ]; then
    fail "ZRT's proxy is set to port $ZRT_CONFIG_PORT (zrt config get proxy.port), so ZRT would serve $model there, not on $want ($ZRT_URL_FROM)" \
      "ZRT serves a model through its proxy. Use ZRT's port (or leave out --zrt-port, --zrt-url and AWARECARE_ZRT_URL):" \
      "\$ ./demo.sh $CMD --zrt-port $ZRT_CONFIG_PORT" \
      "Or set ZRT's proxy to port $want first (zrt -m ${ZRT_MODE:-system} config set proxy.port $want; in system mode it holds for" \
      "every user of ZRT on this machine, so an administrator decides), then rerun ./demo.sh $CMD."
  fi
  check_cuda
  check_gpu_room  # #702 (case 6): before any download or start
  # #528: serve a copy ZRT already has (any revision) before downloading the qualified one.
  local rev sys
  rev=$(local_copy "$DEVICE" "$REVISION")
  if [ -n "$rev" ]; then
    ok "ZRT already has $repo@$rev downloaded; serving that copy (no download)"
  elif sys=$(system_copy "$DEVICE" "$REVISION"); then
    system_copy_fix "$sys"
  else
    rev=${REVISION:-$qualified}
    local size
    size=$(catalog_size "$model")
    [ -z "$size" ] || info "Download: $repo@$rev, about $size GB (once; ZRT keeps it in its cache)"
    # #697: how far it got and how long is left, from the size of ZRT's copy as it grows
    DL_DIR="$(zrt_store)/hf/$repo" DL_GB=${size:-0}
    DL_BASE=$(du -sb -- "$DL_DIR" 2>/dev/null | cut -f1); DL_BASE=${DL_BASE:-0}
    PROGRESS_HINT=download_hint long_run "zrt pull" "Downloading $repo@$rev (this can take a long time) ..." \
      "$z" -m "${ZRT_MODE:-system}" pull "hf:$repo@$rev"
    [ "$DRY" = 1 ] || ok "Downloaded $repo@$rev ($TOOK)"
  fi
  MATCH_NOTE=$(model_ids note --served "$rev" --qualified "$qualified")
  note_revision

  section "Install"
  run "Installing the unit" install -D -m 644 "$zrt/$UNIT" "$HOME/.config/systemd/user/$UNIT"
  run "Installing the serve script" install -D -m 755 "$zrt/serve-model.sh" "$HOME/.local/share/aware-care-demo/zrt/serve-model.sh"
  install_watchdog
  # model.env (the unit's EnvironmentFile): the revision; #537: ZRT's mode when it is not ZRT's default (so the ZGX
  # scripts run the same command as before), and on another machine the model, its label and ZRT's address.
  local envs=(AWARECARE_MODEL_REVISION="$rev") drop=()
  if [ "${ZRT_MODE:-system}" = system ]; then drop+=(AWARECARE_ZRT_MODE); else envs+=(AWARECARE_ZRT_MODE="$ZRT_MODE"); fi
  [ "$DEVICE" != generic ] || envs+=(AWARECARE_MODEL_URI="$hf" AWARECARE_MODEL_LABEL="$model")
  # #549: the serve script's "already served" check: an address other than ZRT's default; without one the script
  # asks ZRT for its proxy port itself
  if [ "$ZRT_URL" != http://127.0.0.1:8080/v1 ]; then envs+=(AWARECARE_ZRT_URL="$ZRT_URL"); else drop+=(AWARECARE_ZRT_URL); fi
  if [ "$DRY" = 1 ]; then
    cmdline "$(printf '%s ' "${envs[@]}")in $MODEL_ENV (other lines kept)"
  else
    # #609: checked before the unit is touched, so a failed write never restarts it with the old settings
    write_model_env "${envs[@]}" "${drop[@]/#/-}" \
      || fail "Could not write $MODEL_ENV, so the unit would still start with its old settings" \
        "The folder is not writable for $USER, or the disk is full (df -h \"\$HOME\"). Fix that, then rerun:" "\$ ./demo.sh $CMD"
  fi
  if [ "$DEVICE" = generic ]; then
    # the catalogue entry's serving flags, one per line, read by the generic serve script
    local args_file="$HOME/.local/share/aware-care-demo/zrt/serve.args" flags
    flags=$(hardware serve-args --model "$model" --tp "${M_TP:-1}") || fail "No serving settings for $model" "The catalogue has none for this machine; doctor says what it found:" "\$ ./demo.sh doctor"
    if [ "$DRY" = 1 ]; then
      cmdline "serving flags in $args_file: $(paste -sd' ' <<< "$flags")"
    else
      printf '%s\n' "$flags" > "$args_file" || fail "Could not write $args_file" "The folder is not writable, or the disk is full. Fix that, then rerun:" "\$ ./demo.sh $CMD"
    fi
  fi
  run "systemctl daemon-reload" systemctl --user daemon-reload
  [ "$DRY" = 1 ] || ok "Installed $UNIT (revision $rev in $MODEL_ENV)"

  section "Start"
  # #533: the unit is a oneshot, so a blocking start waits for the whole model load (it hung silently for 20+ minutes
  # on a test machine). Start it without blocking and watch it instead. The model is not served here, so a restart stops
  # nothing that answers.
  run "Enabling $UNIT" systemctl --user enable "$UNIT"
  run "Starting $UNIT" systemctl --user restart --no-block "$UNIT"
  start_watchdog
  # #665: short lines: how long it usually takes here, the limits, then the model it starts. #702 (case 8): in a dry
  # run too, so nobody takes a slow first start for a failure.
  info "Model start: $(start_usual) here; a first start in a fresh ZRT takes up to 25 min (it builds the GPU kernels)."
  if [ "$DRY" = 1 ]; then info "Dry run: nothing was downloaded, installed or started."; return 0; fi
  local limit; limit=$(model_timeout)
  if [ -n "$TIMEOUT" ]; then info "It gives up after $(elapsed "$limit") (--timeout)."
  else info "Past $(elapsed "$limit") it waits only while the model still loads, $(elapsed "$MAX_WAIT") at most."; fi
  doing "Starting $model ($repo@$rev) ..."
  wait_for_model || model_failed
  ok "ZRT serves $(served_as "$DEVICE") on $ZRT_URL ($TOOK)"
  note_zrt_url
  [ "$DOC_STRICT" = 1 ] || linger_lines quiet  # setup's checks said it already
}
# #640: the model's watchdog: infra/zrt/model-watchdog.sh (shared) beside the serve script, run every minute by the
# device's aware-care-zrt-watchdog.timer and .service (user units). It restarts the model unit only when the unit is
# enabled and active, ZRT does not list the model, no ZRT service process for it is alive, and it made fewer than 3
# restarts within the hour (then it gives up until the model is served again or `model` clears its state file).
WD_STATE="$HOME/.local/share/aware-care-demo/zrt/watchdog.state"
install_watchdog() {
  local units="$HOME/.config/systemd/user"
  run "Installing the watchdog" install -D -m 755 infra/zrt/model-watchdog.sh "$HOME/.local/share/aware-care-demo/zrt/model-watchdog.sh"
  run "Installing $WD_SERVICE" install -D -m 644 "infra/$DEVICE/zrt/$WD_SERVICE" "$units/$WD_SERVICE"
  run "Installing $WD_TIMER" install -D -m 644 "infra/$DEVICE/zrt/$WD_TIMER" "$units/$WD_TIMER"
}
watchdog_current() {  # installed as this checkout has it, and its timer on
  local units="$HOME/.config/systemd/user"
  cmp -s infra/zrt/model-watchdog.sh "$HOME/.local/share/aware-care-demo/zrt/model-watchdog.sh" \
    && cmp -s "infra/$DEVICE/zrt/$WD_SERVICE" "$units/$WD_SERVICE" && cmp -s "infra/$DEVICE/zrt/$WD_TIMER" "$units/$WD_TIMER" \
    && [ "$(systemctl --user is-enabled "$WD_TIMER" 2>/dev/null)" = enabled ] \
    && [ "$(systemctl --user is-active "$WD_TIMER" 2>/dev/null)" = active ]
}
start_watchdog() {  # a fresh restart count (a person ran model), then the timer
  run "Clearing the watchdog's restart count" rm -f "$WD_STATE"
  run "Enabling $WD_TIMER" systemctl --user enable --now "$WD_TIMER"
  [ "$DRY" = 1 ] || ok "Watchdog on: $WD_TIMER restarts $UNIT when the model dies (journalctl --user -u $WD_SERVICE)"
}
# watchdog_line: one line for status and doctor: on or off, and its last restart (or that it gave up)
watchdog_line() {
  local last="" event="" when="" restarted="no restart yet"
  if [ -e "$WD_STATE" ]; then read -r event last < <(awk '$1 == "restart" { r = $2 } { e = $1 } END { print e, r }' "$WD_STATE"); fi
  [ -z "$last" ] || when=$(date -d "@$last" '+%Y-%m-%d %H:%M' 2>/dev/null)
  [ -z "$when" ] || restarted="last restart $when"
  if [ "$(systemctl --user is-enabled "$WD_TIMER" 2>/dev/null)" != enabled ] \
     || [ "$(systemctl --user is-active "$WD_TIMER" 2>/dev/null)" != active ]; then
    info "Watchdog: off (./demo.sh model turns it on: it restarts the model unit when the model dies)${when:+; last restart $when}"
  elif [ "$event" = gaveup ]; then
    note "Watchdog: on, but it gave up after 3 restarts within an hour (last restart $when)" "./demo.sh model serves the model again"
  else ok "Watchdog: on (restarts the model unit when the model dies; $restarted)"; fi
}
# outside_line (#702, case 5; status, doctor): after zrt_resolve, the model served by this account's ZRT but not
# through demo.sh's unit (started by hand): it has no watchdog and does not come back after a reboot
outside_line() {
  [ -n "${MATCH_ID:-}" ] || return 0
  started_by_hand || return 0
  note "ZRT serves the model, but it was started outside demo.sh: no unit and no watchdog, so it does not come back after a crash or a reboot" \
    "./demo.sh setup adds its unit and watchdog (the model keeps running)"
}
# ------------------------------------------------------------------ doctor, check-model (#537)

machine_lines() {  # the machine in a few lines (status, doctor)
  ok "Machine: ${HW_NAME:-unknown} (${HW_ARCH:-?}; images for ${HW_PLATFORM:-?})"
  if [ "${HW_GPU_COUNT:-0}" = 0 ]; then note "GPU: none found (nvidia-smi lists no NVIDIA GPU)" "no local model here; ./demo.sh mock runs without one"
  else
    local how="the sum over the GPUs"
    [ "$HW_UNIFIED" != 1 ] || how="unified with the system memory"
    [ "$HW_CLASS" != gb300 ] || how="the GPU's HBM"
    ok "GPU: $HW_GPUS; $HW_USABLE_GB GB usable ($how)"
  fi
}

# doctor: read-only checks, one line each (✓ fine, ! a note, ✗ a problem with its fix); it changes nothing and always
# exits 0. The last line is the verdict: ready for ./demo.sh setup (or local), or how many ✗ items to fix first.
# #549: setup runs the same checks strictly (DOC_STRICT=1): the first ✗ stops it with its fix.
DOC_BAD=0
bad() {  # bad <what happened> [why...] [$ <command>...]: fail's ✗ without stopping doctor (in setup it does: fail)
  if [ "$DOC_STRICT" = 1 ]; then fail "$@"; fi
  printf '  %s\342\234\227%s %s%s%s\n' "$RED$B" "$X" "$B" "$1" "$X"; shift
  err_lines "$@"
  DOC_BAD=$((DOC_BAD + 1))
}
free_gb() {  # free_gb <path>: free GB on the file system that holds path (or its nearest existing parent)
  local p=$1
  while [ ! -e "$p" ] && [ "$p" != / ]; do p=$(dirname "$p"); done
  df -BG --output=avail "$p" 2>/dev/null | tail -n1 | tr -dc '0-9'
}
cmd_doctor() {
  header "doctor"
  doctor_checks
  # #694: the same administrator block as setup (its items are already counted above)
  if [ -n "${M_LABEL:-}" ]; then
    local was=$DEVICE; DEVICE=${DEVICE:-$M_PROFILE}
    section "Administrator"
    ADMIN_HOW=admin_show admin_check docker zrt linger
    [ "$ADMIN_NEEDED" = 1 ] || ok "Nothing for an administrator to do"
    DEVICE=$was
  fi
  section "Verdict"
  if [ "$DOC_BAD" = 0 ]; then
    # #660: local only when ZRT serves the model (it stops otherwise)
    case "${DOC_HAVE:-}" in
      served) ok "Ready for ./demo.sh setup (or ./demo.sh local)" ;;
      "") ok "Ready: ./demo.sh setup (downloads and serves the model, then builds and deploys the app)" ;;
      *) ok "Ready for ./demo.sh setup (it serves the downloaded model, then builds and deploys the app)" ;;
    esac
    next_steps "Afterwards, optional: ./demo.sh check-model (advisory; writes a report you can send back)"
  else
    printf '  %s\342\234\227%s %sFix %d item%s first (marked \342\234\227 above); ./demo.sh mock runs without them%s\n' \
      "$RED$B" "$X" "$B" "$DOC_BAD" "$([ "$DOC_BAD" = 1 ] || echo s)" "$X"
  fi
}
# doctor_checks: the sections Machine, Docker and network, ZRT, Model and Ports (doctor; setup, strictly).
doctor_checks() {
  hw_choose
  # #549: whether ZRT serves the model already (then a CUDA toolkit is not needed to serve it)
  # #657: ZRT's own address, also when find_device (setup) already found the model on another one (ZRT_FOUND)
  local dev=${DEVICE:-$M_PROFILE} doc_served=0 doc_away="" url=${ZRT_FOUND:-$ZRT_URL} found="" found_on=""
  ZRT_URL=$url ZRT_FOUND="" ZRT_FOUND_ON=""
  if [ -n "$M_LABEL" ] && [ -n "$dev" ] && zrt_resolve "$dev"; then
    doc_served=1
    # #651: another account's ZRT serves it on another port: nothing for you to serve, linger or watch
    if others_model; then doc_away=$(url_port "$ZRT_URL"); fi
  fi
  # the ZRT section shows ZRT's own address; the Model section finds the model again
  ZRT_URL=$url ZRT_FOUND=$found ZRT_FOUND_ON=$found_on
  section "Machine"
  machine_lines
  [ -z "$HW_PRODUCT" ] || [ "$HW_PRODUCT" = "$HW_NAME" ] || info "DMI product name: $HW_PRODUCT"
  [ -n "$HW_PRODUCT" ] || note "DMI product name not readable; the app will call it \"$HW_NAME\"" "nothing to do"
  [ -z "$HW_MEM_GB" ] || info "System memory: $HW_MEM_GB GB"
  if [ -n "$HW_DRIVER" ]; then info "NVIDIA driver $HW_DRIVER (supports CUDA ${HW_CUDA:-?})"; fi
  if [ -n "$M_PROFILE" ] && DEVICE=${DEVICE:-$M_PROFILE} cuda_line; then :
  elif [ -n "$HW_TOOLKIT" ]; then ok "CUDA toolkit: $HW_TOOLKIT (${HW_TOOLKIT_VERSION:-?}, bin/nvcc)"
  elif [ "$doc_served" = 1 ]; then
    note "CUDA toolkit: none with bin/nvcc under ${AWARECARE_CUDA_ROOT:-/usr/local}" "nothing now: ZRT already serves the model"
  elif [ "${HW_GPU_COUNT:-0}" != 0 ]; then
    bad "CUDA toolkit: none with bin/nvcc under ${AWARECARE_CUDA_ROOT:-/usr/local}" \
      "ZRT needs one to serve a model. An administrator installs the CUDA toolkit (12.8 or later for Blackwell GPUs; 13 on a ZGX)."
  fi

  section "Docker and network"
  local out
  if [ "$DOC_STRICT" = 1 ]; then  # setup: local's checks, whose fixes are complete (the proxy for shell and daemon)
    check_docker; check_network
  elif ! command -v docker >/dev/null; then bad "Docker is not installed" "The app runs in 2 containers. An administrator installs Docker Engine with buildx."
  elif docker_cli_lines all; ! out=$(docker info 2>&1); then
    if grep -qi 'permission denied' <<< "$out"; then
      bad "Docker is not usable without sudo (your user is not in the docker group)" \
        "demo.sh never uses sudo. An administrator adds you to the docker group, once (then log out and back in):" \
        "\$ sudo usermod -aG docker ${USER:-$(id -un)}"
    else bad "Docker does not answer: $(head -n1 <<< "$out")" "Its daemon is not running. Start it (or ask an administrator):" "\$ sudo systemctl start docker"; fi
  else
    DOCKER_INFO=$out
    ok "Docker usable without sudo"
    buildx_line bad
  fi
  if [ "$DOC_STRICT" = 0 ]; then
    local shell_proxy=${HTTPS_PROXY:-${https_proxy:-}} daemon_proxy
    daemon_proxy=$(sed -n 's/^ *HTTPS Proxy: *//p' <<< "${DOCKER_INFO:-}" | head -n1)
    if curl -s --noproxy '*' -m 6 -o /dev/null "$PROBE_URL" 2>/dev/null; then ok "Internet: ghcr.io reachable directly"
    elif [ -z "$shell_proxy" ]; then bad "ghcr.io does not answer and no proxy is set (HTTPS_PROXY)" "The build needs the internet. setup prints the proxy settings for your shell and Docker:" "\$ ./demo.sh setup"
    elif ! curl -s -m 10 -o /dev/null "$PROBE_URL" 2>/dev/null; then bad "ghcr.io does not answer through your proxy $shell_proxy" "The proxy address may be wrong: check it with your IT, then:" "\$ export HTTPS_PROXY=<proxy> https_proxy=<proxy>"
    elif [ -z "$daemon_proxy" ]; then bad "Your shell uses the proxy $shell_proxy, but the Docker daemon has none" "The build could not pull its base images. setup prints the daemon's proxy file:" "\$ ./demo.sh setup"
    else ok "Internet through the proxy $shell_proxy (shell and Docker daemon)"; fi
    if GIT_TERMINAL_PROMPT=0 timeout "${AWARECARE_DEMO_REMOTE_TIMEOUT:-20}" git -C "$ROOT" ls-remote origin HEAD >/dev/null 2>&1; then ok "Repository: origin answers (git ls-remote)"
    else note "Repository: git ls-remote origin failed" "only ./demo.sh update needs it: check your network and where origin points (git remote -v)"; fi
  fi

  section "ZRT"
  local z ver
  if z=$(find_zrt); then
    ver=$(timeout 10 "$z" -m "$ZRT_MODE" version 2>/dev/null | head -n1)
    ok "zrt: $z (${ver:-version unknown}), mode $ZRT_MODE (from $ZRT_MODE_FROM)"
  else bad "zrt: not found" "ZRT serves the model. It is preinstalled on ZGX devices; elsewhere an administrator installs it."; fi
  ok "ZRT address: $ZRT_URL (from $ZRT_URL_FROM)"
  if zrt_explicit && [ -n "$ZRT_CONFIG_PORT" ] && [ "$(url_port "$ZRT_URL")" != "$ZRT_CONFIG_PORT" ]; then
    info "ZRT's proxy is set to port $ZRT_CONFIG_PORT (zrt config get proxy.port); ./demo.sh model serves through that port"
  fi
  local served
  served=$(served_list)
  if [ -n "$served" ]; then ok "ZRT on $ZRT_URL serves: $served"
  elif [ -n "$doc_away" ]; then ok "ZRT on $ZRT_URL serves no model; port $doc_away serves it (see Model, below)"
  elif [ "$DOC_STRICT" = 1 ]; then note "ZRT on $ZRT_URL: no model served (or no answer)" "nothing: setup serves it in the next steps"
  else note "ZRT on $ZRT_URL: no model served (or no answer)" "./demo.sh setup (or model) serves it"; fi
  if [ -n "$M_LABEL" ]; then
    local rows
    rows=$(DEVICE=$M_PROFILE zrt_rows "$M_PROFILE" | awk -F'\t' '{ printf "%s%s (%s, %s)", (NR > 1 ? "; " : ""), $4, $7, $3 }')
    [ -z "$rows" ] || info "zrt services: $rows"
  fi
  check_session bad
  if [ -n "$doc_away" ]; then
    info "Lingering and the model's watchdog: nothing to do here (they matter to the account that serves the model)"
  else
    linger_lines
    watchdog_line
  fi

  section "Model"
  if [ -z "$M_LABEL" ]; then
    bad "No local model: $M_REASON" "Run the demo without a model:" "\$ ./demo.sh setup --mock"
  else
    local was=$DEVICE
    DEVICE=$M_PROFILE
    # shellcheck disable=SC2153  # set by hw_choose (printf -v)
    ok "Model for this machine: $M_LABEL ($M_REPO@${M_REVISION:0:7}, $M_SIZE_GB GB)"
    info "Why: $M_REASON"
    if [ "$M_STATUS" = qualified ]; then ok "Qualified on this hardware (${M_QUALIFIED_ON})"
    else note "Candidate on this hardware: chosen by GPU memory, not qualified here (qualified: ${M_QUALIFIED_ON:-nowhere yet})" \
      "optional: ./demo.sh check-model checks it once it runs (advisory)"; fi
    info "Serving: $M_SETTINGS"
    local have="" need
    if zrt_resolve "$DEVICE"; then ok "ZRT serves it: $(served_as "$DEVICE") on $ZRT_URL"; have=served
      note_zrt_url
      [ "$DOC_STRICT" = 1 ] || outside_line  # #702 (case 5); #704: setup says it at its unit step
    else
      have=$(local_copy "$DEVICE")
      local sys=""
      if [ -n "$have" ]; then ok "Downloaded: revision $have (./demo.sh model serves it, no download)"
      elif sys=$(system_copy "$DEVICE"); then system_copy_fix "$sys" bad
      else info "Not downloaded yet: ./demo.sh setup (or model) downloads $M_SIZE_GB GB"; fi
    fi
    if [ -z "$have" ] && [ -z "${sys:-}" ]; then
      need=$(awk -v s="$M_SIZE_GB" 'BEGIN { printf "%d", s * 1.1 + 1 }')
      local avail store; store=$(zrt_store); avail=$(free_gb "$store")
      if [ -n "$avail" ] && [ "$avail" -lt "$need" ]; then
        bad "Disk: $avail GB free for ZRT's models ($store), the model needs about $need GB" "Free some space, or remove a model you do not need:" "\$ zrt -m $ZRT_MODE remove <model>"
      elif [ -n "$avail" ]; then ok "Disk: $avail GB free for ZRT's models ($store)"; fi
    fi
    DEVICE=$was
  fi
  local droot avail
  droot=$(sed -n 's/^ *Docker Root Dir: *//p' <<< "${DOCKER_INFO:-}" | head -n1)
  avail=$(free_gb "${droot:-/var/lib/docker}")
  if [ -n "$avail" ] && [ "$avail" -lt 10 ]; then bad "Disk: $avail GB free for Docker images (${droot:-/var/lib/docker}); the build needs about 10 GB" "Remove unused images and build cache:" "\$ docker system prune"
  elif [ -n "$avail" ]; then ok "Disk: $avail GB free for Docker images (${droot:-/var/lib/docker})"; fi

  section "Ports"
  local p
  for p in "${AWARECARE_DEMO_API_PORT:-8100}" "${AWARECARE_DEMO_WEB_PORT:-8180}"; do
    if ! port_busy "$p"; then ok "Port $p free"
    elif command -v docker >/dev/null && local_running; then ok "Port $p used by the running demo ($INSTANCE)"
    else bad "Port $p is in use" "Another program holds it (see which: ss -ltnp | grep :$p). Run a second instance on other ports:" \
      "\$ ./demo.sh setup --instance my-demo --api-port 28100 --web-port 28180"; fi
  done

  # #678: this data root's power sampler (setup keeps it running itself, so only doctor shows it here)
  if [ "$DOC_STRICT" = 0 ]; then
    section "Telemetry"
    sampler_line
  fi

  DOC_HAVE=${have:-}
}

# check-model: the AI regression set (scripts/ai_regression/run.sh here) against the model this machine serves,
# through an API started in this process tree in local mode with a throwaway data directory. Advisory: it exits 0
# whatever the cases show, and 1 only when the run itself could not run.
cmd_check_model() {
  start_log check-model
  find_device
  header "check the model (advisory AI regression set)$(on_device)" dry
  section "Checks"
  device_line
  command -v uv >/dev/null || fail "uv is missing" "check-model runs the API with uv. Install it as your user:" \
    "\$ curl -LsSf https://astral.sh/uv/install.sh | sh" "then open a new shell and rerun ./demo.sh check-model."
  ok "Tools: uv $(uv --version 2>/dev/null | awk '{print $2}')"
  section "Model"
  local model; model=$(device_model "$DEVICE")
  if ! zrt_resolve "$DEVICE"; then
    [ "$DRY" = 1 ] || fail "ZRT does not serve $model on $ZRT_URL" "check-model needs the model served (doctor shows what it finds). Serve it first:" "\$ ./demo.sh model"
    MATCH_ID=$model
    note "ZRT does not serve $model on $ZRT_URL yet" "./demo.sh model serves it (this is a dry run)"
  else ok "ZRT serves $(served_as "$DEVICE") on $ZRT_URL"; note_revision; note_zrt_url; fi
  section "Run"
  local stamp out report
  stamp=$(date +%Y%m%d-%H%M%S)-$$
  out="$LOG_DIR/check-model-$stamp"
  report="$LOG_DIR/check-model-$(hostname -s 2>/dev/null || echo host)-$stamp.json"
  local cmd=(env "AI_REGRESSION_OUT=$out" "AI_REGRESSION_MODEL=$MATCH_ID" "AI_REGRESSION_ZRT_URL=$ZRT_URL"
    scripts/ai_regression/run.sh here)
  if [ "$DRY" = 1 ]; then cmdline "$(quote "${cmd[@]}")"; info "Dry run: nothing was run."; return 0; fi
  # #544: one AI job at a time on this machine's model; waits (with a message) while another one runs
  # shellcheck disable=SC1091  # the lock helper; this shell holds the lock until it exits
  . "$ROOT/scripts/dev/with_model_lock.sh"
  model_lock_acquire "./demo.sh check-model" || fail "Another AI job kept the model busy" \
    "The model answers one AI job at a time (lock: ${AWARE_CARE_MODEL_LOCK:-/tmp/aware-care-model.lock}). When it is done:" \
    "\$ ./demo.sh check-model"
  doing "Running about 63 synthetic cases through the app in local mode (a few minutes on a fast GPU, longer on a small one) ..."
  printf '
$ %s
' "$(quote "${cmd[@]}")" >> "$LOG"
  progress "${cmd[@]}"
  local rc=$?
  [ -s "$out/here.json" ] || fail "The check did not run (exit $rc)" "The log below and the run's own log ($out/here.log) say why; fix that, then:" "\$ ./demo.sh check-model"
  ok "Ran in $TOOK"
  echo
  grep -E '^\|' "$LOG" | sed 's/^/    /'
  python3 - "$out/here.json" "$report" "$TOOK" "$MATCH_ID" "$ZRT_URL" "$ZRT_MODE" "$M_STATUS" "$model" <<'PY' >> "$LOG" 2>&1
import json, subprocess, sys
src, dst, took, served, url, mode, status, label = sys.argv[1:9]
machine = subprocess.run([sys.executable, "-I", "apps/api/app/runtime/hardware.py", "detect", "--json"],
                         capture_output=True, text=True).stdout
report = {"kind": "aware-care-check-model", "issue": 537, "took": took,
          "model": {"label": label, "served_id": served, "status_on_this_hardware": status or "qualified"},
          "zrt": {"url": url, "mode": mode}, "machine": json.loads(machine or "{}"), "result": json.load(open(src))}
json.dump(report, open(dst, "w"), indent=2)
PY
  echo
  local gate
  gate=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["summary"]["gate"])' "$out/here.json" 2>/dev/null)
  if [ "$gate" = PASS ]; then ok "Result: PASS (every gated case passed)"
  else note "Result: ${gate:-unknown} (advisory only; the model still runs)" "send the report below to the maintainers"; fi
  ok "Report: $report"
  next_steps "Send that file back (synthetic cases only; it holds no patient data). This check is advisory and never blocks."
}

# ------------------------------------------------------------------ status, stop, uninstall, update

local_running() { docker container inspect -f '{{.State.Running}}' "$INSTANCE-api" 2>/dev/null | grep -q true; }

cmd_status() {
  header "status"
  dirty && { echo; note "The checkout has local changes" "nothing, if you meant it (git -C $ROOT status shows them)"; }
  section "Mock"
  if mock_running; then
    local API_PORT="" WEB_PORT="" BROWSER_PORT=""
    # shellcheck disable=SC1090
    . "$MOCK_STATE"
    local r; r=$(curl -s --noproxy '*' -m 3 "http://127.0.0.1:$WEB_PORT$READY_PATH" | sed -n 's/.*"readiness":"\([a-z]*\)".*/\1/p')
    ok "Mock: API 127.0.0.1:$API_PORT, web 127.0.0.1:$WEB_PORT, readiness ${r:-no answer}; browser port $BROWSER_PORT"
  else
    info "Mock: not running"
  fi
  hw_choose
  section "Machine"
  machine_lines
  section "Model"
  local d served="" devices=(nano fury)
  case "$HW_CLASS" in gb300) devices=(fury) ;; gb10) devices=(nano) ;; esac  # #646: one model on both: the GPU decides
  [ "$M_PROFILE" != generic ] || devices=(generic nano fury)
  for d in "${devices[@]}"; do
    [ -z "$DEVICE" ] || [ "$DEVICE" = "$d" ] || continue
    if zrt_resolve "$d"; then served=$d; DEVICE=$d; ok "ZRT serves $(served_as "$d") on $ZRT_URL"; note_revision; break; fi
  done
  if [ -n "$served" ]; then note_zrt_url
  else note "ZRT: no supported model served on $ZRT_URL (it serves: $(served_list | grep . || echo nothing))" "./demo.sh setup (or model) serves it"; fi
  if [ -n "$served" ] && others_model; then info "Watchdog: nothing to do here (another account's ZRT serves the model)"  # #651
  else outside_line; watchdog_line; fi
  section "Local"
  if ! command -v docker >/dev/null; then info "Local: Docker not installed"; return 0; fi
  if [ -z "$DEVICE" ]; then
    case "$HW_CLASS" in gb300) DEVICE=fury ;; discrete|grace) DEVICE=generic ;; *) DEVICE=nano ;; esac
  fi
  deploy_tool
  local json kind text
  json=$("${DEPLOY[@]}" status 2>/dev/null) || { info "Local: no deployment status (Docker not usable?)"; return 0; }
  # #652: the containers may run someone else's demo, whose record is not in your data root
  local other="" kept=""
  # #670: not when its data root is your own (the account the deploy workflow deploys with): its record is yours
  if running_other && { [ -z "${OTHER_ROOT:-}" ] || [ "$(canon "$OTHER_ROOT")" != "$(canon "$DATA_ROOT")" ]; }; then
    other=$OTHER kept=$OTHER_KEPT
  fi
  while IFS=$'\t' read -r kind text fix; do
    case "$kind" in ok) ok "$text" ;; note) note "$text" ${fix:+"$fix"} ;; *) info "$text" ;; esac
  done < <(python3 - "$json" "$(git -C "$ROOT" rev-parse HEAD 2>/dev/null)" "${served:+$ZRT_URL}" "$other" "$kept" <<'PY'
import json, sys
s, head, zrt, other, kept = json.loads(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]
cur = s.get("current") or {}
cons = s.get("containers") or {}
if not cur and not any(cons.values()):
    print("info\tLocal: not deployed"); sys.exit()
if cur and not any(cons.values()) and not other:
    # #702 (case 1): the record says it runs, but its containers were removed outside demo.sh
    print(f"note\tLocal: {cur.get('release_tag', '?')} is recorded here, but its containers are gone (removed outside "
          "demo.sh?), so nothing answers\tRun ./demo.sh setup to deploy it again (its data is kept)")
    print(f"info\tData: {s.get('data_root')}")
    sys.exit()
state = ", ".join(f"{c['name']} {c['status']}" for c in cons.values() if c) or "no containers"
ready = (s.get("readiness") or {}).get("readiness") or "no answer"
if other:
    print(f"ok\tLocal: {other} runs here, readiness {ready}")
    print(f"info\tContainers: {state}")
    if s.get("model_base_url"):
        print(f"info\tThe app's ZRT address: {s['model_base_url']}")
    print(f"info\t{kept[:1].upper() + kept[1:]}")
    print("info\tYours instead: ./demo.sh setup --replace (its containers go, its data stays)")
    print("info\tOr yours beside it: ./demo.sh setup --instance my-demo --api-port 28100 --web-port 28180")
    sys.exit()
print(f"ok\tLocal: {cur.get('release_tag', '?')} (commit {str(cur.get('app_commit', '?'))[:12]}), mode {cur.get('mode')}, "
      f"model {cur.get('model_id') or '-'}, readiness {ready}")
print(f"info\tContainers: {state}")
if s.get("model_base_url"):
    print(f"info\tThe app's ZRT address: {s['model_base_url']}")
    if cur.get("mode") == "local" and zrt and s["model_base_url"].rstrip("/") != zrt.rstrip("/"):
        print(f"note\tThe app uses ZRT at {s['model_base_url']}, but the model is served on {zrt}: "
              "run ./demo.sh local to bring them together")
print(f"info\tData: {s.get('data_root')}")
if cur.get("app_commit") and head and cur["app_commit"] != head:
    print(f"note\tThe deployment runs commit {cur['app_commit'][:12]}, but this checkout is {head[:12]}: "
          "run ./demo.sh local (or ./demo.sh update) to bring them together")
PY
  )
  local cfg web api
  cfg=$(config_file)
  web=${AWARECARE_DEMO_WEB_PORT:-$(config_value "['network']['web_port']")}
  api=${AWARECARE_DEMO_API_PORT:-$(config_value "['network']['api_port']")}
  info "Ports: API 127.0.0.1:$api, web 127.0.0.1:$web ($(basename "$cfg"))"
  # #678: the power sampler of your own local deployment's data root
  local mode
  mode=$(python3 -c 'import json, sys; print((json.loads(sys.argv[1]).get("current") or {}).get("mode") or "")' "$json" 2>/dev/null)
  if [ -z "$other" ] && [ "$mode" = local ]; then
    sampler_line
  fi
}

stop_local() {
  # #590: each container's removal is checked; only those really removed are reported as stopped, and one that is
  # still there makes stop fail with its name.
  local role found=0 stopped=() failed=() kept="data kept in $DATA_ROOT"
  # #644: whoever's demo it is (no main instance); its data always stays
  if running_other; then kept="$OTHER; $OTHER_KEPT"; fi
  for role in api web; do
    docker container inspect "$INSTANCE-$role" >/dev/null 2>&1 || continue
    found=1
    if [ "$DRY" = 1 ]; then cmdline "docker rm -f $INSTANCE-$role"
    elif docker rm -f "$INSTANCE-$role" >/dev/null; then stopped+=("$INSTANCE-$role")
    else failed+=("$INSTANCE-$role"); fi
  done
  if [ "$found" = 0 ]; then info "No $INSTANCE containers"; return 0; fi
  if [ "$DRY" = 1 ]; then
    [ -z "$OTHER" ] || info "They run $OTHER; $OTHER_KEPT."  # #662: as the real stop says it
    info "Dry run: nothing was stopped."; return 0
  fi
  [ ${#stopped[@]} = 0 ] || ok "Stopped $(and_list "${stopped[@]}") ($kept)"
  [ ${#failed[@]} = 0 ] || fail "Could not stop $(and_list "${failed[@]}"): Docker did not remove it (see its message above)" \
    "Docker's message above says why (docker ps shows it). Fix that, then:" "\$ ./demo.sh stop local"
}
and_list() { if [ $# -le 1 ]; then echo "${1:-}"; else echo "${*:1:$#-1} and ${*: -1}"; fi; }

cmd_stop() {
  header "stop" dry
  section "Stop"
  case "$ARG" in
    mock) if mock_running; then stop_mock; else info "Mock is not running"; fi ;;
    local) stop_local ;;
    "")
      if mock_running; then stop_mock
      elif ! command -v docker >/dev/null; then info "Nothing runs (Docker is not installed)"
      else stop_local; fi ;;
    *) fail "Unknown stop target: $ARG" "stop takes mock, local or nothing (both):" "\$ ./demo.sh stop" ;;
  esac
}

# ------------------------------------------------------------------ uninstall

# uninstall_items walks what there is to remove. item <what> <command...> lists it (PLAN=list; a dry run also prints
# the commands) or removes it (PLAN=run). Every command honours DRY (act, stop_mock, remove_unit, remove_model).
act() { if [ "$DRY" = 1 ]; then cmdline "$(quote "$@")"; else "$@"; fi; }
item() {
  local what=$1 out rc; shift
  ITEMS=$((ITEMS + 1))
  if [ "$PLAN" = list ]; then
    info "- $what"
    if [ "$DRY" = 1 ]; then "$@"; fi
    return 0
  fi
  out=$("$@" 2>&1); rc=$?
  case "$rc" in
    0) ok "Removed $what" ;;
    3) note "$out" ;;  # skipped, with the reason
    *) fail "Could not remove $what: $(tail -n1 <<< "$out")" "Fix that, then rerun:" "\$ ./demo.sh uninstall$([ "$ALL" = 0 ] || echo ' --all')" ;;
  esac
}
remove_watchdog() {  # #640: before the model unit, so it never restarts the unit being removed
  local units="$HOME/.config/systemd/user"
  act systemctl --user disable --now "$WD_TIMER" || true
  act rm -f "$units/$WD_TIMER" "$units/$WD_SERVICE" "$DEFAULT_DATA_ROOT/zrt/model-watchdog.sh" "$DEFAULT_DATA_ROOT/zrt/watchdog.state"
}
remove_unit() {
  act systemctl --user disable --now "$UNIT" || true
  act rm -f "$HOME/.config/systemd/user/$UNIT" "$DEFAULT_DATA_ROOT/zrt/serve.args"
  act systemctl --user daemon-reload || true
}
# remove_model <device> <uri>: zrt remove, only once `zrt services` no longer shows the device's model served (our unit
# is stopped before this); returns 3 (skipped) when something else still serves it.
remove_model() {
  local d=$1 uri=$2 n
  if [ "$DRY" = 1 ]; then
    cmdline "zrt -m ${ZRT_MODE:-system} services   # then, only when it no longer serves the model:"
    cmdline "zrt -m ${ZRT_MODE:-system} remove $uri"; return 0
  fi
  find_zrt >/dev/null || { echo "The zrt command is missing, so $uri stays in ZRT's cache"; return 3; }
  for ((n = 0; n < 6; n++)); do
    zrt_rows "$d" | awk -F'\t' '$1 == 1 { found = 1 } END { exit !found }' || break
    sleep "$POLL"
  done
  if [ "$n" = 6 ]; then
    echo "ZRT still serves $(device_model "$d") (not through this app's unit), so $uri stays. Stop it first (zrt services; zrt service stop <uri>), then rerun"
    return 3
  fi
  zrt_run remove "$uri"
}
# model_copies: "<device> <uri>" of each downloaded copy of a device model in ZRT's cache (the revision model.env names,
# else the one demo.sh would serve). #537: on another machine, model.env names the catalogue model (cmd_uninstall sets
# M_HF and M_LABEL from it).
model_copies() {
  local d rev want uri seen=" " devices=(nano fury)
  want=$(env_value AWARECARE_MODEL_REVISION)
  [ -z "$M_HF" ] || devices=(generic)
  for d in "${devices[@]}"; do
    [ -z "$DEVICE" ] || [ "$DEVICE" = "$d" ] || continue
    rev=$(local_copy "$d" "$want")
    [ -n "$rev" ] || continue
    uri="hf:$(device_repo "$d")@$rev"
    case "$seen" in *" $uri "*) continue ;; esac  # #646: the Nano and the Fury share one model, so one copy
    seen+="$uri "
    echo "$d $uri"
  done
}
# #589: uninstall checks, and removes, each path in its canonical form (realpath -m: no //, /./, /../, trailing slash or
# symlink left), so no other spelling of /, $HOME or the checkout ($HOME//, $HOME/../home, a link to it) gets past.
canon() { [[ $1 == /* ]] && realpath -m -- "$1" 2>/dev/null; }
PROTECTED_WHY="/, \$HOME, the checkout or a folder that holds one of them"
safe_dir() {  # safe_dir <path>: prints its canonical form when demo.sh may delete it: absolute, and not $PROTECTED_WHY
  local c p
  c=$(canon "$1") && [ -n "$c" ] && [ "$c" != / ] || return 1
  for p in "$HOME" "$ROOT"; do
    p=$(canon "$p") && [ -n "$p" ] || return 1
    case "$p/" in "$c"/*) return 1 ;; esac  # $p itself, or a folder above it
  done
  echo "$c"
}
path_item() {  # path_item <path> <what>: removes its canonical form, when that exists and safe_dir allows it
  local c
  if ! c=$(safe_dir "$1"); then
    if [ "$PLAN" = list ] && { [ -e "$1" ] || [ -L "$1" ]; }; then info "Kept: $1 ($2) is $PROTECTED_WHY"; fi
    return 0
  fi
  [ -e "$c" ] || return 0
  # #644: only your own paths: another account's data root (say, AWARECARE_DEMO_DATA_ROOT naming it) is never deleted
  local owner; owner=$(stat -c %U -- "$c" 2>/dev/null) || owner=""
  if [ -n "$owner" ] && [ "$owner" != "$(id -un)" ]; then
    [ "$PLAN" != list ] || info "Kept: $c ($2) belongs to $owner, not to you"
    return 0
  fi
  item "$c ($2)" act rm -rf -- "$c"
}
own_data_root() {  # #557: a data root an Aware Care deployment created (its lock, state or presenter key)
  [ -e "$1/deploy.lock" ] || [ -d "$1/state" ] || [ -e "$1/secrets/presenter.key" ]
}
uninstall_items() {
  local role ref d names=() refs=() unit_file="$HOME/.config/systemd/user/$UNIT" serve="$DEFAULT_DATA_ROOT/zrt" line
  # #678: this data root's power sampler: its crontab line goes first (cron then never runs a removed script), and the
  # running sampler stops
  if crontab -l 2>/dev/null | grep -v '^[[:space:]]*#' | grep -qF " $DATA_ROOT/telemetry/power_sampler.py "; then
    item "the GPU power sampler's crontab line (the sampler stops)" act python3 infra/deploy/nano_deploy.py \
      --data-root "$DATA_ROOT" power-sampler --remove
  fi
  # #564: mock mode belongs to the default instance; uninstalling a second instance leaves it alone
  if [ "$DATA_ROOT" = "$DEFAULT_DATA_ROOT" ] && mock_running; then item "the mock development servers" stop_mock quiet; fi
  if command -v docker >/dev/null; then
    for role in api web; do
      if docker container inspect "$INSTANCE-$role" >/dev/null 2>&1; then names+=("$INSTANCE-$role"); fi
    done
    [ ${#names[@]} = 0 ] || item "the containers ${names[*]}${OTHER:+ ($OTHER; $OTHER_KEPT)}" act docker rm -f "${names[@]}"
    # #702 (case 1): someone else's demo that answers: removing it takes it away from everyone who uses it
    if [ ${#names[@]} -gt 0 ] && [ -n "${OTHER:-}" ] && [ "$PLAN" = list ]; then
      local web; running_ports; web=$RUN_WEB
      if [ "$(readiness_of "$web")" = ready ]; then
        note "This stops the demo that runs here and answers ready now ($OTHER): everyone who uses it loses it" \
          "to use it rather than remove it, answer N and open it: ./demo.sh open"
      fi
    fi
    refs=("$INSTANCE-api:local" "$INSTANCE-web:local")
    [ "$ALL" = 0 ] || refs+=(aware-care-api:local aware-care-web:local)
    for ref in "${refs[@]}"; do
      if docker image inspect "$ref" >/dev/null 2>&1; then item "the image $ref" act docker image rm "$ref"; fi
    done
  fi
  if { [ "$ALL" = 1 ] || [ "$DATA_ROOT" = "$DEFAULT_DATA_ROOT" ]; } && [ -e "$HOME/.config/systemd/user/$WD_TIMER" ]; then
    item "the model watchdog $WD_TIMER and $WD_SERVICE" remove_watchdog
  fi
  if { [ "$ALL" = 1 ] || [ "$DATA_ROOT" = "$DEFAULT_DATA_ROOT" ]; } && [ -e "$unit_file" ]; then
    item "the model unit $UNIT (stops the model it serves)" remove_unit
  fi
  if [ "$ALL" = 1 ] && [ "$WITH_MODEL" = 1 ]; then
    while read -r d line; do
      [ -z "$line" ] || item "the downloaded model $line (ZRT's cache)" remove_model "$d" "$line"
    done <<< "$COPIES"
  fi
  if [ "$DATA_ROOT" = "$DEFAULT_DATA_ROOT" ]; then
    path_item "$ROOT/runtime-data/api" "mock mode's data"
    path_item "$ROOT/runtime-data/presenter-dev.key" "mock mode's presenter key"
    path_item "$DATA_ROOT" "the app's data, presenter key, backups and the model's serve script"
  elif own_data_root "$DATA_ROOT"; then path_item "$DATA_ROOT" "the app's data, presenter key and backups"
  elif [ -e "$DATA_ROOT" ] && [ "$PLAN" = list ]; then
    # #557: --instance zrt (uv, keyrings, ...) names another program's folder: never deleted
    info "Kept: $DATA_ROOT is not an Aware Care deployment's data (no deploy.lock, state or presenter key)"
  fi
  if [ "$ALL" = 1 ]; then
    [ "$DATA_ROOT" = "$DEFAULT_DATA_ROOT" ] || path_item "$serve" "the model's serve script"
    path_item "$(dirname "$MODEL_ENV")" "the model's settings"
    path_item "$LOG_DIR" "demo.sh's logs, the mock servers' logs, check-model reports and build metadata"
  fi
}

cmd_uninstall() {
  header "uninstall$([ "$ALL" = 0 ] || echo ' --all')" dry
  local root
  root=$(safe_dir "$DATA_ROOT") || fail "Refusing to delete the data root $DATA_ROOT: it is $PROTECTED_WHY" \
    "AWARECARE_DEMO_DATA_ROOT names it. Point it at the app's own folder, or leave it out:" "\$ unset AWARECARE_DEMO_DATA_ROOT"
  # #589: from here on every comparison and the ownership check (own_data_root) see the canonical paths
  DATA_ROOT=$root
  DEFAULT_DATA_ROOT=$(canon "$DEFAULT_DATA_ROOT")
  # #644: no main instance: uninstall never refuses because of whose containers run (they are removed, their data
  # stays: only paths of your own data root are ever deleted, path_item)
  OTHER="" OTHER_KEPT=""
  if command -v docker >/dev/null; then running_other || true; fi
  # #667: the running demo's data root is your own (the account the deploy workflow deploys with): uninstall deletes it
  if [ -n "$OTHER" ] && [ -n "${OTHER_ROOT:-}" ] && [ "$(canon "$OTHER_ROOT")" = "$DATA_ROOT" ]; then
    OTHER_KEPT="its data is your own data root, which uninstall removes below"
  fi
  COPIES=""
  if [ "$WITH_MODEL" = 1 ]; then
    M_HF=$(env_value AWARECARE_MODEL_URI) M_LABEL=$(env_value AWARECARE_MODEL_LABEL)
    [ "$DEVICE" != generic ] || [ -n "$M_HF" ] || DEVICE=""
    COPIES=$(model_copies)
  fi
  section "What it removes"
  ITEMS=0 PLAN=list
  uninstall_items
  if [ "$ITEMS" = 0 ]; then info "Nothing: demo.sh has nothing installed here."
  elif [ "$DRY" = 1 ]; then info "Dry run: nothing was removed."
  else
    if [ "$YES" = 0 ]; then
      local answer=""
      read -r -p "  Remove these? [y/N] " answer || true
      case "$answer" in y|Y|yes|YES) ;; *) info "Nothing changed."; return 0 ;; esac
    fi
    section "Remove"
    PLAN=run
    uninstall_items
  fi
  if [ "$ALL" = 0 ]; then
    # #655: the same instance: without --instance, --all would remove the default instance's containers
    # #658: only what --all adds (the default instance's data root holds the model's serve script)
    if [ "$INSTANCE" = "$DEFAULT_INSTANCE" ]; then next_steps "Also the model's settings and demo.sh's logs: ./demo.sh uninstall --all"
    else next_steps "Also the model unit, its settings and demo.sh's logs: ./demo.sh uninstall --all --instance $INSTANCE"; fi
    return 0
  fi
  section "What stays"
  local kept="" images  # #636: only what exists (a fresh clone has neither)
  [ ! -d "$ROOT/apps/api/.venv" ] || kept="apps/api/.venv"
  [ ! -d "$ROOT/apps/web/node_modules" ] || kept+="${kept:+ and }apps/web/node_modules"
  info "This checkout, $ROOT${kept:+ (with $kept)}. Delete it:"
  cmdline "cd ~ && rm -rf $(quote "$ROOT")"
  info "Docker and its build cache (docker builder prune, if nothing else on this machine needs it), and ZRT"
  # #636: the release images a deploy workflow pulled (only on the maintainer's devices)
  images=$(docker images -q "ghcr.io/your-github-user/aware-care/*" 2>/dev/null | sort -u | paste -sd' ' -)
  if [ -n "$images" ]; then  # #668: a command that selects them, not every ID on one line
    info "The release images the deploy workflow pulled ($(wc -w <<< "$images")). Remove them:"
    cmdline "docker image rm \$(docker images -q 'ghcr.io/your-github-user/aware-care/*')"
  fi
  if [ "$WITH_MODEL" = 0 ]; then
    info "The downloaded model in ZRT's cache (remove it too: ./demo.sh uninstall --all --with-model)"
  fi
  info "uv and Node, if you installed them for mock mode"
}

# open (#695, owner decision T2): the tunnel command and the exact address of the demo that runs here, for this login
# and this machine, at any time: this checkout's mock mode, else this instance's containers (anyone's), else whatever
# answers on this instance's web port (without Docker access). Reads only; changes nothing.
cmd_open() {
  header "open"
  section "Demo"
  if [ "$INSTANCE" = "$DEFAULT_INSTANCE" ] && mock_running; then
    local API_PORT="" WEB_PORT="" BROWSER_PORT=""
    # shellcheck disable=SC1090
    . "$MOCK_STATE"
    ok "Mock mode runs here (API 127.0.0.1:$API_PORT, web 127.0.0.1:$WEB_PORT; no model, scripted results)"
    ready_line "$WEB_PORT"
    open_it "$BROWSER_PORT" "$WEB_PORT"
    return 0
  fi
  local whose=""
  if docker info >/dev/null 2>&1 && docker container inspect "$INSTANCE-web" >/dev/null 2>&1; then
    running_ports
    if running_other; then whose="${OTHER^} ($INSTANCE-api, $INSTANCE-web)"
    else whose="Your own ./demo.sh instance ($INSTANCE-api, $INSTANCE-web)"; fi
  else
    RUN_WEB=${AWARECARE_DEMO_WEB_PORT:-$(config_value "['network']['web_port']")}
    RUN_BROWSER=$(url_port "$(config_value "['network']['browser_origin']")")
    [ -n "$(readiness_of "$RUN_WEB")" ] || fail "Nothing answers on 127.0.0.1:$RUN_WEB: the demo does not run here" \
      "Set it up (a rerun skips what is done):" "\$ ./demo.sh setup$(instance_args)"
    whose="A demo answers on 127.0.0.1:$RUN_WEB"
    docker info >/dev/null 2>&1 || whose+=" (Docker is not usable for you, so demo.sh cannot tell whose it is)"
  fi
  ok "The demo runs here: $whose"
  ready_line "$RUN_WEB"
  open_it "$RUN_BROWSER" "$RUN_WEB"
}

# fresh (#698, owner decision T5): start from scratch safely. 1. back up this instance's data with the README's tar
# command (~/aware-care-data-<date>.tar.gz; a time is added when that file exists); 2. ./demo.sh uninstall --all
# (never --with-model: the downloaded model stays); 3. ./demo.sh setup. Asks first (--yes answers). A failed backup
# stops it before anything is removed. It says where the backup is, and how to bring it back.
cmd_fresh() {
  header "fresh: back up, uninstall --all, set up again" dry
  local parent base backup name pass=()
  parent=$(dirname "$DATA_ROOT"); base=$(basename "$DATA_ROOT")
  name=${base/#aware-care-demo/aware-care}
  backup="$HOME/$name-data-$(date +%Y%m%d).tar.gz"
  [ ! -e "$backup" ] || backup="$HOME/$name-data-$(date +%Y%m%d-%H%M%S).tar.gz"
  [ "$INSTANCE" = "$DEFAULT_INSTANCE" ] || pass+=(--instance "$INSTANCE")
  [ -z "${AWARECARE_DEMO_API_PORT:-}" ] || pass+=(--api-port "$AWARECARE_DEMO_API_PORT")
  [ -z "${AWARECARE_DEMO_WEB_PORT:-}" ] || pass+=(--web-port "$AWARECARE_DEMO_WEB_PORT")
  [ "$NO_COLOR_OPT" = 0 ] || pass+=(--no-color)
  [ "$DRY" = 0 ] || pass+=(--dry-run)
  local setup_args=("${pass[@]}")
  [ -z "$PORT" ] || setup_args+=(--port "$PORT")
  [ -z "$DEVICE" ] || setup_args+=(--device "$DEVICE")
  [ -z "$MODEL_OPT" ] || setup_args+=(--model "$MODEL_OPT")
  [ -z "$ZRT_MODE_OPT" ] || setup_args+=(--zrt-mode "$ZRT_MODE_OPT")
  [ -z "$ZRT_URL_OPT" ] || setup_args+=(--zrt-url "$ZRT_URL_OPT")
  [ -z "$ZRT_PORT_OPT" ] || setup_args+=(--zrt-port "$ZRT_PORT_OPT")

  section "Plan"
  info "1. Back up $DATA_ROOT to $backup"
  info "2. ./demo.sh uninstall --all$(instance_args): the app, its data, the model unit and settings, demo.sh's logs;"
  info "   the downloaded model stays (fresh never removes it)"
  info "3. ./demo.sh setup$(instance_args): everything again, as after a clone"
  if [ "$DRY" = 0 ] && [ "$YES" = 0 ]; then
    local answer=""
    if [ -t 0 ]; then read -r -p "  Go on? [y/N] " answer || true; fi
    case "$answer" in y|Y|yes|YES) ;; *) info "Nothing changed (--yes answers the question)."; return 0 ;; esac
  fi

  section "1. Back up"
  if [ ! -e "$DATA_ROOT" ]; then
    info "Nothing to back up: $DATA_ROOT does not exist."
    backup=""
  elif [ "$DRY" = 1 ]; then
    cmdline "tar -czf $backup -C $parent $base"
  else
    local out
    if ! out=$(tar -czf "$backup" -C "$parent" "$base" 2>&1) || ! tar -tzf "$backup" >/dev/null 2>&1; then
      rm -f -- "$backup"
      fail "The backup of $DATA_ROOT failed, so nothing was removed" "${out:-tar could not write or read $backup}" \
        "Free some space in your home (df -h ~) or fix the message above, then rerun:" "\$ ./demo.sh fresh$(instance_args)"
    fi
    ok "Backed up $DATA_ROOT to $backup ($(du -h -- "$backup" | cut -f1))"
  fi

  section "2. Uninstall --all"
  echo
  "$ROOT/demo.sh" uninstall --all --yes "${pass[@]}" || fail "uninstall --all failed (see above); nothing was set up" \
    "Fix what it says, then rerun:" "\$ ./demo.sh fresh$(instance_args)"

  section "3. Setup"
  echo
  local rc=0
  "$ROOT/demo.sh" setup "${setup_args[@]}" || rc=$?
  section "Backup"
  if [ -n "$backup" ]; then
    if [ "$DRY" = 1 ]; then info "The backup would be $backup."
    else ok "Your earlier data is in $backup"; fi
    next_steps "To bring it back: ./demo.sh stop$(instance_args), then tar -xzf $backup -C $parent, then ./demo.sh setup$(instance_args)"
  else
    info "No backup: there was no data."
  fi
  return "$rc"
}

cmd_update() {
  header "update" dry
  section "Update"
  if dirty; then
    # #702 (case 7): one command keeps them (a branch of their own), so update can switch
    fail "The checkout has local changes, so it cannot switch versions" \
      "update checks out another version, which would lose them (git -C $ROOT status shows them). Keep them on a branch:" \
      "\$ git -C $ROOT switch -c my-changes && git -C $ROOT commit -qam 'My changes'" "Then rerun ./demo.sh update."
  fi
  local mode=""
  if mock_running; then mode=mock
  elif command -v docker >/dev/null && local_running && ! running_other; then mode=local; fi
  if [ "$DRY" = 1 ]; then
    cmdline "git -C $ROOT fetch --tags --quiet origin"
  else
    git -C "$ROOT" fetch --tags --quiet origin || fail "git fetch failed" \
      "The network (or its proxy: ./demo.sh doctor checks it) failed, or origin is not a repository you can read." \
      "Check where origin points:" "\$ git -C $ROOT remote -v" "Then rerun ./demo.sh update."
  fi
  local target=${ARG:-} have
  [ -n "$target" ] || target=$(git -C "$ROOT" tag -l 'v*' --sort=-v:refname | head -n1)
  [ -n "$target" ] || fail "No release tag (v*) found" "The fetch brought none from origin. Name one:" "\$ ./demo.sh update <tag>"
  # #702 (case 7): without a tag named, never an older release than this checkout's. Any origin is accepted (a fork or
  # a copy of this repository has the releases it publishes as v* tags).
  have=$(git -C "$ROOT" describe --tags --abbrev=0 --match 'v*' HEAD 2>/dev/null)
  if [ -z "$ARG" ] && [ -n "$have" ] && [ "$(printf '%s\n%s\n' "$have" "$target" | sort -V | tail -n1)" = "$have" ]; then
    if [ "$have" = "$target" ] && [ "$(git -C "$ROOT" rev-parse "$have^{commit}" 2>/dev/null)" = "$(git -C "$ROOT" rev-parse HEAD)" ]; then
      ok "Already on the newest release origin has: $target"
    else
      ok "This checkout is at or past $have; origin's newest release is $target, so update changes nothing"
    fi
    return 0
  fi
  local want
  if ! want=$(git -C "$ROOT" rev-parse -q --verify "refs/tags/$target^{commit}" 2>/dev/null); then
    [ "$DRY" = 0 ] || { info "Dry run: $target is not fetched yet; the fetch above would bring it if it exists."; return 0; }
    fail "No tag named $target" "It is not a release tag. List them:" "\$ git -C $ROOT tag -l 'v*' --sort=-v:refname"
  fi
  # A release older than demo.sh (before v0.16.1-demo.1) has no demo.sh: refuse it before the checkout, or the next
  # ./demo.sh would be "No such file or directory".
  git -C "$ROOT" cat-file -e "$want:demo.sh" 2>/dev/null || fail "$target is older than demo.sh (it has no demo.sh), so demo.sh does not switch to it" \
    "The next ./demo.sh would not exist. Choose a newer release (an older one: follow its README by hand):" \
    "\$ git -C $ROOT tag -l 'v*' --sort=-v:refname"
  local again=("./demo.sh" "$mode")
  [ -z "$PORT" ] || again+=(--port "$PORT")
  [ -z "$DEVICE" ] || again+=(--device "$DEVICE")
  [ "$INSTANCE" = "$DEFAULT_INSTANCE" ] || again+=(--instance "$INSTANCE")
  [ -z "${AWARECARE_DEMO_API_PORT:-}" ] || again+=(--api-port "$AWARECARE_DEMO_API_PORT")
  [ -z "${AWARECARE_DEMO_WEB_PORT:-}" ] || again+=(--web-port "$AWARECARE_DEMO_WEB_PORT")
  [ -z "$ZRT_URL_OPT" ] || again+=(--zrt-url "$ZRT_URL_OPT")
  [ -z "$ZRT_PORT_OPT" ] || again+=(--zrt-port "$ZRT_PORT_OPT")
  [ -z "$MODEL_OPT" ] || again+=(--model "$MODEL_OPT")  # #565
  [ -z "$ZRT_MODE_OPT" ] || again+=(--zrt-mode "$ZRT_MODE_OPT")
  [ "$NO_COLOR_OPT" = 0 ] || again+=(--no-color)
  if [ "$DRY" = 1 ]; then
    cmdline "git -C $ROOT checkout $target   # commit ${want:0:12}"
    if [ -n "$mode" ]; then cmdline "$(quote "${again[@]}")   # restarts $mode on $target"
    else info "Nothing was started by demo.sh, so nothing would restart."; fi
    info "Dry run: nothing was fetched, checked out or restarted."
    return 0
  fi
  git -C "$ROOT" -c advice.detachedHead=false checkout --quiet "$want" \
    || fail "git checkout of $target failed" "git's message above says why; status shows more:" "\$ git -C $ROOT status"
  [ "$(git -C "$ROOT" rev-parse HEAD)" = "$want" ] || fail "The checkout is not at $target after git checkout" \
    "Something changed the checkout meanwhile; status and git log -1 show where it is:" "\$ git -C $ROOT status"
  ok "Checked out $target (commit ${want:0:12})"
  if [ -z "$mode" ]; then info "Nothing was started by demo.sh. Start it: ./demo.sh mock  or  ./demo.sh local"; return 0; fi
  again[0]="$ROOT/demo.sh"
  doing "Restarting $mode on $target ..."
  echo
  exec "${again[@]}"
}

# ------------------------------------------------------------------ main

# #558: an option's value is the next word unless that word is another option (`--revision --dry-run` is a missing
# revision, never a revision named --dry-run that drops the dry run)
has_value() { [ "$1" -ge 2 ] && case "$2" in -*) return 1 ;; esac; }
while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) HELP=1 ;;
    --port) has_value $# "${2:-}" || { echo "demo.sh: --port needs a number" >&2; exit 2; }; PORT=$2; shift ;;
    --port=*) PORT=${1#--port=} ;;
    --device) has_value $# "${2:-}" || { echo "demo.sh: --device needs nano or fury" >&2; exit 2; }; DEVICE=$2; shift ;;
    --device=*) DEVICE=${1#--device=} ;;
    --model) has_value $# "${2:-}" || { echo "demo.sh: --model needs a catalogue label (see ./demo.sh doctor)" >&2; exit 2; }
      MODEL_OPT=$2; shift ;;
    --model=*) MODEL_OPT=${1#--model=} ;;
    --zrt-mode) has_value $# "${2:-}" || { echo "demo.sh: --zrt-mode needs user or system" >&2; exit 2; }; ZRT_MODE_OPT=$2; shift ;;
    --zrt-mode=*) ZRT_MODE_OPT=${1#--zrt-mode=} ;;
    --zrt-url) has_value $# "${2:-}" || { echo "demo.sh: --zrt-url needs a URL, e.g. http://127.0.0.1:9093/v1" >&2; exit 2; }
      ZRT_URL_OPT=$2; shift ;;
    --zrt-url=*) ZRT_URL_OPT=${1#--zrt-url=} ;;
    --zrt-port) has_value $# "${2:-}" || { echo "demo.sh: --zrt-port needs a port number, e.g. 9093" >&2; exit 2; }
      ZRT_PORT_OPT=$2; shift ;;
    --zrt-port=*) ZRT_PORT_OPT=${1#--zrt-port=} ;;
    --revision) has_value $# "${2:-}" || { echo "demo.sh: --revision needs a revision" >&2; exit 2; }; REVISION=$2; shift ;;
    --revision=*) REVISION=${1#--revision=} ;;
    --timeout) has_value $# "${2:-}" || { echo "demo.sh: --timeout needs a time, e.g. 20m" >&2; exit 2; }; TIMEOUT=$2; shift ;;
    --timeout=*) TIMEOUT=${1#--timeout=} ;;
    --instance) has_value $# "${2:-}" || { echo "demo.sh: --instance needs a name, e.g. my-demo" >&2; exit 2; }; INSTANCE=$2; shift ;;
    --instance=*) INSTANCE=${1#--instance=} ;;
    --api-port) has_value $# "${2:-}" || { echo "demo.sh: --api-port needs a number" >&2; exit 2; }; AWARECARE_DEMO_API_PORT=$2; shift ;;
    --api-port=*) AWARECARE_DEMO_API_PORT=${1#--api-port=} ;;
    --web-port) has_value $# "${2:-}" || { echo "demo.sh: --web-port needs a number" >&2; exit 2; }; AWARECARE_DEMO_WEB_PORT=$2; shift ;;
    --web-port=*) AWARECARE_DEMO_WEB_PORT=${1#--web-port=} ;;
    --all) ALL=1 ;;
    --with-model) WITH_MODEL=1 ;;
    --mock) MOCK_OPT=1 ;;
    --rebuild) REBUILD=1 ;;
    --replace) REPLACE=1 ;;
    --dry-run) DRY=1 ;;
    --yes|-y) YES=1 ;;
    --no-color) NO_COLOR_OPT=1 ;;
    -*) echo "demo.sh: unknown option $1 (see ./demo.sh --help)" >&2; exit 2 ;;
    *) if [ -z "$CMD" ]; then CMD=$1; elif [ -z "$ARG" ]; then ARG=$1; else echo "demo.sh: unexpected $1" >&2; exit 2; fi ;;
  esac
  shift
done
setup_style
if [ "$HELP" = 1 ]; then help; exit 0; fi
port_ok() { case "$1" in ''|*[!0-9]*|0*) return 1 ;; esac; [ "${#1}" -le 5 ] && [ "$1" -le 65535 ]; }
for opt in "--port=$PORT" "--api-port=${AWARECARE_DEMO_API_PORT:-}" "--web-port=${AWARECARE_DEMO_WEB_PORT:-}" \
           "--zrt-port=$ZRT_PORT_OPT"; do
  [ -z "${opt#*=}" ] || port_ok "${opt#*=}" || { echo "demo.sh: ${opt%%=*} must be a port number (1 to 65535)" >&2; exit 2; }
done
if ! [[ $INSTANCE =~ ^[a-z0-9][a-z0-9_.-]*$ ]]; then
  echo "demo.sh: --instance must be lower-case letters, digits, '.', '_' or '-' (e.g. my-demo)" >&2; exit 2
fi
DATA_ROOT=${AWARECARE_DEMO_DATA_ROOT:-$HOME/.local/share/$INSTANCE}
if [ -n "$ZRT_URL_OPT" ] && [ -n "$ZRT_PORT_OPT" ]; then
  echo "demo.sh: give --zrt-url or --zrt-port, not both" >&2; exit 2
fi
# #549: ./demo.sh alone runs setup: on a terminal after one question (it may download a model and build images),
# without one (a script) it prints the help as before; with --dry-run it runs at once (nothing changes)
if [ -z "$CMD" ]; then
  if [ "$DRY" = 1 ] || [ "$MOCK_OPT" = 1 ] || [ "$REBUILD" = 1 ]; then CMD=setup
  elif [ -t 0 ] && [ -t 1 ]; then
    printf '%sAware Care%s: set up this machine now (./demo.sh setup: checks, the model, build, deploy)? [Y/n] ' "$B" "$X"
    answer=""; read -r answer || true
    case "$answer" in ""|y|Y|yes|YES) CMD=setup ;; *) help; exit 0 ;; esac
  fi
fi
if { [ "$MOCK_OPT" = 1 ] || [ "$REBUILD" = 1 ]; } && [ "$CMD" != setup ]; then
  echo "demo.sh: --mock and --rebuild go with setup (./demo.sh setup --mock)" >&2; exit 2
fi
if [ "$MOCK_OPT" = 1 ] && [ "$REBUILD" = 1 ]; then echo "demo.sh: --rebuild goes with setup, not setup --mock" >&2; exit 2; fi
if [ "$REPLACE" = 1 ]; then
  case "$CMD" in setup|local) ;; *) echo "demo.sh: --replace goes with setup or local" >&2; exit 2 ;; esac
  [ "$MOCK_OPT" = 0 ] || { echo "demo.sh: --replace goes with setup or local, not setup --mock" >&2; exit 2; }
fi
if [ "$CMD" = fresh ] && { [ "$ALL" = 1 ] || [ "$WITH_MODEL" = 1 ]; }; then
  # #698: fresh always runs uninstall --all, and never removes the downloaded model
  echo "demo.sh: fresh runs uninstall --all itself and never removes the model (--with-model goes with uninstall --all)" >&2; exit 2
fi
if [ "$ALL" = 1 ] || [ "$WITH_MODEL" = 1 ]; then
  [ "$CMD" = uninstall ] || { echo "demo.sh: --all and --with-model go with uninstall" >&2; exit 2; }
  [ "$ALL" = 1 ] || { echo "demo.sh: --with-model goes with uninstall --all" >&2; exit 2; }
fi
case "$DEVICE" in ''|nano|fury) ;; auto) DEVICE="" ;; *) echo "demo.sh: --device must be nano, fury or auto" >&2; exit 2 ;; esac
case "$ZRT_MODE_OPT" in ''|user|system) ;; *) echo "demo.sh: --zrt-mode must be user or system" >&2; exit 2 ;; esac
case "${AWARECARE_ZRT_MODE:-}" in ''|user|system) ;; *) echo "demo.sh: AWARECARE_ZRT_MODE must be user or system" >&2; exit 2 ;; esac
case "$MODEL_OPT" in *[!A-Za-z0-9._/@:-]*) echo "demo.sh: --model must be a catalogue label, e.g. qwen3-14b-fp8" >&2; exit 2 ;; esac
case "$TIMEOUT" in
  '') ;;
  *[!0-9sm]*|s|m|*[sm]?*|*[0-9][0-9][0-9][0-9][0-9][0-9][0-9]*)
    echo "demo.sh: --timeout must be seconds or minutes, e.g. 900 or 15m" >&2; exit 2 ;;
  # #559: base 10 (08m is eight minutes, not an octal error), and more than nothing
  *m) TIMEOUT=$((10#${TIMEOUT%m} * 60)) ;;
  *s) TIMEOUT=$((10#${TIMEOUT%s})) ;;
  *) TIMEOUT=$((10#$TIMEOUT)) ;;
esac
if [ -n "$TIMEOUT" ] && [ "$TIMEOUT" -le 0 ]; then
  echo "demo.sh: --timeout must be seconds or minutes, e.g. 900 or 15m" >&2; exit 2
fi
# The same loopback rule as the deploy tool and the API (ADR-014): ZRT on this device, never another host.
for url in "$ZRT_URL_OPT" "$ZRT_URL_ENV"; do
  case "${url%/}" in
    ''|http://127.0.0.1:[0-9]*|http://localhost:[0-9]*|http://\[::1\]:[0-9]*) ZRT_BAD=0 ;;
    *) ZRT_BAD=1 ;;
  esac
  case "$url" in *@*|*\?*|*#*) ZRT_BAD=1 ;; esac
  if [ "$ZRT_BAD" = 1 ]; then
    echo "demo.sh: --zrt-url (or AWARECARE_ZRT_URL) must be ZRT on this device, e.g. http://127.0.0.1:8080/v1" >&2; exit 2
  fi
done
case "$REVISION" in *[!A-Za-z0-9._-]*) echo "demo.sh: --revision must be a branch, tag or commit (e.g. main)" >&2; exit 2 ;; esac

# demo.sh never uses sudo, and does not run as root: the containers, the data, the model unit (a user unit) and the
# checkout belong to the user who runs the demo (docs/wiki/Requirements.md).
if [ -n "$CMD" ] && [ "$(id -u)" = 0 ]; then
  fail "demo.sh runs as your own user, not with sudo or as root" \
    "The containers, data and model unit belong to the user who runs the demo. Run it as yourself:" "\$ ./demo.sh ${CMD}" \
    "Docker without sudo needs, once, an administrator: sudo usermod -aG docker <user> (docs/wiki/Requirements.md)."
fi

case "$CMD" in
  setup) [ "$MOCK_OPT" = 1 ] || { zrt_mode; zrt_address; } ;;  # setup --mock needs no ZRT
  local|model|status|doctor|check-model|uninstall) zrt_mode; zrt_address ;;
esac
case "$CMD" in
  setup) cmd_setup ;;
  mock) cmd_mock ;;
  local) cmd_local ;;
  model) cmd_model ;;
  doctor) cmd_doctor ;;
  check-model) cmd_check_model ;;
  status) cmd_status ;;
  stop) cmd_stop ;;
  uninstall) cmd_uninstall ;;
  update) cmd_update ;;
  open) cmd_open ;;
  fresh) cmd_fresh ;;
  "") help; exit 2 ;;
  *) echo "demo.sh: unknown command $CMD (see ./demo.sh --help)" >&2; exit 2 ;;
esac
