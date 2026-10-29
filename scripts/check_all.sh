#!/usr/bin/env bash
# check_all.sh: every local pre-PR check in one command (#368), in CI order, with a summary table.
#
#   scripts/check_all.sh            the same as --changed: the pre-PR default (#509)
#   scripts/check_all.sh --changed  web type-check, contrast, contracts, backend, and only the browser specs related to
#                the files changed against origin/main (scripts/changed_ui_specs.py: the whole suite when shared
#                infrastructure changed, none when no web file or spec changed); CI runs the full suite
#   scripts/check_all.sh --standard web type-check, contrast, tooling tests, traceability, contracts, Wiki lint, backend
#   scripts/check_all.sh --fast     --standard without the backend suite (and without the browser suite)
#   scripts/check_all.sh --full     --standard plus the whole browser suite (Playwright)
#   --base REF   the base for --changed (default origin/main)
#   --dry-run    print the plan and exit
#   --verbose    stream each check's output instead of showing the tail of a failing one
#   --repo DIR   the worktree to check (default: the one holding this script)
#
# Every check runs even after a failure; the exit status is non-zero when any check failed.
# The browser suite honours AWARECARE_PW_LOCK: when set, it runs under `flock` on that file, so two worktrees on one
# host never run Playwright on the same ports at once. Dependencies are never installed here (no `npm ci`): a missing
# apps/web/node_modules fails the web checks with a hint instead.
set -u

usage() { sed -n '2,/^set -u/p' "$0" | grep '^#' | sed 's/^# \{0,1\}//'; }

MODE=changed; SET=0; DRY=0; VERBOSE=0; BASE=origin/main
REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
while [ $# -gt 0 ]; do
  case "$1" in
    --fast|--full|--changed|--standard)
      m=${1#--}
      [ "$SET" = 1 ] && [ "$MODE" != "$m" ] && { echo "check_all: --$MODE and --$m exclude each other" >&2; exit 2; }
      MODE=$m; SET=1 ;;
    --base) [ $# -ge 2 ] || { echo "check_all: --base needs a ref" >&2; exit 2; }; BASE=$2; shift ;;
    --dry-run) DRY=1 ;;
    --verbose) VERBOSE=1 ;;
    --repo) [ $# -ge 2 ] || { echo "check_all: --repo needs a directory" >&2; exit 2; }; REPO=$2; shift ;;
    --repo=*) REPO=${1#--repo=} ;;
    -h|--help) usage; exit 0 ;;
    *) echo "check_all: unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done
if [ ! -d "$REPO/spec" ] || [ ! -d "$REPO/scripts" ]; then echo "check_all: $REPO is not an Aware Care worktree" >&2; exit 2; fi
REPO=$(cd "$REPO" && pwd)

PW="NODE_PATH=\$PWD/node_modules npx playwright test"
[ -n "${AWARECARE_PW_LOCK:-}" ] && PW="flock \"\$AWARECARE_PW_LOCK\" env NODE_PATH=\$PWD/node_modules npx playwright test"

# name | directory | command
TSC="Web type-check|apps/web|npx tsc --noEmit -p ."
CONTRAST="Design contrast|.|python3 scripts/check_contrast.py"
CONTRACTS="Contracts|.|uv run --no-project --with jsonschema==4.25.1 python scripts/check_contracts.py"
BACKEND="Backend (mock and local)|apps/api|uv run pytest -q"
BROWSER_NOTE=""
if [ "$MODE" = changed ]; then
  STEPS=("$TSC" "$CONTRAST" "$CONTRACTS" "$BACKEND")
  if ! specs=$(python3 "$REPO/scripts/changed_ui_specs.py" --base "$BASE"); then
    echo "check_all: could not work out the changed files against $BASE" >&2; exit 2
  fi
  if [ "$specs" = ALL ]; then
    STEPS+=("Browser UI (all: shared files changed)|apps/web|$PW"); BROWSER_NOTE=all
  elif [ -n "$specs" ]; then
    STEPS+=("Browser UI ($(wc -l <<<"$specs" | tr -d ' ') related specs)|apps/web|$PW $(tr '\n' ' ' <<<"$specs")")
    BROWSER_NOTE=some
  fi
