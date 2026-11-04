#!/usr/bin/env bash
# 预拉 SWE-bench 评测镜像（5.0.2 起 harness 不再自动拉取，预拉是必需步骤）
#
# 用法（开发机）：
#   bash pull_images.sh astropy__astropy-12907 sympy__sympy-20590 pytest-dev__pytest-7432
#   bash pull_images.sh --lite-batch 3     # 按 Lite 实例清单前 N 个拉取（需先跑 eval/prepare.py）
#
# 命名规则：swebench/sweb.eval.x86_64.{org}_1776_{repo}-{issue}:latest
#   （数据集里的 __ 在镜像名里变成 _1776_，Docker Hub 不允许双下划线）
set -eu

if ! command -v docker >/dev/null 2>&1; then
  echo "docker 不可用（W0 已知：当前用户不在 docker 组，需 sudo 或加入 docker 组后重登）" >&2
  exit 1
fi

pull_one() {
  local iid="$1"
  local image="swebench/sweb.eval.x86_64.${iid//__/_1776_}:latest"
  echo "==> $iid -> $image"
  if docker image inspect "$image" >/dev/null 2>&1; then
    echo "    已存在，跳过"
  else
    docker pull "$image"
  fi
}

if [ "${1:-}" = "--lite-batch" ]; then
  N="${2:-3}"
  LIST_FILE="$(dirname "$0")/../data/datasets/lite_instance_ids.txt"
  [ -f "$LIST_FILE" ] || { echo "缺少 $LIST_FILE，先跑 eval/prepare.py" >&2; exit 1; }
  head -n "$N" "$LIST_FILE" | while read -r iid; do
    [ -n "$iid" ] && pull_one "$iid"
  done
else
  for iid in "$@"; do pull_one "$iid"; done
fi
