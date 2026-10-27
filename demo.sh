#!/usr/bin/env bash
# demo.sh: run the Aware Care demo with one command (#525) on an HP ZGX Nano, a ZGX Fury or, #537, any NVIDIA Linux
# machine (the model is chosen from infra/models/catalog.json by the GPU memory found here).
#
#   ./demo.sh setup             #549: everything after the clone, in order, each step skipped when it is done: the doctor
#                               checks, the model (served through ZRT), the build and deploy, the tunnel and the URL;
#                               --mock: mock mode instead. `./demo.sh` alone asks once on a terminal, then runs setup
#   ./demo.sh mock              try it: no model, no Docker (development servers, scripted synthetic results)
#   ./demo.sh local             real on-device AI: checks, builds the images, deploys the two containers
#   ./demo.sh model             serve this machine's model with ZRT: a copy ZRT already has (any revision), else
#                               it downloads the pinned revision (once; 10 to 190 GB); #640: with the unit, its
#                               watchdog (a timer that restarts the unit when the model died)
#   ./demo.sh doctor            what this machine has (GPUs, memory, CUDA, ZRT) and which model it will use
#   ./demo.sh check-model       the advisory AI regression set against the model this machine serves
#   ./demo.sh status            what runs, which commit or tag, which model ZRT serves
#   ./demo.sh update [<tag>]    check out a release tag (default: the latest v*), then rerun mock or local
#   ./demo.sh stop [mock|local] stop the app (data kept)
#   ./demo.sh uninstall         stop and remove the app, its data, images, the model unit and its watchdog (asks first)
#   ./demo.sh uninstall --all   everything demo.sh added on this machine, to start from scratch (--with-model: the
#                               downloaded model too); Docker, ZRT and the checkout stay
#
# Options: --port <n>, --device nano|fury|auto, --model <label>, --zrt-url <url>, --zrt-port <n>,
# --zrt-mode user|system, --revision <rev>, --timeout <time>, --instance <name>, --api-port <n>, --web-port <n>, --all,
# --with-model, --mock, --rebuild, --dry-run, --yes, --no-color, -h/--help (see help()). --dry-run holds for every command: it prints what it would do
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
# Output (#533): a header with the checked-out commit or tag, then sections (Checks, Model, Build, Deploy, Open it)
# separated by blank lines, one line per step: ✓ done, ✗ failed (then a Fix: line), ! a note, → a long step. Color
# only on a terminal (--no-color or NO_COLOR turn it off, FORCE_COLOR turns it on); the elapsed-time indicator only
# on a terminal. Details go to a log file under runtime-data/demo-logs/; a failed step prints its path and last
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
MODEL_OPT="" ZRT_MODE_OPT="" ZRT_MODE="" ZRT_MODE_FROM="" CHOSEN=0 MOCK_OPT=0 REBUILD=0 DOC_STRICT=0
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
    HEAD="$B$(cap setaf 4 || printf '\033[34m')"
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
ok() { printf '  %s\342\234\223%s %s\n' "$GRN" "$X" "$*"; }
note() { printf '  %s! %s%s\n' "$YEL" "$*" "$X"; }
doing() { printf '  %s\342\206\222%s %s\n' "$CYN" "$X" "$*"; }
info() { printf '    %s\n' "$*"; }
cmdline() { printf '    %s$%s %s\n' "$D" "$X" "$*"; }  # a command that a dry run prints instead of running
# fail <message> [fix lines...]: a red line, the fix in yellow, then the log path and its last lines; exits 1.
fail() {
  local msg=$1 line first=1; shift
  printf '  %s\342\234\227 %s%s\n' "$RED$B" "$msg" "$X" >&2
  for line in "$@"; do
    if [ "$first" = 1 ]; then printf '    %sFix: %s%s\n' "$YEL" "$line" "$X" >&2; first=0
    else printf '         %s%s%s\n' "$YEL" "$line" "$X" >&2; fi
  done
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
  "$@" >> "$LOG" 2>&1 || fail "$what failed" "See the last lines of the log below, then rerun ./demo.sh $CMD"
}
quote() { local out="" a; for a in "$@"; do out+="$(printf '%q' "$a") "; done; printf '%s' "${out% }"; }
elapsed() { if [ "$1" -ge 60 ]; then printf '%dm%02ds' $(($1 / 60)) $(($1 % 60)); else printf '%ds' "$1"; fi; }
# progress <command...>: runs a long step in the background (its output into the log) and, on a terminal, shows a
# spinner with the elapsed time. Returns the command's status and sets TOOK (the elapsed time).
progress() {
  local start=$SECONDS pid rc i=0 frames=(⠋ ⠙ ⠹ ⠸ ⠼ ⠴ ⠦ ⠧ ⠇ ⠏)
  "$@" >> "$LOG" 2>&1 < /dev/null &
  pid=$!
  # shellcheck disable=SC2064  # expand $pid now
  trap "kill $pid 2>/dev/null; echo; exit 130" INT TERM
  if [ "$SPIN" = 1 ]; then
    while kill -0 "$pid" 2>/dev/null; do
      printf '\r    %s%s %s%s' "$CYN" "${frames[i++ % 10]}" "$(elapsed $((SECONDS - start)))" "$X"
      sleep 0.2
    done
    printf '\r\033[K'
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
  progress "$@" || fail "$what failed" "See the last lines of the log below, then rerun ./demo.sh $CMD"
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
    "update [<tag>]" "check out a release tag (default: the latest v*), then rerun mock or local" \
    "stop [mock|local]" "stop the app (data kept)" \
    "uninstall [--all]" "remove the app, its data, images and model unit (asks first); --all: everything demo.sh added"
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
    "--timeout <time>" "model: give up waiting after this long (e.g. 20m; default 15m Nano, 8m Fury)" \
    "--instance <name>" "local: a second instance, its own containers and data (~/.local/share/<name>)" \
    "--api-port <n>" "local: the API's port on this device (default 8100)" \
    "--web-port <n>" "local: the web port on this device (default 8180)" \
    "--all" "uninstall: also the model's serve script, ~/.config/aware-care-demo, logs, generic images" \
    "--with-model" "uninstall --all: also the downloaded model in ZRT's cache (zrt remove)" \
    "--mock" "setup: mock mode instead (no Docker, no model)" \
    "--rebuild" "setup: build and deploy again even when the app already runs this commit" \
    "--dry-run" "print what it would do; changes nothing (every command)" \
    "--yes, -y" "answer yes to the uninstall question" \
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
note_revision() { [ -z "${MATCH_NOTE:-}" ] || note "Note: $MATCH_NOTE (it works; this is only a note)"; }
served_list() { served_models | model_ids ids --models - | paste -sd, - | sed 's/,/, /g'; }

# zrt_rows <device>: the rows of `zrt services`, tab-separated (model_ids.py services, #535): 1 when it is the
# device's model (else 0), PID, status, endpoint, its loopback <endpoint>/v1 (else -), uptime in seconds, name.
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
note_zrt_url() {  # the note when ZRT_URL is a service endpoint
  [ -n "$ZRT_FOUND" ] || return 0
  if [ "$ZRT_FOUND_ON" = port ]; then
    note "Nothing on port $(url_port "$ZRT_FOUND") lists the model; it is served on port $(url_port "$ZRT_URL"), so demo.sh uses $ZRT_URL"
    info "(for example another account's ZRT on this machine). No need to serve it again with ./demo.sh model."
    info "To use this address directly next time: --zrt-port $(url_port "$ZRT_URL")"
    return 0
  fi
  note "ZRT's proxy on $(url_port "$ZRT_FOUND") does not list the model; using the service endpoint $ZRT_URL"
  info "A service's own endpoint can change when the service restarts. For a permanent setup, serve the model"
  info "through ZRT's proxy (./demo.sh model), or pass this address: --zrt-port $(url_port "$ZRT_URL")."
}
# zrt_endpoint_lines <device>: the services `zrt services` lists, for a fix text.
zrt_endpoint_lines() {
  local rows
  rows=$(zrt_rows "$1" | awk -F'\t' '{ printf "%s%s (%s, %s%s)", (NR > 1 ? "; " : ""), $4, $7, $3, $1 == 1 ? ", this model" : "" }')
  if [ -n "$rows" ]; then echo "zrt services lists: $rows"; fi
  echo "If ZRT serves the model on another port: ./demo.sh $CMD --zrt-port <port>   (or --zrt-url http://127.0.0.1:<port>/v1)"
}

# local_copy <device> [revision]: the revision of an already downloaded copy of the device's model in ZRT's cache
# (`zrt models` and $ZRT_HOME/models), the qualified one first, then main, then any; empty when there is none.
local_copy() {
  zrt_arg
  model_ids local --repo "$(device_hf "$1")" --store "$ZRT_HOME/models" "${ZRT_ARG[@]}" --revision "${2:-}" 2>/dev/null
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
  local d
  for d in nano fury; do
    if match_model "$d"; then DEVICE=$d; DEVICE_LINE="Device: ZGX ${d^} (ZRT serves $MATCH_ID)"; return; fi
  done
  for d in nano fury; do  # #535: on a ZRT service's own endpoint
    if zrt_resolve "$d"; then DEVICE=$d; DEVICE_LINE="Device: ZGX ${d^} (ZRT serves $MATCH_ID)"; return; fi
  done
  local gpu=$HW_GPU_NAME
  case "$gpu" in
    *GB10*) DEVICE=nano ;;
    *GB300*) DEVICE=fury ;;
    *) DEVICE_GPU=${gpu:-none found}; DEVICE_WHY=${M_REASON:-GPU $DEVICE_GPU}; return ;;
  esac
  DEVICE_LINE="Device: ZGX ${DEVICE^} (GPU $gpu)"
}
device_line() {
  [ -n "$DEVICE" ] || fail "No local model for this machine: ${DEVICE_WHY:-GPU $DEVICE_GPU}" \
    "Try the demo without a model: ./demo.sh mock" \
    "See what this machine has and which models fit: ./demo.sh doctor" \
    "On a ZGX device: ./demo.sh ${CMD} --device nano   (or --device fury); a catalogue model: --model <label>"
  ok "$DEVICE_LINE"
  if [ "$DEVICE" = generic ]; then
    if [ "$M_STATUS" = qualified ]; then ok "Model: $M_LABEL (qualified on this hardware), $M_SETTINGS"
    else note "Model: $M_LABEL, a candidate on this hardware (${M_TIER}; qualified: ${M_QUALIFIED_ON:-nowhere yet}). ./demo.sh check-model checks it"
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
  if [ -n "$have" ]; then
    printf '%s\n' "ZRT already has $repo downloaded (revision $have); serve that copy, no download:" \
      "  ./demo.sh model $how        (see first: ./demo.sh model $how --dry-run)"
  else
    printf '%s\n' "Let the script do it:  ./demo.sh model $how   (see first: --dry-run)" \
      "or by hand, from $ROOT:" \
      "  zrt $([ "${ZRT_MODE:-system}" = system ] || echo "-m $ZRT_MODE ")pull $hf"
  fi
  if [ "$DEVICE" = generic ]; then
    echo "Already set up? It may still be starting: systemctl --user status $UNIT"; return
  fi
  printf '%s\n' "  (by hand: install -D -m 644 $zrt/$UNIT ~/.config/systemd/user/$UNIT" \
    "   install -D -m 755 $zrt/serve-model.sh ~/.local/share/aware-care-demo/zrt/serve-model.sh" \
    "   echo AWARECARE_MODEL_REVISION=${have:-$(qualified_rev "$DEVICE")} > ~/.config/aware-care-demo/model.env" \
    "   systemctl --user daemon-reload && systemctl --user enable --now $UNIT)" \
    "Already set up? It may still be starting (up to 6 minutes on a Nano, 2 on a Fury): systemctl --user status $UNIT"
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
  printf '  %s\342\224\202%s Then open exactly:  %s%s%s\n' "$GRN" "$X" "$B$CYN" "http://127.0.0.1:$browser" "$X"
  printf '  %s\342\224\202%s %s(use 127.0.0.1, not localhost; then Start a new consultation or Open the presenter tools)%s\n' \
    "$GRN" "$X" "$YEL" "$X"
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
  command -v uv >/dev/null || fail "uv is missing" "Install it as your user: curl -LsSf https://astral.sh/uv/install.sh | sh" \
    "then open a new shell and rerun ./demo.sh mock"
  { command -v npm >/dev/null && command -v node >/dev/null; } || fail "Node 24 and npm are missing" \
    "Install them as your user, for example with nvm (https://github.com/nvm-sh/nvm): nvm install 24"
  ok "Tools: uv $(uv --version 2>/dev/null | awk '{print $2}'), Node $(node --version 2>/dev/null)"

  if mock_running; then [ "$DRY" = 1 ] || stop_mock quiet; fi

  local web=${PORT:-5173} browser=${PORT:-15173} api=8000
  if [ "$DRY" = 0 ]; then
    port_busy "$web" && fail "Port $web is in use on this device" "Choose another: ./demo.sh mock --port <n>" \
      "(see what holds it: ss -ltnp | grep :$web)"
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
    fail "The app did not become ready within 2 minutes, so demo.sh stopped what it started" "API log: $api_log" \
      "Web log: $web_log" "Then rerun ./demo.sh mock (another port: --port <n>)"
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

config_file() { if [ "$DEVICE" = generic ]; then echo infra/deploy/demo-generic.json; else echo "infra/deploy/demo-zgx-$DEVICE.json"; fi; }
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

# The image of this instance's API container when it is not this account's: a release deployed by the maintainer's
# deploy workflow (an image demo.sh did not build), or #634 another account's ./demo.sh instance (container names are
# the same for every account on a machine). demo.sh never replaces, stops or removes such a deployment.
# foreign_image [instance] [data root]: this instance's by default.
foreign_image() {
  local inst=${1:-$INSTANCE} root=${2:-$DATA_ROOT} img
  img=$(docker container inspect -f '{{.Config.Image}}' "$inst-api" 2>/dev/null) \
    || img=$(sed -n 's/^ *"api_image": "\(.*\)",*$/\1/p' "$root/state/current.json" 2>/dev/null | head -n1)
  [ -n "$img" ] || return 1
  [ "$img" != "$inst-api:local" ] || other_owner "$inst" "$root" >/dev/null || return 1
  echo "$img"
}
# instance_root [instance] (#634): the data root the instance's API container mounts (<root>/data/<mode>).
instance_root() {
  local src
  src=$(docker container inspect -f \
    '{{range .Mounts}}{{if eq .Destination "/var/lib/aware-care/data"}}{{.Source}}{{end}}{{end}}' "${1:-$INSTANCE}-api" \
    2>/dev/null) || return 1
  [ -n "$src" ] || return 1
  echo "${src%/data/*}"
}
# other_owner [instance] [data root] (#634): the account whose ./demo.sh instance this is, when it keeps its data
# elsewhere than this account's data root: the data root's owner, else the user in /home/<user>/, else "another account".
other_owner() {
  local inst=${1:-$INSTANCE} root=${2:-$DATA_ROOT} theirs who=""
  theirs=$(instance_root "$inst") || return 1
  [ "$(canon "$theirs")" != "$(canon "$root")" ] || return 1
  who=$(stat -c %U "$theirs" 2>/dev/null) || who=""
  if [ -z "$who" ] && [[ $theirs =~ ^/home/([^/]+)/ ]]; then who=${BASH_REMATCH[1]}; fi
  echo "${who:-another account}"
}
# foreign_what [instance] [data root]: what runs there, after foreign_image found it is not this account's.
foreign_what() {
  local inst=${1:-$INSTANCE} who
  if [ "$(docker container inspect -f '{{.Config.Image}}' "$inst-api" 2>/dev/null)" = "$inst-api:local" ] \
    && who=$(other_owner "$@"); then
    echo "the ./demo.sh instance of $who (data in $(instance_root "$inst"))"
  else echo "a release from the deploy workflow"; fi
}
refuse_foreign() {  # this instance's containers are a workflow release or another account's instance: refuse
  local inst=$INSTANCE img who="" why change
  # #636: uninstall goes ahead once the containers are gone (a stopped release is only a record in the data root)
  if [ "$CMD" = uninstall ] && ! docker container inspect "$inst-api" >/dev/null 2>&1; then return 0; fi
  img=$(foreign_image) || return 0
  if [ "$img" = "$inst-api:local" ]; then who=$(other_owner); fi
  if [ -n "$who" ] && [ "$who" = "$(id -un)" ]; then  # your own instance, with its data elsewhere
    fail "The containers $inst-api and $inst-web keep their data in $(instance_root), not in $DATA_ROOT" \
      "Rerun with that data root: AWARECARE_DEMO_DATA_ROOT=$(instance_root) ./demo.sh $CMD$(instance_args)" \
      "or use another instance: ./demo.sh $CMD --instance my-demo --api-port 28100 --web-port 28180"
  elif [ -n "$who" ]; then
    why="The containers $inst-api and $inst-web are $(foreign_what); demo.sh leaves them alone"
    change="Only $who changes or stops that instance (container names are the same for every account on a machine)."
  else
    why="The containers $inst-api and $inst-web run $img, which demo.sh did not build (a release from the deploy workflow); demo.sh leaves them alone"
    change="Change that deployment only through its deploy workflow (maintainers)."
  fi
  case $CMD in
    # #617: stop and uninstall act on your own instance instead (no deploy ports: they start nothing)
    stop|uninstall)
      [ -n "$who" ] || [ "$CMD" = stop ] \
        || change+=" To remove it anyway (maintainers only): docker rm -f $inst-api $inst-web, then rerun ./demo.sh uninstall."
      fail "$why" "To $CMD only your own instance: ./demo.sh $CMD$([ "$CMD" = stop ] && echo " local") --instance <name>" \
        "$change" ;;
    local|setup) use_running_release "$img" "$who" ;;
    *)
      fail "$why" "Run your own copy beside it on other ports and data (data in ~/.local/share/my-demo):" \
        "  ./demo.sh $CMD --instance my-demo --api-port 28100 --web-port 28180" \
        "$change" ;;
  esac
}
# use_running_release <image> [account] (#632): local or setup where the deploy workflow's release (on a shared ZGX, the
# maintainer's) or #634 another account's ./demo.sh instance already runs as this instance: the demo is already here,
# so say how to open it; a second instance is only for your own copy. Exits 0 when it answers ready, else 1.
use_running_release() {
  local inst=$INSTANCE release env web origin browser
  release=$(docker container inspect -f '{{index .Config.Labels "aware-care.release"}}' "$inst-web" 2>/dev/null)
  env=$(docker container inspect -f '{{json .Config.Env}}' "$inst-web" 2>/dev/null)
  web=$(sed -n 's/.*"AWARECARE_WEB_PORT=\([0-9]*\)".*/\1/p' <<< "$env")
  origin=$(sed -n 's/.*"AWARECARE_ORIGIN=\([^"]*\)".*/\1/p' <<< "$env")
  web=${web:-$(config_value "['network']['web_port']")}
  # the browser port is the release's own origin (its Origin checks accept only that address)
  browser=$(url_port "${origin:-$(config_value "['network']['browser_origin']")}")
  section "Already running"
  if [ -n "${2:-}" ]; then
    ok "The demo already runs on this machine: the instance of $2${release:+, $release} ($inst-api, $inst-web)"
    info "Set up by $2 with ./demo.sh. You can use it as it is (you share its data): nothing to set up."
  else
    ok "The demo already runs on this machine: release ${release:-$1} ($inst-api, $inst-web)"
    info "Set up by the maintainer's deploy workflow, with the model it needs. You can use it as it is: nothing to set up."
  fi
  if ! curl -s --noproxy '*' -m 5 "http://127.0.0.1:$web$READY_PATH" 2>/dev/null | grep -q '"readiness":"ready"'; then
    fail "The running demo does not answer ready on 127.0.0.1:$web" \
      "It may still be starting; try again in 2 minutes, or ask ${2:-the maintainer} to check it (./demo.sh status)." \
      "Or run your own copy beside it (data in ~/.local/share/my-demo):" \
      "  ./demo.sh $CMD --instance my-demo --api-port 28100 --web-port 28180"
  fi
  ok "It answers ready on 127.0.0.1:$web"
  open_it "$browser" "$web"
  next_steps "Want your own copy instead (your own data, or code you changed)? Run it beside this one:"
  next_steps "  ./demo.sh $CMD --instance my-demo --api-port 28100 --web-port 28180"
  if [ -n "${2:-}" ]; then next_steps "demo.sh never changes another account's instance; only $2 updates or stops it."
  else next_steps "demo.sh never changes the running release; only its deploy workflow does (maintainers)."; fi
  exit 0
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
  if [ -n "$DOCKER_OTHER" ]; then
    note "Docker CLI: $DOCKER_BIN, from $DOCKER_ENV, comes before $DOCKER_OTHER on PATH"
  else note "Docker CLI: $DOCKER_BIN, from $DOCKER_ENV"; fi
  info "Its docker may not find the system's plugins (docker buildx). Fix: conda deactivate (or deactivate a virtualenv),"
  info "then rerun; or put the system Docker CLI first: PATH=$(dirname "${DOCKER_OTHER:-/usr/bin/docker}"):\$PATH ./demo.sh ${CMD:-setup}"
}
# buildx_line: the buildx this machine has (infra/deploy/find_buildx.sh, the same build_images.sh uses), or fail/bad.
buildx_line() {
  # shellcheck disable=SC1091  # infra/deploy/find_buildx.sh is checked on its own
  . "$ROOT/infra/deploy/find_buildx.sh"
  if find_buildx; then ok "$BUILDX_HOW"; return 0; fi
  "${1:-fail}" "docker buildx is missing" \
    "Install the Docker buildx plugin (package docker-buildx-plugin; check: docker buildx version)," \
    "or the standalone docker-buildx program on your PATH (check: docker-buildx version). Tried: $BUILDX_TRIED"
}

