#!/usr/bin/env bash
# 带重试的实例镜像拉取（国内镜像偶发 connection reset；docker pull 会复用已下载层）
#
# 用法：
#   MIRROR=docker.1panel.live bash scripts/pull_gold_retry.sh            # 读 lite_instance_ids.txt
#   MIRROR=docker.1panel.live bash scripts/pull_gold_retry.sh --limit 10
#   bash scripts/pull_gold_retry.sh astropy__astropy-12907 ...           # 指定实例
set -u

MIRROR="${MIRROR:-docker.1panel.live}"
LIMIT=""
if [ "${1:-}" = "--limit" ]; then LIMIT="${2:-}"; shift 2; fi

if [ "$#" -gt 0 ]; then
  IDS=("$@")
else
  IDS_FILE="$(dirname "$0")/../data/datasets/lite_instance_ids.txt"
  [ -f "$IDS_FILE" ] || { echo "缺少 $IDS_FILE" >&2; exit 1; }
  mapfile -t IDS < <( [ -n "$LIMIT" ] && head -n "$LIMIT" "$IDS_FILE" || cat "$IDS_FILE" )
fi

for iid in "${IDS[@]}"; do
  [ -z "$iid" ] && continue
  image="swebench/sweb.eval.x86_64.${iid//__/_1776_}:latest"
  if docker image inspect "$image" >/dev/null 2>&1; then
    echo "== $iid 已存在，跳过"
    continue
  fi
  echo "== $iid"
  ok=0
  for attempt in $(seq 1 12); do
    echo "-- attempt $attempt: $MIRROR/$image"
    if docker pull "$MIRROR/$image"; then
      docker tag "$MIRROR/$image" "$image"
      ok=1
      break
    fi
    sleep 8
  done
  [ "$ok" = 1 ] && echo "== $iid OK" || echo "== $iid FAILED"
done
echo "== 全部结束"
docker images --format '{{.Repository}}:{{.Tag}} {{.Size}}' | grep '^swebench' || true
