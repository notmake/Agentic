#!/usr/bin/env bash
# 本机 llama-server（C++ llama.cpp，支持 --jinja 原生工具调用）
#
# 前置：
#   1. 编译 llama.cpp（官方源）：cmake -B build -DGGML_CUDA=ON \
#        -DCMAKE_CUDA_ARCHITECTURES=86 -DCMAKE_C_COMPILER=/usr/bin/gcc-12 \
#        -DCMAKE_CXX_COMPILER=/usr/bin/g++-12 -DCMAKE_CUDA_HOST_COMPILER=/usr/bin/g++-12
#      cmake --build build -j 16 --target llama-server
#   2. 停掉旧的 llama_cpp.server（端口 6790），否则显存冲突
#
# 用法：
#   bash openhands/serve_llama.sh
#   MODEL_PATH=... CTX=32768 PORT=6790 bash openhands/serve_llama.sh
set -eu

LLAMA_SERVER="${LLAMA_SERVER:-/home/wit627/tools/llama.cpp/build/bin/llama-server}"
MODEL_PATH="${MODEL_PATH:-/home/wit627/project/models/Qwen3.8-27B-Q4_K_M.gguf}"
ALIAS="${ALIAS:-Qwen3.8-27B}"
PORT="${PORT:-6790}"
# 2026-11-06 显存事故后调稳：16K + 单槽 + 量化 KV。
# 32K + n_slots=4 时长 prompt 触发 CUDA OOM/Xid 154（双卡掉线，需重启）。
CTX="${CTX:-16384}"
NGL="${NGL:-99}"
SPLIT_MODE="${SPLIT_MODE:-layer}"
PARALLEL="${PARALLEL:-1}"
KV_TYPE="${KV_TYPE:-q8_0}"

if [ ! -x "$LLAMA_SERVER" ]; then
  echo "找不到 llama-server：$LLAMA_SERVER（先编译 llama.cpp）" >&2
  exit 1
fi

echo "== llama-server: $MODEL_PATH -> :$PORT (ctx=$CTX, alias=$ALIAS) =="
exec "$LLAMA_SERVER" \
  --model "$MODEL_PATH" \
  --alias "$ALIAS" \
  --host 0.0.0.0 --port "$PORT" \
  --ctx-size "$CTX" \
  --parallel "$PARALLEL" \
  --n-gpu-layers "$NGL" \
  --split-mode "$SPLIT_MODE" \
  --flash-attn on \
  --cache-type-k "$KV_TYPE" \
  --cache-type-v "$KV_TYPE" \
  --jinja \
  --no-webui