check_docker() {
  command -v docker >/dev/null || fail "Docker is not installed" "Ask an administrator to install Docker Engine with the buildx plugin."
  docker_cli_lines
  local out
  if ! out=$(docker info 2>&1); then
    if grep -qi 'permission denied' <<< "$out"; then
      fail "Docker is not usable without sudo (your user is not in the docker group)" \
        "Once, with sudo:  sudo usermod -aG docker \$USER" \
        "then log out and back in (or reboot), check that 'docker ps' works without sudo, and rerun ./demo.sh local"
    fi
    fail "Docker does not answer: $(head -n1 <<< "$out")" "Start it: sudo systemctl start docker (or ask an administrator)"
  fi
  DOCKER_INFO=$out
  ok "Docker usable without sudo"
  # #535, #549: the plugin, the standalone program, the plugin binary run directly, or `docker docker-buildx`
  buildx_line
}

proxy_fix_lines() {
  local p=${1:-<proxy>}
  printf '%s\n' "Ask your IT for the proxy address." \
    "Your shell (add to ~/.bashrc):" \
    "  export HTTP_PROXY=$p HTTPS_PROXY=$p NO_PROXY=localhost,127.0.0.1" \
    "  export http_proxy=$p https_proxy=$p no_proxy=localhost,127.0.0.1" \
    "The Docker daemon (once, with sudo), in /etc/systemd/system/docker.service.d/http-proxy.conf:" \
    "  [Service]" \
    "  Environment=\"HTTP_PROXY=$p\" \"HTTPS_PROXY=$p\" \"NO_PROXY=localhost,127.0.0.1\"" \
    "  then: sudo systemctl daemon-reload && sudo systemctl restart docker" \
    "Then rerun ./demo.sh local"
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
      "Check the address with your IT, then: export HTTPS_PROXY=<proxy> https_proxy=<proxy>"
  fi
  if [ -z "$daemon_proxy" ]; then
    local IFS=$'\n'
    # shellcheck disable=SC2046
    fail "Your shell uses the proxy $shell_proxy, but the Docker daemon has none (docker info shows no HTTPS Proxy), so base images cannot be pulled" \
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
    "Run on other ports, as a second instance with its own containers and data:" \
    "  ./demo.sh local --instance my-demo --api-port 28100 --web-port 28180" \
    "(see what holds it: ss -ltnp | grep -E ':($api|$web) ')"
  ok "Ports free: API 127.0.0.1:$api, web 127.0.0.1:$web"
}

