#!/usr/bin/env bash
# 边拉边跑：按实例清单顺序，等镜像就绪 → 导出 testbed → OpenHands 跑 → 下一个
# 用法（在 sg docker 下执行）：
#   sg docker -c 'bash scripts/run_pilot_when_ready.sh 10 pilot-10'
set -u

LIMIT="${1:-10}"
RUN_ID="${2:-pilot-10}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export PATH="$HOME/venvs/openhands/bin:$PATH"
export LLM_MODEL="${LLM_MODEL:-openai/Qwen3.8-27B}"
export LLM_BASE_URL="${LLM_BASE_URL:-http://127.0.0.1:6790/v1}"
export LLM_API_KEY="${LLM_API_KEY:-local}"

IDS_FILE="${ORDER_FILE:-$ROOT/data/datasets/lite_instance_ids.txt}"
DATASET="${DATASET:-$ROOT/data/datasets/lite.jsonl}"
RUN_DIR="$ROOT/data/runs/openhands-batch/$RUN_ID"
mkdir -p "$RUN_DIR"

mapfile -t IDS < <(head -n "$LIMIT" "$IDS_FILE")

for iid in "${IDS[@]}"; do
  [ -z "$iid" ] && continue
  image="swebench/sweb.eval.x86_64.${iid//__/_1776_}:latest"
  echo "=== $iid ==="
  if [ -f "$RUN_DIR/$iid/prediction.jsonl" ]; then
    echo "已存在，跳过"
    continue
  fi
  echo "等待镜像 $image ..."
  waited=0
  until docker image inspect "$image" >/dev/null 2>&1; do
    sleep 30; waited=$((waited + 30))
    if [ "$waited" -ge "${MAX_IMAGE_WAIT:-600}" ]; then
      echo "镜像未就绪（等待 ${waited}s），跳过 $iid"
      continue 2
    fi
  done

  # 保护 1：显存被其他任务占用时等待（27B 自身约 19G，上限设 21.5G）
  while true; do
    used=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null | sort -n | tail -1)
    [ -z "$used" ] && break
    if [ "$used" -lt 21500 ]; then break; fi
    echo "显存占用 ${used}MiB（可能有其他任务），等待释放..."
    sleep 60
  done

  # 保护 2：27B 服务挂了自动重启
  if ! curl -s --max-time 3 http://127.0.0.1:6790/v1/models 2>/dev/null | grep -q '"models"'; then
    echo "27B 服务不可用，自动重启..."
    setsid nohup bash "$ROOT/openhands/serve_llama.sh" > /tmp/llama_server_auto.log 2>&1 < /dev/null &
    for _ in $(seq 1 40); do
      sleep 5
      curl -s --max-time 2 http://127.0.0.1:6790/v1/models 2>/dev/null | grep -q '"models"' && break
    done
  fi
  python3 -m openhands.run_instance \
    --dataset "$DATASET" \
    --instance-id "$iid" --from-image \
    --output-dir "$RUN_DIR/$iid" > "$RUN_DIR/$iid.log" 2>&1
  echo "完成 $iid（exit=$?）"
done

# 合并 predictions
: > "$RUN_DIR/predictions.jsonl"
for iid in "${IDS[@]}"; do
  p="$RUN_DIR/$iid/prediction.jsonl"
  [ -f "$p" ] && cat "$p" >> "$RUN_DIR/predictions.jsonl"
done
echo "=== pilot 全部结束：$RUN_DIR/predictions.jsonl ==="
