#!/usr/bin/env bash
# Build the Aware Care API and web images (M12; R34, R37, R40).
# Used by .github/workflows/release.yml (linux/arm64, --push) and by the CI
# package smoke test (runner-native platform, --load). Run from the repository root.
#
#   infra/deploy/build_images.sh --platform linux/arm64 --commit <40-hex> \
#       --api-ref <image:tag> --web-ref <image:tag> --metadata-dir <dir> (--push | --load)
#
# With --push, <metadata-dir>/{api,web}.json hold buildx metadata including
# "containerimage.digest", the immutable digest deployments pin.
set -euo pipefail

platform="" commit="" api_ref="" web_ref="" metadata_dir="" output=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --platform) platform="$2"; shift 2 ;;
    --commit) commit="$2"; shift 2 ;;
    --api-ref) api_ref="$2"; shift 2 ;;
    --web-ref) web_ref="$2"; shift 2 ;;
    --metadata-dir) metadata_dir="$2"; shift 2 ;;
    --push) output="--push"; shift ;;
    --load) output="--load"; shift ;;
    *) echo "build_images.sh: unknown argument $1" >&2; exit 2 ;;
  esac
done
for required in platform commit api_ref web_ref metadata_dir output; do
  if [[ -z "${!required}" ]]; then echo "build_images.sh: --${required//_/-} is required" >&2; exit 2; fi
done
if [[ ! "$commit" =~ ^[0-9a-f]{40}$ ]]; then echo "build_images.sh: --commit must be a full 40-hex SHA" >&2; exit 2; fi
if [[ ! -f infra/deploy/api.Dockerfile ]]; then echo "build_images.sh: run from the repository root" >&2; exit 2; fi
mkdir -p "$metadata_dir"

# #535, #549: the same buildx demo.sh checked (infra/deploy/find_buildx.sh): the Docker CLI plugin (`docker buildx`),
# the standalone program (`docker-buildx`, as on an HP Z8), the plugin binary run directly (a conda shell's docker CLI
# does not find it) or `docker docker-buildx`; all take the same subcommands.
# shellcheck source=infra/deploy/find_buildx.sh
. "$(dirname "${BASH_SOURCE[0]}")/find_buildx.sh"
if ! find_buildx; then
  echo "build_images.sh: docker buildx is missing: install the Docker buildx plugin (docker buildx version) or the" \
    "standalone docker-buildx program (docker-buildx version). Tried: $BUILDX_TRIED" >&2
  exit 2
fi
buildx=("${BUILDX[@]}")
echo "build_images.sh: using ${buildx[*]} ($BUILDX_VERSION)"

# Forward an outbound proxy to RUN steps (npm ci, uv sync) when the builder host
# needs one. These are BuildKit's predefined proxy args: they are not written to
# the image config or history. Base images and registry pushes still use the
# Docker daemon's own proxy configuration.
proxy_args=()
for name in HTTP_PROXY HTTPS_PROXY NO_PROXY http_proxy https_proxy no_proxy; do
  if [[ -n "${!name:-}" ]]; then proxy_args+=(--build-arg "$name"); fi
done
# Optional base-image overrides (e.g. PYTHON_IMAGE=...) for builders that load the
# pinned base images out of band; the Dockerfile defaults are the pinned digests.
base_args=()
for name in PYTHON_IMAGE UV_IMAGE NODE_IMAGE NGINX_IMAGE; do
  if [[ -n "${!name:-}" ]]; then base_args+=(--build-arg "$name"); fi
done

for role in api web; do
  if [[ "$role" == api ]]; then ref="$api_ref"; else ref="$web_ref"; fi
  echo "::group::build ${role} (${platform})"
  "${buildx[@]}" build \
    --platform "$platform" \
    --file "infra/deploy/${role}.Dockerfile" \
    --build-arg "APP_COMMIT=${commit}" \
    "${proxy_args[@]}" \
    "${base_args[@]}" \
    --label "org.opencontainers.image.revision=${commit}" \
    --tag "$ref" \
    --metadata-file "${metadata_dir}/${role}.json" \
    "$output" \
    .
  echo "::endgroup::"
done