check_model() {
  MODEL=$(device_model "$DEVICE")
  [ -n "$MODEL" ] || fail "No model chosen for this machine" "See why: ./demo.sh doctor"
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
  dirty && note "Note: the checkout has local changes; the images include them."
  command -v python3 >/dev/null || fail "python3 is missing" "Install python3 (the system one is fine)."
  check_docker
  refuse_foreign
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
    note "Dry run: these commands were printed, not run."
  else
    doing "Deploying and running one synthetic consultation on the model (1 to 3 minutes) ..."
    printf '\n$ %s\n' "$(quote "${DEPLOY[@]}" deploy ...)" >> "$LOG"
    progress "${DEPLOY[@]}" "${deploy_args[@]}"
    local rc=$? outcome
    outcome=$(sed -n 's/^\[nano-deploy\] outcome: //p' "$LOG" | tail -n1)
    [ "$rc" = 0 ] || fail "Deploy failed: outcome ${outcome:-unknown}" "The log names the failed step; see the log lines below, README.md and docs/wiki/Troubleshooting.md."
    ok "outcome: $outcome ($tag, commit ${commit:0:12}, model $MODEL, $TOOK)"
  fi
  open_app
}
open_app() {  # the Open it box for the deployed app (local, setup)
  local web browser
  web=${AWARECARE_DEMO_WEB_PORT:-$(config_value "['network']['web_port']")}
  browser=${PORT:-$(config_value "['network']['browser_origin']" | sed 's/.*://')}
  open_it "$browser" "$web"
  local where
  where=$(instance_args)
  if [ -n "$where" ]; then next_steps "Status: ./demo.sh status$where    Stop: ./demo.sh stop local$where"
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
  doctor_checks
  [ -n "$DEVICE" ] || device_line  # no model for this machine: stops with the fix
  dirty && note "Note: the checkout has local changes; the images include them."
  refuse_foreign
  model_steps "Serve the model"
  MODEL=$(device_model "$DEVICE")
  deploy_tool
  if [ "$REBUILD" = 0 ] && app_current; then
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
model_timeout() { if [ -n "$TIMEOUT" ]; then echo "$TIMEOUT"; elif [ "$DEVICE" = fury ]; then echo 480; else echo 900; fi; }
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
  printf '%s\n' "Set it, then restart the unit:" \
    "  echo AWARECARE_CUDA_HOME=$1 >> $MODEL_ENV" \
    "  systemctl --user restart $UNIT"
}
check_cuda() {
  local cuda want
  want=$(cuda_preferred)
  if cuda=$(cuda_choice); then
    if [ "$cuda" = "$want" ]; then ok "CUDA toolchain: $cuda"
    else note "Note: $want is not installed here; the serve script uses $cuda (found: $(cuda_dirs))"; fi
    return 0
  fi
  local IFS=$'\n'
  # shellcheck disable=SC2046
  fail "No CUDA toolchain with bin/nvcc for the serve script (it wants $want; found: $(cuda_dirs | grep . || echo none))" \
    $(cuda_fix "<a CUDA 13 directory with bin/nvcc>") "No CUDA 13 at all? Ask an administrator to install the CUDA 13 toolkit."
}

