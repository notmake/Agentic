#!/usr/bin/env bash
# A800 上启动 vLLM（裸跑，不依赖 Docker）
#
# 用法（A800 上）：
#   MODEL_PATH=/path/to/Qwen3.8-27B-Q4_K_M.gguf bash serve_a800.sh
#   MODEL_PATH=/path/to/Qwen3-Coder-30B-A3B-Instruct bash serve_a800.sh   # 决策门通过后
#
# 注意：
#   - GGUF 加载：vLLM 直接 --model 指向 .gguf 文件；若 tokenizer 缺失需加 --tokenizer
#   - 27B 是思考模型：--reasoning-parser qwen3 + 客户端 strip_think 双保险
#   - 工具调用：--enable-auto-tool-choice --tool-call-parser hermes（Qwen 系）
#     若实测 hermes 不认，回退 text 协议（客户端已支持，不改服务端参数）
#   - Ampere 无原生 FP8；本机跑 GGUF Q4_K_M，--kv-cache-dtype 保持 auto
set -eu

MODEL_PATH="${MODEL_PATH:?请用 MODEL_PATH 指定权重路径（.gguf 或 HF 目录）}"
PORT="${PORT:-8000}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-32768}"
GPU_MEM_UTIL="${GPU_MEM_UTIL:-0.90}"
TP="${TP:-1}"
SERVED_NAME="${SERVED_NAME:-$(basename "$MODEL_PATH")}"
LOG="${LOG:-$HOME/vllm_a800_\${PORT}.log}"

echo "== 启动 vLLM：$MODEL_PATH -> :$PORT (max_len=$MAX_MODEL_LEN) =="
echo "== 日志：$LOG =="

# 前台运行便于排障；常驻用 tmux：tmux new -s vllm 'bash serve_a800.sh'
exec python3 -m vllm.entrypoints.openai.api_server \
  --model "$MODEL_PATH" \
  --served-model-name "$SERVED_NAME" \
  --host 0.0.0.0 --port "$PORT" \
  --tensor-parallel-size "$TP" \
  --max-model-len "$MAX_MODEL_LEN" \
  --gpu-memory-utilization "$GPU_MEM_UTIL" \
  --enable-auto-tool-choice \
  --tool-call-parser hermes \
  --reasoning-parser qwen3 \
  --enable-prefix-caching \
  2>&1 | tee "$LOG"
