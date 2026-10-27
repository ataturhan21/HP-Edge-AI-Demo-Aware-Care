# find_buildx.sh: sourced by demo.sh and build_images.sh, so both use the same buildx (#535, #549). Bash only.
# shellcheck shell=bash
#
# find_buildx sets BUILDX (the command, an array: append `build ...`), BUILDX_HOW (which form, for messages) and
# BUILDX_VERSION (its first version line), or returns 1 with BUILDX_TRIED (what it tried). In order:
#   1. docker buildx version                 the Docker CLI plugin, as Docker finds it
#   2. docker-buildx version                 the standalone program on PATH (as on an HP Z8)
#   3. <dir>/docker-buildx version           the plugin binary itself, run directly, from ~/.docker/cli-plugins,
#                                            /usr/local/lib/docker/cli-plugins, /usr/libexec/docker/cli-plugins or
#                                            /usr/lib/docker/cli-plugins: a docker CLI from a conda or virtualenv
#                                            environment does not look there, so `docker buildx` fails (#549)
#   4. docker docker-buildx --version        only when its output names buildx: the system Docker CLI answers this
#                                            with its own version ("Docker version 29.2.1"), which proves nothing
# AWARECARE_DOCKER_PLUGIN_DIRS (colon-separated; tests only) replaces the directories of step 3.
# shellcheck disable=SC2034  # BUILDX_HOW, BUILDX_VERSION and BUILDX_TRIED are for the caller
find_buildx() {
  BUILDX=() BUILDX_HOW="" BUILDX_VERSION="" BUILDX_TRIED=""
  local out="" d dirs
  IFS=: read -r -a dirs <<< "${AWARECARE_DOCKER_PLUGIN_DIRS:-$HOME/.docker/cli-plugins:/usr/local/lib/docker/cli-plugins:/usr/libexec/docker/cli-plugins:/usr/lib/docker/cli-plugins}"
  if out=$(docker buildx version 2>/dev/null); then
    BUILDX=(docker buildx) BUILDX_HOW="docker buildx (Docker CLI plugin)"
  elif command -v docker-buildx >/dev/null 2>&1 && out=$(docker-buildx version 2>/dev/null); then
    BUILDX=(docker-buildx) BUILDX_HOW="docker-buildx (standalone program)"
  else
    for d in "${dirs[@]}"; do
      if [ -x "$d/docker-buildx" ] && out=$("$d/docker-buildx" version 2>/dev/null); then
        BUILDX=("$d/docker-buildx") BUILDX_HOW="$d/docker-buildx (the buildx plugin, run directly)"
        break
      fi
    done
    if [ ${#BUILDX[@]} = 0 ] && out=$(docker docker-buildx --version 2>/dev/null) && grep -qi buildx <<< "$out"; then
      BUILDX=(docker docker-buildx) BUILDX_HOW="docker docker-buildx"
    fi
  fi
  if [ ${#BUILDX[@]} = 0 ]; then
    BUILDX_TRIED="docker buildx version; docker-buildx version; docker-buildx version in ${dirs[*]}; docker docker-buildx --version"
    out=$(docker docker-buildx --version 2>/dev/null | head -n1) || out=""
    [ -z "$out" ] || BUILDX_TRIED+=" (it printed \"$out\", Docker's own version, not buildx's)"
    return 1
  fi
  BUILDX_VERSION=$(head -n1 <<< "$out")
}