# zrt_service: "<pid>|<status>|<uptime seconds>" of the ZRT service that serves this device's model, from the table
# `zrt services` prints (zrt_rows; both of its layouts, #535).
zrt_service() { zrt_rows "$DEVICE" | awk -F'\t' '$1 == 1 { print $2 "|" $3 "|" $6; exit }'; }
unit_age() {  # seconds since the unit began activating
  local since
  since=$(unit_prop InactiveExitTimestamp)
  [ -n "$since" ] && since=$(date -d "$since" +%s 2>/dev/null) && echo $(($(date +%s) - since))
}

# wait_for_model: polls until ZRT lists the model; stops early when the unit failed or stopped, when ZRT's service
# keeps restarting (its PID changes, or it is younger than the unit's start while not Ready), when the unit finished
# and no ZRT service process for the model is left (#636: ZRT 0.43 on the Fury lists a loading service as Dead after
# the oneshot unit finished; it served the model a minute later), or at the timeout.
# Prints a status line every 30 seconds. Sets TOOK, or WAIT_WHY on failure.
wait_for_model() {
  local start=$SECONDS limit t last=-30 active sub restarts svc pid status up age seen="" changes=0 line i=0 k
  local frames=(⠋ ⠙ ⠹ ⠸ ⠼ ⠴ ⠦ ⠧ ⠇ ⠏)
  limit=$(model_timeout); WAIT_WHY=""
  while :; do
    t=$((SECONDS - start))
    if zrt_resolve "$DEVICE"; then [ "$SPIN" = 0 ] || printf '\r\033[K'; TOOK=$(elapsed "$t"); return 0; fi
    active=$(unit_prop ActiveState); sub=$(unit_prop SubState); restarts=$(unit_prop NRestarts)
    svc=$(zrt_service); pid=${svc%%|*}; status=$(cut -d'|' -f2 <<< "$svc"); up=${svc##*|}
    if [ -n "$pid" ]; then
      if [ -n "$seen" ] && [ "$pid" != "$seen" ]; then changes=$((changes + 1)); fi
      seen=$pid
    fi
    age=$(unit_age)
    if [ "$active" = failed ]; then WAIT_WHY="The unit $UNIT failed ($sub)"
    elif [ "$active" = inactive ] && [ "$t" -ge 15 ]; then WAIT_WHY="The unit $UNIT stopped (inactive, ${sub:-dead})"
    elif [ "${restarts:-0}" -ge 3 ]; then WAIT_WHY="The unit $UNIT restarted $restarts times"
    elif [ "$changes" -ge 2 ]; then WAIT_WHY="ZRT's service for the model keeps restarting (PID changed $changes times; now $pid, $status)"
    elif [ "$active" = activating ] && [ -n "$svc" ] && [ "$status" != Ready ] && [ -n "$age" ] \
         && [ "$age" -ge 300 ] && [ $((up + 120)) -lt "$age" ]; then
      WAIT_WHY="ZRT's service for the model keeps restarting: the unit has been starting for $(elapsed "$age"), but the service (PID $pid, $status) is only $(elapsed "$up") old"
    elif [ "$active" = active ] && [ "$sub" = exited ] && [ "$t" -ge "${AWARECARE_DEMO_FINISHED_GRACE:-60}" ] \
         && ! { [ -n "$pid" ] && ps -p "$pid" >/dev/null 2>&1; }; then
      WAIT_WHY="The unit $UNIT finished, but ZRT does not list $(device_model "$DEVICE")"
    elif [ "$t" -ge "$limit" ]; then WAIT_WHY="ZRT did not serve $(device_model "$DEVICE") within $(elapsed "$limit")"
    fi
    if [ -n "$WAIT_WHY" ]; then [ "$SPIN" = 0 ] || printf '\r\033[K'; return 1; fi
    if [ $((t - last)) -ge 30 ]; then
      [ "$SPIN" = 0 ] || printf '\r\033[K'
      line=$(journal_tail 1 | tail -n1 | cut -c1-90)
      info "$(elapsed "$t"): unit ${active:-unknown}${sub:+ ($sub)}${svc:+; ZRT service $status, PID $pid}${line:+; $line}"
      last=$t
    fi
    if [ "$SPIN" = 1 ]; then
      for ((k = 0; k < POLL * 5; k++)); do
        printf '\r    %s%s %s%s' "$CYN" "${frames[i++ % 10]}" "$(elapsed $((SECONDS - start)))" "$X"; sleep 0.2
      done
    else
      sleep "$POLL"
    fi
  done
}

# model_diagnosis: the known causes found now, each with its fix (#533).
model_diagnosis() {
  local journal cuda want apps label
  journal=$(journal_tail 50)
  label=$(device_model "$DEVICE"); want=$(cuda_preferred)
  if ! cuda=$(cuda_choice); then
    echo "CUDA: no toolchain with bin/nvcc (wanted $want; found: $(cuda_dirs | grep . || echo none))."
    cuda_fix "<a CUDA 13 directory with bin/nvcc>"
  elif [ "$cuda" != "$want" ] || grep -qiE 'nvcc|cuda_home|cuda-1[0-9]' <<< "$journal"; then
    echo "CUDA: the serve script uses $cuda (qualified: $want; found: $(cuda_dirs)). If the journal shows CUDA errors, pick another one."
    cuda_fix "$cuda"
  fi
  apps=$(nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader 2>/dev/null | paste -sd';' - | sed 's/;/; /g')
  if [ -n "$apps" ] || grep -qiE 'out of memory|free memory on device|insufficient memory' <<< "$journal"; then
    echo "GPU memory: processes on the GPU now: ${apps:-none listed}. Stop the one that is not this model (another ZRT model: zrt services, then zrt service stop <uri>), then ./demo.sh model"
  fi
  if ! curl -s --noproxy '*' -m 5 -o /dev/null "$ZRT_URL/models" 2>/dev/null || ! find_zrt >/dev/null; then
    echo "ZRT: its proxy does not answer on $ZRT_URL (or zrt is missing). Check: zrt services. ZRT runs as a system service: ask an administrator to start it"
  fi
  linger_on || echo "Lingering is off, so the unit stops when you log out: loginctl enable-linger \"\$USER\" (may need an administrator)"
  echo "ZRT's own log: zrt logs tail $label --lines 50"  # #636: `zrt logs <model>` only prints help
  local z; if z=$(find_zrt); then timeout 10 "$z" -m "${ZRT_MODE:-system}" logs tail "$label" --lines 8 2>&1 | sed 's/^/  | /'; fi
  echo "More: systemctl --user status $UNIT; journalctl --user -u $UNIT -n 100"
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
    # #640: the watchdog of a model unit installed earlier (one installed before the watchdog existed gets it now);
    # nothing when it is installed as this checkout has it and on (so a rerun of setup changes nothing)
    if [ -e "$HOME/.config/systemd/user/$UNIT" ] && ! watchdog_current; then
      section "Watchdog"
      install_watchdog
      run "systemctl daemon-reload" systemctl --user daemon-reload
      start_watchdog
    fi
    return 0
  fi
  local z
  z=$(find_zrt) || { [ "$DRY" = 1 ] && z=zrt; } \
    || fail "The zrt command is missing" "ZRT is preinstalled on ZGX devices; ask an administrator to install it."
  # #549: ZRT serves a model through its proxy, on the port ZRT is set to; another port asked for is ZRT's setting
  local want; want=$(url_port "$ZRT_URL")
  if [ -n "$ZRT_CONFIG_PORT" ] && [ "$want" != "$ZRT_CONFIG_PORT" ]; then
    fail "ZRT's proxy is set to port $ZRT_CONFIG_PORT (zrt config get proxy.port), so ZRT would serve $model there, not on $want ($ZRT_URL_FROM)" \
      "Serve it through ZRT's proxy port: ./demo.sh $CMD --zrt-port $ZRT_CONFIG_PORT   (or leave out --zrt-port, --zrt-url and AWARECARE_ZRT_URL)" \
      "or set ZRT's proxy to port $want first: zrt -m ${ZRT_MODE:-system} config set proxy.port $want" \
      "  (ZRT's own setting: in system mode it holds for every user of ZRT on this machine, so an administrator decides)," \
      "  then rerun ./demo.sh $CMD"
  fi
  check_cuda
  # #528: serve a copy ZRT already has (any revision) before downloading the qualified one.
  local rev
  rev=$(local_copy "$DEVICE" "$REVISION")
  if [ -n "$rev" ]; then
    ok "ZRT already has $repo@$rev downloaded; serving that copy (no download)"
  else
    rev=${REVISION:-$qualified}
    local size
    size=$(catalog_size "$model")
    [ -z "$size" ] || info "Download: $repo@$rev, about $size GB (once; ZRT keeps it in its cache)"
    long_run "zrt pull" "Downloading $repo@$rev (this can take a long time) ..." \
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
        "Make $(dirname "$MODEL_ENV") writable for $USER (ls -ld it), check the disk has space (df -h \"\$HOME\"), then rerun ./demo.sh $CMD"
  fi
  if [ "$DEVICE" = generic ]; then
    # the catalogue entry's serving flags, one per line, read by the generic serve script
    local args_file="$HOME/.local/share/aware-care-demo/zrt/serve.args" flags
    flags=$(hardware serve-args --model "$model" --tp "${M_TP:-1}") || fail "No serving settings for $model" "./demo.sh doctor"
    if [ "$DRY" = 1 ]; then
      cmdline "serving flags in $args_file: $(paste -sd' ' <<< "$flags")"
    else
      printf '%s\n' "$flags" > "$args_file" || fail "Could not write $args_file" "Check the disk and that folder, then rerun ./demo.sh $CMD"
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
  if [ "$DRY" = 1 ]; then note "Dry run: nothing was downloaded, installed or started."; return 0; fi
  local usual="about 6 minutes on a Nano, 2 on a Fury"
  [ "$DEVICE" != generic ] || usual="several minutes the first time"
  doing "Starting hf:$repo@$rev as $model ($usual; gives up after $(elapsed "$(model_timeout)")) ..."
  wait_for_model || model_failed
  ok "ZRT serves $(served_as "$DEVICE") on $ZRT_URL ($TOOK)"
  note_zrt_url
  linger_on || note "To keep it running after you log out: loginctl enable-linger \"\$USER\" (may need an administrator)"
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
    note "Watchdog: on, but it gave up after 3 restarts within an hour (last restart $when); ./demo.sh model serves the model again"
  else ok "Watchdog: on (restarts the model unit when the model dies; $restarted)"; fi
}
# ------------------------------------------------------------------ doctor, check-model (#537)

machine_lines() {  # the machine in a few lines (status, doctor)
  ok "Machine: ${HW_NAME:-unknown} (${HW_ARCH:-?}; images for ${HW_PLATFORM:-?})"
  if [ "${HW_GPU_COUNT:-0}" = 0 ]; then note "GPU: none found (nvidia-smi lists no NVIDIA GPU)"
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
bad() {  # bad <message> [fix lines...]: a ✗ line that does not stop doctor (in setup it does: fail)
  if [ "$DOC_STRICT" = 1 ]; then fail "$@"; fi
  local first=1 line
  printf '  %s\342\234\227 %s%s\n' "$RED$B" "$1" "$X"; shift
  for line in "$@"; do
    if [ "$first" = 1 ]; then printf '    %sFix: %s%s\n' "$YEL" "$line" "$X"; first=0
    else printf '         %s%s%s\n' "$YEL" "$line" "$X"; fi
  done
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
  section "Verdict"
  if [ "$DOC_BAD" = 0 ]; then
    if [ -n "${DOC_HAVE:-}" ]; then ok "Ready for ./demo.sh setup (or ./demo.sh local)"
    else ok "Ready: ./demo.sh setup (downloads and serves the model, then builds and deploys the app)"; fi
    next_steps "Afterwards, optional: ./demo.sh check-model (advisory; writes a report you can send back)"
  else
    printf '  %s\342\234\227 Fix %d item%s first (marked \342\234\227 above); ./demo.sh mock runs without them%s\n' \
      "$RED$B" "$DOC_BAD" "$([ "$DOC_BAD" = 1 ] || echo s)" "$X"
  fi
}
# doctor_checks: the sections Machine, Docker and network, ZRT, Model and Ports (doctor; setup, strictly).
doctor_checks() {
  hw_choose
  # #549: whether ZRT serves the model already (then a CUDA toolkit is not needed to serve it)
  local dev=${DEVICE:-$M_PROFILE} doc_served=0 url=$ZRT_URL found=$ZRT_FOUND found_on=$ZRT_FOUND_ON
  if [ -n "$M_LABEL" ] && [ -n "$dev" ] && zrt_resolve "$dev"; then doc_served=1; fi
  # the ZRT section shows ZRT's own address; the Model section finds the model again
  ZRT_URL=$url ZRT_FOUND=$found ZRT_FOUND_ON=$found_on
  section "Machine"
  machine_lines
  [ -z "$HW_PRODUCT" ] || [ "$HW_PRODUCT" = "$HW_NAME" ] || info "DMI product name: $HW_PRODUCT"
  [ -n "$HW_PRODUCT" ] || note "DMI product name not readable; the app will call it \"$HW_NAME\""
  [ -z "$HW_MEM_GB" ] || info "System memory: $HW_MEM_GB GB"
  if [ -n "$HW_DRIVER" ]; then info "NVIDIA driver $HW_DRIVER (supports CUDA ${HW_CUDA:-?})"; fi
  if [ -n "$HW_TOOLKIT" ]; then ok "CUDA toolkit: $HW_TOOLKIT (${HW_TOOLKIT_VERSION:-?}, bin/nvcc)"
  elif [ "$doc_served" = 1 ]; then
    note "CUDA toolkit: none with bin/nvcc under ${AWARECARE_CUDA_ROOT:-/usr/local}; ZRT already serves the model, so it is not needed now"
  elif [ "${HW_GPU_COUNT:-0}" != 0 ]; then
    bad "CUDA toolkit: none with bin/nvcc under ${AWARECARE_CUDA_ROOT:-/usr/local} (ZRT needs one to serve a model)" \
      "ask an administrator to install the CUDA toolkit (CUDA 12.8 or later for Blackwell GPUs)"
  fi

  section "Docker and network"
  local out
  if [ "$DOC_STRICT" = 1 ]; then  # setup: local's checks, whose fixes are complete (the proxy for shell and daemon)
    check_docker; check_network
  elif ! command -v docker >/dev/null; then bad "Docker is not installed" "ask an administrator to install Docker Engine with buildx"
  elif docker_cli_lines all; ! out=$(docker info 2>&1); then
    if grep -qi 'permission denied' <<< "$out"; then
      bad "Docker is not usable without sudo (your user is not in the docker group)" \
        "sudo usermod -aG docker \$USER, then log out and back in"
    else bad "Docker does not answer: $(head -n1 <<< "$out")" "sudo systemctl start docker (or ask an administrator)"; fi
  else
    DOCKER_INFO=$out
    ok "Docker usable without sudo"
    buildx_line bad
  fi
  if [ "$DOC_STRICT" = 0 ]; then
    local shell_proxy=${HTTPS_PROXY:-${https_proxy:-}} daemon_proxy
    daemon_proxy=$(sed -n 's/^ *HTTPS Proxy: *//p' <<< "${DOCKER_INFO:-}" | head -n1)
    if curl -s --noproxy '*' -m 6 -o /dev/null "$PROBE_URL" 2>/dev/null; then ok "Internet: ghcr.io reachable directly"
    elif [ -z "$shell_proxy" ]; then bad "ghcr.io does not answer and no proxy is set (HTTPS_PROXY)" "./demo.sh setup (or local) prints the proxy settings for your shell and Docker"
    elif ! curl -s -m 10 -o /dev/null "$PROBE_URL" 2>/dev/null; then bad "ghcr.io does not answer through your proxy $shell_proxy" "check the proxy address with IT"
    elif [ -z "$daemon_proxy" ]; then bad "Your shell uses the proxy $shell_proxy, but the Docker daemon has none" "./demo.sh setup (or local) prints the daemon's proxy file"
    else ok "Internet through the proxy $shell_proxy (shell and Docker daemon)"; fi
    if GIT_TERMINAL_PROMPT=0 timeout "${AWARECARE_DEMO_REMOTE_TIMEOUT:-20}" git -C "$ROOT" ls-remote origin HEAD >/dev/null 2>&1; then ok "Repository: origin answers (git ls-remote)"
    else note "Repository: git ls-remote origin failed (needed only for ./demo.sh update)"; fi
  fi

  section "ZRT"
  local z ver
  if z=$(find_zrt); then
    ver=$(timeout 10 "$z" -m "$ZRT_MODE" version 2>/dev/null | head -n1)
    ok "zrt: $z (${ver:-version unknown}), mode $ZRT_MODE (from $ZRT_MODE_FROM)"
  else bad "zrt: not found" "ZRT is preinstalled on ZGX devices; elsewhere ask an administrator to install it"; fi
  ok "ZRT address: $ZRT_URL (from $ZRT_URL_FROM)"
  if zrt_explicit && [ -n "$ZRT_CONFIG_PORT" ] && [ "$(url_port "$ZRT_URL")" != "$ZRT_CONFIG_PORT" ]; then
    info "ZRT's proxy is set to port $ZRT_CONFIG_PORT (zrt config get proxy.port); ./demo.sh model serves through that port"
  fi
  local served
  served=$(served_list)
  if [ -n "$served" ]; then ok "ZRT on $ZRT_URL serves: $served"
  else note "ZRT on $ZRT_URL: no model served (or no answer)"; fi
  if [ -n "$M_LABEL" ]; then
    local rows
    rows=$(DEVICE=$M_PROFILE zrt_rows "$M_PROFILE" | awk -F'\t' '{ printf "%s%s (%s, %s)", (NR > 1 ? "; " : ""), $4, $7, $3 }')
    [ -z "$rows" ] || info "zrt services: $rows"
  fi
  if linger_on; then ok "Lingering on: the model unit keeps running after you log out"
  else note "Lingering off: the model unit stops when you log out (loginctl enable-linger \"\$USER\"; may need an administrator)"; fi
  watchdog_line

  section "Model"
  if [ -z "$M_LABEL" ]; then
    bad "No local model: $M_REASON" "run the demo without a model: ./demo.sh setup --mock (or ./demo.sh mock)"
  else
    local was=$DEVICE
    DEVICE=$M_PROFILE
    # shellcheck disable=SC2153  # set by hw_choose (printf -v)
    ok "Model for this machine: $M_LABEL ($M_REPO@${M_REVISION:0:7}, $M_SIZE_GB GB)"
    info "Why: $M_REASON"
    if [ "$M_STATUS" = qualified ]; then ok "Qualified on this hardware (${M_QUALIFIED_ON})"
    else note "Candidate on this hardware: chosen by GPU memory, not qualified here (qualified: ${M_QUALIFIED_ON:-nowhere yet}); ./demo.sh check-model checks it (advisory)"; fi
    info "Serving: $M_SETTINGS"
    local have="" need
    if zrt_resolve "$DEVICE"; then ok "ZRT serves it: $(served_as "$DEVICE") on $ZRT_URL"; have=served
      note_zrt_url
    else
      have=$(local_copy "$DEVICE")
      if [ -n "$have" ]; then ok "Downloaded: revision $have (./demo.sh model serves it, no download)"
      else info "Not downloaded yet: ./demo.sh setup (or model) downloads $M_SIZE_GB GB"; fi
    fi
    if [ -z "$have" ]; then
      need=$(awk -v s="$M_SIZE_GB" 'BEGIN { printf "%d", s * 1.1 + 1 }')
      local avail; avail=$(free_gb "$ZRT_HOME/models")
      if [ -n "$avail" ] && [ "$avail" -lt "$need" ]; then
        bad "Disk: $avail GB free for ZRT's models ($ZRT_HOME), the model needs about $need GB" "free some space, or remove unused models: zrt -m $ZRT_MODE remove <model>"
      elif [ -n "$avail" ]; then ok "Disk: $avail GB free for ZRT's models ($ZRT_HOME)"; fi
    fi
    DEVICE=$was
  fi
  local droot avail
  droot=$(sed -n 's/^ *Docker Root Dir: *//p' <<< "${DOCKER_INFO:-}" | head -n1)
  avail=$(free_gb "${droot:-/var/lib/docker}")
  if [ -n "$avail" ] && [ "$avail" -lt 10 ]; then bad "Disk: $avail GB free for Docker images (${droot:-/var/lib/docker}); the build needs about 10 GB" "docker system prune (removes unused images)"
  elif [ -n "$avail" ]; then ok "Disk: $avail GB free for Docker images (${droot:-/var/lib/docker})"; fi

  section "Ports"
  local p
  for p in "${AWARECARE_DEMO_API_PORT:-8100}" "${AWARECARE_DEMO_WEB_PORT:-8180}"; do
    if ! port_busy "$p"; then ok "Port $p free"
    elif command -v docker >/dev/null && local_running; then ok "Port $p used by the running demo ($INSTANCE)"
    else bad "Port $p is in use" "see what holds it: ss -ltnp | grep :$p; or run beside it: AWARECARE_DEMO_API_PORT / AWARECARE_DEMO_WEB_PORT"; fi
  done

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
  command -v uv >/dev/null || fail "uv is missing" "Install it as your user: curl -LsSf https://astral.sh/uv/install.sh | sh" \
    "then open a new shell and rerun ./demo.sh check-model"
  ok "Tools: uv $(uv --version 2>/dev/null | awk '{print $2}')"
  section "Model"
  local model; model=$(device_model "$DEVICE")
  if ! zrt_resolve "$DEVICE"; then
    [ "$DRY" = 1 ] || fail "ZRT does not serve $model on $ZRT_URL" "Serve it first: ./demo.sh model" "See what is found: ./demo.sh doctor"
    MATCH_ID=$model
    note "Dry run: ZRT does not serve $model on $ZRT_URL yet"
  else ok "ZRT serves $(served_as "$DEVICE") on $ZRT_URL"; note_revision; note_zrt_url; fi
  section "Run"
  local stamp out report
  stamp=$(date +%Y%m%d-%H%M%S)-$$
  out="$LOG_DIR/check-model-$stamp"
  report="$LOG_DIR/check-model-$(hostname -s 2>/dev/null || echo host)-$stamp.json"
  local cmd=(env "AI_REGRESSION_OUT=$out" "AI_REGRESSION_MODEL=$MATCH_ID" "AI_REGRESSION_ZRT_URL=$ZRT_URL"
    scripts/ai_regression/run.sh here)
  if [ "$DRY" = 1 ]; then cmdline "$(quote "${cmd[@]}")"; note "Dry run: nothing was run."; return 0; fi
  # #544: one AI job at a time on this machine's model; waits (with a message) while another one runs
  # shellcheck disable=SC1091  # the lock helper; this shell holds the lock until it exits
  . "$ROOT/scripts/dev/with_model_lock.sh"
  model_lock_acquire "./demo.sh check-model" || fail "Another AI job kept the model busy" \
    "Wait for it to finish, then rerun ./demo.sh check-model (lock: ${AWARE_CARE_MODEL_LOCK:-/tmp/aware-care-model.lock})"
  doing "Running about 63 synthetic cases through the app in local mode (a few minutes on a fast GPU, longer on a small one) ..."
  printf '
$ %s
' "$(quote "${cmd[@]}")" >> "$LOG"
  progress "${cmd[@]}"
  local rc=$?
  [ -s "$out/here.json" ] || fail "The check did not run (exit $rc)" "See the log below; the run's own log: $out/here.log"
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
  else note "Result: ${gate:-unknown}: advisory only; the model still runs. Send the report so the maintainers can look"; fi
  ok "Report: $report"
  next_steps "Send that file back (synthetic cases only; it holds no patient data). This check is advisory and never blocks."
}

# ------------------------------------------------------------------ status, stop, uninstall, update

local_running() { docker container inspect -f '{{.State.Running}}' "$INSTANCE-api" 2>/dev/null | grep -q true; }

cmd_status() {
  header "status"
  dirty && { echo; note "Note: the checkout has local changes."; }
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
  [ "$M_PROFILE" != generic ] || devices=(generic nano fury)
  for d in "${devices[@]}"; do
    [ -z "$DEVICE" ] || [ "$DEVICE" = "$d" ] || continue
    if zrt_resolve "$d"; then served=$d; DEVICE=$d; ok "ZRT serves $(served_as "$d") on $ZRT_URL"; note_revision; break; fi
  done
  if [ -n "$served" ]; then note_zrt_url
  else note "ZRT: no supported model served on $ZRT_URL (it serves: $(served_list | grep . || echo nothing))"; fi
  watchdog_line
  section "Local"
  if ! command -v docker >/dev/null; then info "Local: Docker not installed"; return 0; fi
  if [ -z "$DEVICE" ]; then
    case "$HW_CLASS" in gb300) DEVICE=fury ;; discrete|grace) DEVICE=generic ;; *) DEVICE=nano ;; esac
  fi
  deploy_tool
  local json kind text
  json=$("${DEPLOY[@]}" status 2>/dev/null) || { info "Local: no deployment status (Docker not usable?)"; return 0; }
  while IFS=$'\t' read -r kind text; do
    case "$kind" in ok) ok "$text" ;; note) note "$text" ;; *) info "$text" ;; esac
  done < <(python3 - "$json" "$(git -C "$ROOT" rev-parse HEAD 2>/dev/null)" "${served:+$ZRT_URL}" <<'PY'
import json, sys
s, head, zrt = json.loads(sys.argv[1]), sys.argv[2], sys.argv[3]
cur = s.get("current") or {}
cons = s.get("containers") or {}
if not cur and not any(cons.values()):
    print("info\tLocal: not deployed"); sys.exit()
state = ", ".join(f"{c['name']} {c['status']}" for c in cons.values() if c) or "no containers"
ready = (s.get("readiness") or {}).get("readiness") or "no answer"
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
}

