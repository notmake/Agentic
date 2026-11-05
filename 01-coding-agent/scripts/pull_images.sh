#!/usr/bin/env bash
# 预拉 SWE-bench 评测镜像（5.0.2 起 harness 不再自动拉取，预拉是必需步骤）
#
# 用法（开发机）：
#   bash pull_images.sh astropy__astropy-12907 sympy__sympy-20590
#   bash pull_images.sh --lite-batch 3          # 按实例清单前 N 个拉取
#   MIRROR=docker.1panel.live bash pull_images.sh <ids>   # 国内镜像源（daocloud 不放行 swebench）
#
# 命名规则：swebench/sweb.eval.x86_64.{org}_1776_{repo}-{issue}:latest
set -eu

MIRROR="${MIRROR:-}"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker 不可用" >&2
  exit 1
fi

pull_one() {
  local iid="$1"
  local image="swebench/sweb.eval.x86_64.${iid//__/_1776_}:latest"
  local ref="$image"
  [ -n "$MIRROR" ] && ref="$MIRROR/$image"
  echo "==> $iid"
  echo "    pull: $ref"
  if docker image inspect "$image" >/dev/null 2>&1; then
    echo "    已存在，跳过"
    return
  fi
  docker pull "$ref"
  if [ "$ref" != "$image" ]; then
    docker tag "$ref" "$image"
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
