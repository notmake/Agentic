#!/usr/bin/env bash
# 从官方 SWE-bench 镜像导出 /testbed 到宿主机目录（OpenHands 本地 runtime 用）
#
# 为什么不用 git clone：GitHub 直连 ~18KB/s，大仓库要几十分钟；
# 官方镜像里已经有 base_commit 的完整仓库，导出即用。
#
# 用法：
#   bash scripts/export_testbed.sh <image> <dest> [base_commit]
# 例：
#   bash scripts/export_testbed.sh \
#     swebench/sweb.eval.x86_64.astropy_1776_astropy-12907:latest \
#     data/workspaces/astropy__astropy-12907 <base_commit>
#
# 注意：用 tar 流导出（而不是 docker cp），文件属主是当前用户，OpenHands 才能改。
set -eu

IMAGE="${1:?用法: export_testbed.sh <image> <dest> [base_commit]}"
DEST="${2:?缺少目标目录}"
COMMIT="${3:-}"
NAME="sweagent-export-$$"

cleanup() { docker rm -f "$NAME" >/dev/null 2>&1 || true; }
trap cleanup EXIT

echo "== 启动临时容器：$NAME =="
docker run -d --name "$NAME" --entrypoint sleep "$IMAGE" infinity >/dev/null

mkdir -p "$DEST"
echo "== 导出 /testbed -> $DEST =="
docker exec "$NAME" tar -C /testbed -cf - . | tar -C "$DEST" -xf -

if [ -n "$COMMIT" ]; then
  echo "== 对齐 base_commit：$COMMIT =="
  git -C "$DEST" reset --hard "$COMMIT"
  git -C "$DEST" clean -fdq
fi

echo "== 完成 =="
du -sh "$DEST"