else
  STEPS=(
    "$TSC" "$CONTRAST"
    "Tooling tests|.|python3 -m unittest discover -s tests/tooling"
    "Traceability|.|python3 scripts/check_traceability.py"
    "$CONTRACTS"
    "Wiki lint|.|python3 scripts/publish_wiki.py lint"
  )
  [ "$MODE" != fast ] && STEPS+=("$BACKEND")
  [ "$MODE" = full ] && STEPS+=("Browser UI|apps/web|$PW")
fi

if [ "$DRY" = 1 ]; then
  echo "check_all plan ($MODE, repo $REPO):"
  i=0
  for s in "${STEPS[@]}"; do
    i=$((i + 1)); IFS='|' read -r name dir cmd <<<"$s"
    printf '  %d. %-26s (cd %s && %s)\n' "$i" "$name" "$dir" "$cmd"
  done
  [ "$MODE" = fast ] && echo "  skipped: Backend (mock and local), Browser UI (--fast)"
  [ "$MODE" = standard ] && echo "  skipped: Browser UI (use --full)"
  [ "$MODE" = changed ] && [ -z "$BROWSER_NOTE" ] && echo "  skipped: Browser UI (no web file or spec changed against $BASE)"
  exit 0
fi

LOGS=$(mktemp -d "${TMPDIR:-/tmp}/check_all.XXXXXX")
RESULTS=(); FAILED=0; i=0
for s in "${STEPS[@]}"; do
  i=$((i + 1)); IFS='|' read -r name dir cmd <<<"$s"
  log="$LOGS/$i.log"
  echo "==> [$i/${#STEPS[@]}] $name: (cd $dir && $cmd)"
  start=$(date +%s)
  if [ "$dir" = apps/web ] && [ ! -d "$REPO/apps/web/node_modules" ]; then
    echo "apps/web/node_modules is missing; install the web dependencies yourself (this script never runs npm ci)" >"$log"
    rc=127
  elif [ "$VERBOSE" = 1 ]; then
    (cd "$REPO/$dir" && bash -c "$cmd") 2>&1 | tee "$log"; rc=${PIPESTATUS[0]}
  else
    (cd "$REPO/$dir" && bash -c "$cmd") >"$log" 2>&1; rc=$?
  fi
  secs=$(( $(date +%s) - start ))
  if [ "$rc" -eq 0 ]; then status=PASS; else status="FAIL ($rc)"; FAILED=$((FAILED + 1))
    [ "$VERBOSE" = 1 ] || { tail -n 20 "$log" | sed 's/^/    /'; }
  fi
  RESULTS+=("$name|$status|$secs")
done

echo
echo "| # | Check | Result | Seconds |"
echo "|---|---|---|---|"
i=0
for r in "${RESULTS[@]}"; do
  i=$((i + 1)); IFS='|' read -r name status secs <<<"$r"
  echo "| $i | $name | $status | $secs |"
done
[ "$MODE" = fast ] && echo "| - | Backend (mock and local) | skipped (--fast) | - |"
{ [ "$MODE" = fast ] || [ "$MODE" = standard ]; } && echo "| - | Browser UI | skipped (use --full) | - |"
[ "$MODE" = changed ] && [ -z "$BROWSER_NOTE" ] && echo "| - | Browser UI | skipped (no related spec) | - |"
echo
echo "Logs: $LOGS"
if [ "$FAILED" -gt 0 ]; then
  echo "check_all: $FAILED of ${#STEPS[@]} checks FAILED"
  exit 1
fi
echo "check_all: all ${#STEPS[@]} checks passed ($MODE)"