stop_local() {
  # #590: each container's removal is checked; only those really removed are reported as stopped, and one that is
  # still there makes stop fail with its name.
  local role found=0 stopped=() failed=()
  refuse_foreign
  for role in api web; do
    docker container inspect "$INSTANCE-$role" >/dev/null 2>&1 || continue
    found=1
    if [ "$DRY" = 1 ]; then cmdline "docker rm -f $INSTANCE-$role"
    elif docker rm -f "$INSTANCE-$role" >/dev/null; then stopped+=("$INSTANCE-$role")
    else failed+=("$INSTANCE-$role"); fi
  done
  if [ "$found" = 0 ]; then info "No $INSTANCE containers"; return 0; fi
  if [ "$DRY" = 1 ]; then note "Dry run: nothing was stopped."; return 0; fi
  [ ${#stopped[@]} = 0 ] || ok "Stopped $(and_list "${stopped[@]}") (data kept in $DATA_ROOT)"
  [ ${#failed[@]} = 0 ] || fail "Could not stop $(and_list "${failed[@]}"): Docker did not remove it (see its message above)" \
    "Check Docker (docker ps; docker rm -f ${failed[*]}), then run ./demo.sh stop local again"
}
and_list() { if [ $# -le 1 ]; then echo "${1:-}"; else echo "${*:1:$#-1} and ${*: -1}"; fi; }

cmd_stop() {
  local img
  header "stop" dry
  section "Stop"
  case "$ARG" in
    mock) if mock_running; then stop_mock; else info "Mock is not running"; fi ;;
    local) stop_local ;;
    "")
      if mock_running; then stop_mock
      elif ! command -v docker >/dev/null; then info "Nothing of yours runs"
      elif img=$(foreign_image); then
        info "Nothing of yours runs ($INSTANCE-api and $INSTANCE-web are $(foreign_what); demo.sh leaves them alone)"
      else stop_local; fi ;;
    *) fail "Unknown stop target: $ARG" "Use ./demo.sh stop, ./demo.sh stop mock or ./demo.sh stop local" ;;
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
    *) fail "Could not remove $what: $(tail -n1 <<< "$out")" "Fix that, then rerun ./demo.sh uninstall$([ "$ALL" = 0 ] || echo ' --all')" ;;
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
  local d rev want devices=(nano fury)
  want=$(env_value AWARECARE_MODEL_REVISION)
  [ -z "$M_HF" ] || devices=(generic)
  for d in "${devices[@]}"; do
    [ -z "$DEVICE" ] || [ "$DEVICE" = "$d" ] || continue
    rev=$(local_copy "$d" "$want")
    [ -z "$rev" ] || echo "$d hf:$(device_repo "$d")@$rev"
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
  item "$c ($2)" act rm -rf -- "$c"
}
own_data_root() {  # #557: a data root an Aware Care deployment created (its lock, state or presenter key)
  [ -e "$1/deploy.lock" ] || [ -d "$1/state" ] || [ -e "$1/secrets/presenter.key" ]
}
uninstall_items() {
  local role ref d names=() refs=() unit_file="$HOME/.config/systemd/user/$UNIT" serve="$DEFAULT_DATA_ROOT/zrt" line
  # #564: mock mode belongs to the default instance; uninstalling a second instance leaves it alone
  if [ "$DATA_ROOT" = "$DEFAULT_DATA_ROOT" ] && mock_running; then item "the mock development servers" stop_mock quiet; fi
  if command -v docker >/dev/null; then
    for role in api web; do
      if docker container inspect "$INSTANCE-$role" >/dev/null 2>&1; then names+=("$INSTANCE-$role"); fi
    done
    [ ${#names[@]} = 0 ] || item "the containers ${names[*]}" act docker rm -f "${names[@]}"
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

tilde() { case $1 in "$HOME"/*) printf '%s/%s\n' "~" "${1#"$HOME"/}" ;; *) echo "$1" ;; esac; }
# refuse_all_beside_workflow (#602): --all removes, for every instance on this machine, what uninstall_items removes
# only with ALL=1; a workflow deployment of the default instance uses it, so --all is refused there.
refuse_all_beside_workflow() {
  local img shared
  # #636: only a running one; a release whose containers were removed is only a record in its data root
  docker container inspect "$DEFAULT_INSTANCE-api" >/dev/null 2>&1 || return 0
  img=$(foreign_image "$DEFAULT_INSTANCE" "$DEFAULT_DATA_ROOT") || return 0
  shared="the model unit $UNIT (it stops the model) and its watchdog $WD_TIMER, the model's serve script $(tilde "$DEFAULT_DATA_ROOT/zrt"),"
  shared+=" the model's settings $(tilde "$(dirname "$MODEL_ENV")"), the images aware-care-api:local and"
  shared+=" aware-care-web:local, and demo.sh's logs and check-model reports ($(tilde "$LOG_DIR"))"
  [ "$WITH_MODEL" = 0 ] || shared+=", and with --with-model the downloaded model in ZRT's cache"
  fail "uninstall --all is refused: --all also removes what every instance on this machine shares, and the live deployment $DEFAULT_INSTANCE uses it" \
    "$(if [ "$INSTANCE" = "$DEFAULT_INSTANCE" ]; then echo "To remove only your own instance: ./demo.sh uninstall --instance <name>"
       else echo "To remove only $INSTANCE: ./demo.sh uninstall --instance $INSTANCE"; fi)" \
    "To remove everything: stop the live deployment $DEFAULT_INSTANCE first, then rerun ./demo.sh uninstall --all." \
    "  A release (maintainers only): docker rm -f $DEFAULT_INSTANCE-api $DEFAULT_INSTANCE-web; its deploy workflow puts it back later" \
    "  Another account's instance: that account runs ./demo.sh stop" \
    "What --all removes for every instance: $shared" \
    "The live deployment: $DEFAULT_INSTANCE-api and $DEFAULT_INSTANCE-web run $img ($(foreign_what "$DEFAULT_INSTANCE" "$DEFAULT_DATA_ROOT"))"
}

cmd_uninstall() {
  header "uninstall$([ "$ALL" = 0 ] || echo ' --all')" dry
  local root
  root=$(safe_dir "$DATA_ROOT") || fail "Refusing to delete the data root $DATA_ROOT: it is $PROTECTED_WHY" \
    "Set AWARECARE_DEMO_DATA_ROOT to the app's own directory."
  # #589: from here on every comparison and the ownership check (own_data_root) see the canonical paths
  DATA_ROOT=$root
  DEFAULT_DATA_ROOT=$(canon "$DEFAULT_DATA_ROOT")
  if command -v docker >/dev/null; then
    # --all also removes what every instance on this machine shares (uninstall_items): never beside a workflow
    # deployment, which uses it. #602: the refusal says why and what to do instead; #617: also for the default
    # instance, so this check comes first.
    [ "$ALL" = 0 ] || refuse_all_beside_workflow
    refuse_foreign
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
  elif [ "$DRY" = 1 ]; then note "Dry run: nothing was removed."
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
  if [ "$ALL" = 0 ]; then next_steps "Everything demo.sh added (logs, settings, the model's serve script): ./demo.sh uninstall --all"; return 0; fi
  section "What stays"
  local kept="" images  # #636: only what exists (a fresh clone has neither)
  [ ! -d "$ROOT/apps/api/.venv" ] || kept="apps/api/.venv"
  [ ! -d "$ROOT/apps/web/node_modules" ] || kept+="${kept:+ and }apps/web/node_modules"
  info "This checkout, $ROOT${kept:+ (with $kept)}. Delete it:"
  cmdline "cd ~ && rm -rf $(quote "$ROOT")"
  info "Docker and its build cache (docker builder prune, if nothing else on this machine needs it), and ZRT"
  # #636: the release images a deploy workflow pulled (only on the maintainer's devices)
  images=$(docker images -q "ghcr.io/your-github-user/aware-care/*" 2>/dev/null | sort -u | paste -sd' ' -)
  if [ -n "$images" ]; then
    info "The release images the deploy workflow pulled ($(wc -w <<< "$images")); remove them: docker image rm $images"
  fi
  if [ "$WITH_MODEL" = 0 ]; then
    info "The downloaded model in ZRT's cache (remove it too: ./demo.sh uninstall --all --with-model)"
  fi
  info "uv and Node, if you installed them for mock mode"
}

cmd_update() {
  header "update" dry
  section "Update"
  if dirty; then
    fail "The checkout has local changes, so it cannot switch versions" \
      "See them: git -C $ROOT status" "Commit them on a branch, or discard them (git checkout -- <file>), then rerun ./demo.sh update"
  fi
  local mode=""
  if mock_running; then mode=mock
  elif command -v docker >/dev/null && local_running && ! foreign_image >/dev/null; then mode=local; fi
  if [ "$DRY" = 1 ]; then
    cmdline "git -C $ROOT fetch --tags --quiet origin"
  else
    git -C "$ROOT" fetch --tags --quiet origin || fail "git fetch failed" \
      "Check the network (and the proxy: see ./demo.sh local) and that the clone's origin still points to the" \
      "repository (git -C $ROOT remote -v)."
  fi
  local target=${ARG:-}
  [ -n "$target" ] || target=$(git -C "$ROOT" tag -l 'v*' --sort=-v:refname | head -n1)
  [ -n "$target" ] || fail "No release tag (v*) found" "Name one: ./demo.sh update <tag>"
  local want
  if ! want=$(git -C "$ROOT" rev-parse -q --verify "refs/tags/$target^{commit}" 2>/dev/null); then
    [ "$DRY" = 0 ] || { note "Dry run: $target is not fetched yet; the fetch above would bring it if it exists."; return 0; }
    fail "No tag named $target" "List them: git -C $ROOT tag -l 'v*' --sort=-v:refname"
  fi
  # A release older than demo.sh (before v0.16.1-demo.1) has no demo.sh: refuse it before the checkout, or the next
  # ./demo.sh would be "No such file or directory".
  git -C "$ROOT" cat-file -e "$want:demo.sh" 2>/dev/null || fail "$target is older than demo.sh (it has no demo.sh), so demo.sh does not switch to it" \
    "Choose a newer release: git -C $ROOT tag -l 'v*' --sort=-v:refname" \
    "(to run an older one anyway, follow its README: git -C $ROOT checkout $target; back with git -C $ROOT checkout -)"
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
    note "Dry run: nothing was fetched, checked out or restarted."
    return 0
  fi
  git -C "$ROOT" -c advice.detachedHead=false checkout --quiet "$want" \
    || fail "git checkout of $target failed" "git -C $ROOT status shows why"
  [ "$(git -C "$ROOT" rev-parse HEAD)" = "$want" ] || fail "The checkout is not at $target after git checkout" \
    "git -C $ROOT status; git -C $ROOT log -1"
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
    "Run it without sudo. Docker must work for your user without sudo: once, an administrator runs" \
    "  sudo usermod -aG docker <user>   (then log out and back in; see docs/wiki/Requirements.md)"
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
  "") help; exit 2 ;;
  *) echo "demo.sh: unknown command $CMD (see ./demo.sh --help)" >&2; exit 2 ;;
esac
