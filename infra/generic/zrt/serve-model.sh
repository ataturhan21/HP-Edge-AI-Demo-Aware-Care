#!/bin/bash
# Serve the catalogue model ./demo.sh chose for this machine through ZRT (#537). Operator asset for any NVIDIA machine
# other than the ZGX Nano and Fury (their qualified scripts are infra/nano/zrt/ and infra/fury/zrt/), started by
# aware-care-zrt-model.service (user unit). It does not change ZRT, CUDA or drivers. It reads:
# - ~/.config/aware-care-demo/model.env (the unit's EnvironmentFile): AWARECARE_MODEL_URI (hf:<repo>@<pinned rev>),
#   AWARECARE_MODEL_LABEL, optionally AWARECARE_MODEL_REVISION (a downloaded copy at another revision),
#   AWARECARE_ZRT_MODE (user or system: zrt -m) and AWARECARE_CUDA_HOME;
# - serve.args next to this script: the catalogue entry's serving flags, one per line (gpu memory fraction,
#   max-model-len, max-num-seqs, tensor parallel, vLLM flags), written by demo.sh from infra/models/catalog.json.
# Like the Fury's script it pins vLLM's own addresses to loopback (#151, #176; tensor parallel opens engine sockets),
# and like both it turns off vLLM's usage statistics (#175) and keeps the Hugging Face hub offline (the model loads from
# ZRT's cache).
set -euo pipefail
export PATH=$PATH:/snap/bin
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# The CUDA toolchain, in order: AWARECARE_CUDA_HOME, the highest installed /usr/local/cuda-<version> with bin/nvcc,
# /usr/local/cuda. `serve-model.sh cuda` prints the choice. AWARECARE_CUDA_ROOT: tests only.
choose_cuda() {
  local root=${AWARECARE_CUDA_ROOT:-/usr/local} d
  if [ -n "${AWARECARE_CUDA_HOME:-}" ]; then
    [ -x "$AWARECARE_CUDA_HOME/bin/nvcc" ] || { echo "serve-model: AWARECARE_CUDA_HOME=$AWARECARE_CUDA_HOME has no bin/nvcc" >&2; return 1; }
    echo "$AWARECARE_CUDA_HOME"; return 0
  fi
  for d in $(printf '%s\n' "$root"/cuda-[0-9]* | sort -rV) "$root/cuda"; do
    if [ -x "$d/bin/nvcc" ]; then echo "$d"; return 0; fi
  done
  echo "serve-model: no CUDA toolchain with bin/nvcc under $root (found: $(echo "$root"/cuda*)); set AWARECARE_CUDA_HOME in ~/.config/aware-care-demo/model.env" >&2
  return 1
}
if [ "${1:-}" = cuda ]; then choose_cuda; exit; fi
export VLLM_HOST_IP=127.0.0.1 GLOO_SOCKET_IFNAME=lo
export VLLM_NO_USAGE_STATS=1 VLLM_DO_NOT_TRACK=1 DO_NOT_TRACK=1 HF_HUB_OFFLINE=1
MODEL=${AWARECARE_MODEL_URI:?serve-model: AWARECARE_MODEL_URI is not set (run ./demo.sh model)}
LABEL=${AWARECARE_MODEL_LABEL:?serve-model: AWARECARE_MODEL_LABEL is not set (run ./demo.sh model)}
[ -z "${AWARECARE_MODEL_REVISION:-}" ] || MODEL=${MODEL%@*}@$AWARECARE_MODEL_REVISION
# #549: ZRT's mode (AWARECARE_ZRT_MODE in model.env: ./demo.sh model writes it when it is not ZRT's default, system;
# unset, the command is the qualified one, as before) and ZRT's address for the "already served" check below:
# AWARECARE_ZRT_URL (model.env), else the port ZRT's proxy is set to (zrt config get proxy.port), else 8080.
ZRT=(zrt)
[ -z "${AWARECARE_ZRT_MODE:-}" ] || ZRT+=(-m "$AWARECARE_ZRT_MODE")
zrt_url() {
  local port
  if [ -n "${AWARECARE_ZRT_URL:-}" ]; then echo "${AWARECARE_ZRT_URL%/}"; return; fi
  port=$("${ZRT[@]}" config get proxy.port 2>/dev/null | tr -d '[:space:]') || port=""
  case "$port" in ''|*[!0-9]*) port=8080 ;; esac
  echo "http://127.0.0.1:$port/v1"
}
if [ "${1:-}" = stop ]; then exec "${ZRT[@]}" service stop "$MODEL"; fi
ARGS=()
if [ -f "$HERE/serve.args" ]; then mapfile -t ARGS < <(grep -v '^[[:space:]]*$' "$HERE/serve.args"); fi
CUDA=$(choose_cuda) || exit 1
echo "serve-model: CUDA $CUDA" >&2
export PATH=$CUDA/bin:$PATH CUDA_HOME=$CUDA
# Already served under any of its names (the label, or ZRT's default: the repository id, any case, any revision)?
REPO=${MODEL#hf:}; REPO=${REPO%@*}
NAMES="(hf:)?($(printf '%s|%s' "$LABEL" "$REPO" | sed 's/[.]/[.]/g'))(@[^\"]*)?"
if curl -sf --noproxy '*' "$(zrt_url)/models" | grep -iqE "\"id\": *\"$NAMES\""; then
  echo "$LABEL is already served"; exit 0
fi
exec "${ZRT[@]}" service start "$MODEL" --label "$LABEL" "${ARGS[@]}"
