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

IDS_FILE="$ROOT/data/datasets/lite_instance_ids.txt"
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
  until docker image inspect "$image" >/dev/null 2>&1; do sleep 30; done
  python3 -m openhands.run_instance \
    --dataset "$ROOT/data/datasets/lite.jsonl" \
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
