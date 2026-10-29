#!/bin/bash
# Serve the Fury's model through ZRT (#142; ADR-018). #646 (ADR-018 amendment, 2026-10-28): the Nano's model,
# Qwen/Qwen3.6-35B-A3B-FP8 at the Nano's pinned revision, with the Nano's serving flags and a GPU memory fraction
# sized for the GB300 (0.20 of its 250.7 GiB, about the 48 GiB the Nano gives it at 0.40).
# Operator asset for the HP ZGX Fury, started by aware-care-zrt-model.service (user unit). It does not change ZRT,
# CUDA or drivers. For this command only, it:
# - puts the installed CUDA 13.2 toolchain first on PATH, because the distribution's /usr/bin/nvcc (CUDA 12.0)
#   cannot build the GB300's sm_103a kernels;
# - pins vLLM's own address to loopback (#151). Without it vLLM uses the default route's source address, and its
#   engine sockets (torch distributed init, tcp://<ip>:<port>) listened on the Fury's external interface.
# - binds the CPU process group (Gloo) to loopback (#176): VLLM_HOST_IP does not cover it, and Gloo takes an address
#   from the hostname, which on the Fury resolves to ::1, <device-host> and the Docker bridge; after one restart its 7
#   listening sockets were on <device-host>;
# - turns off vLLM's usage statistics (#175): unset, vLLM posts a hardware and configuration report to
#   https://stats.vllm.ai at start and every 10 minutes, through the system proxy. The model loads from a local path,
#   so the Hugging Face hub stays offline too.
# The flags are the Nano's qualified ones (infra/nano/zrt/serve-model.sh) except the GPU memory fraction.
set -euo pipefail
export PATH=$PATH:/snap/bin
# #533: the CUDA toolchain, in order: AWARECARE_CUDA_HOME (from ~/.config/aware-care-demo/model.env), the qualified
# /usr/local/cuda, the highest installed /usr/local/cuda-13.* with bin/nvcc, /usr/local/cuda; each needs bin/nvcc.
# A device without the qualified one (a test machine has only cuda-13.0) otherwise crash-looped vLLM silently.
# `serve-model.sh cuda` prints the choice (demo.sh checks it before starting the unit). AWARECARE_CUDA_ROOT: tests only.
CUDA_PREFERRED=cuda
choose_cuda() {
  local root=${AWARECARE_CUDA_ROOT:-/usr/local} d
  if [ -n "${AWARECARE_CUDA_HOME:-}" ]; then
    [ -x "$AWARECARE_CUDA_HOME/bin/nvcc" ] || { echo "serve-model: AWARECARE_CUDA_HOME=$AWARECARE_CUDA_HOME has no bin/nvcc" >&2; return 1; }
    echo "$AWARECARE_CUDA_HOME"; return 0
  fi
  for d in "$root/$CUDA_PREFERRED" $(printf '%s\n' "$root"/cuda-13.* | sort -rV) "$root/cuda"; do
    if [ -x "$d/bin/nvcc" ]; then echo "$d"; return 0; fi
  done
  echo "serve-model: no CUDA toolchain with bin/nvcc under $root (found: $(echo "$root"/cuda*)); set AWARECARE_CUDA_HOME in ~/.config/aware-care-demo/model.env" >&2
  return 1
}
if [ "${1:-}" = cuda ]; then choose_cuda; exit; fi
export VLLM_HOST_IP=127.0.0.1 GLOO_SOCKET_IFNAME=lo
export VLLM_NO_USAGE_STATS=1 VLLM_DO_NOT_TRACK=1 DO_NOT_TRACK=1 HF_HUB_OFFLINE=1
MODEL=hf:Qwen/Qwen3.6-35B-A3B-FP8@95a723d08a9490559dae23d0cff1d9466213d989
LABEL=qwen3.6-35b-a3b-fp8
# #528: AWARECARE_MODEL_REVISION (written by `./demo.sh model` to ~/.config/aware-care-demo/model.env, which the unit
# reads) serves another downloaded revision of the same model, e.g. main, without editing this script; MODEL above
# stays the qualified one. `serve-model.sh stop` stops whichever revision this script serves (the unit's ExecStop).
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
CUDA=$(choose_cuda) || exit 1
echo "serve-model: CUDA $CUDA (qualified: /usr/local/$CUDA_PREFERRED)" >&2
export PATH=$CUDA/bin:$PATH CUDA_HOME=$CUDA
# Already served under any of its names (the label, or ZRT's default: the repository id, any case, any revision)?
REPO=${MODEL#hf:}; REPO=${REPO%@*}
NAMES="(hf:)?($(printf '%s|%s' "$LABEL" "$REPO" | sed 's/[.]/[.]/g'))(@[^\"]*)?"
if curl -sf --noproxy '*' "$(zrt_url)/models" | grep -iqE "\"id\": *\"$NAMES\""; then
  echo "$LABEL is already served"; exit 0
fi
exec "${ZRT[@]}" serve "$MODEL" --label "$LABEL" --gpu-memory-fraction 0.20 \
  --extra '--compilation-config={"inductor_compile_config": {"combo_kernels": false, "benchmark_combo_kernel": false}}' \
  --extra "--max-model-len=16384" --extra "--max-num-seqs=1" --extra "--language-model-only" \
  --extra "--reasoning-parser=qwen3" --extra '--default-chat-template-kwargs={"enable_thinking": false}' \
  --extra '--speculative-config={"method":"mtp","num_speculative_tokens":2}'
