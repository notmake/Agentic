#!/usr/bin/env bash
# 带重试的 gold 镜像拉取（国内镜像偶发 connection reset；docker pull 会复用已下载层）
set -u

MIRROR="${MIRROR:-docker.1panel.live}"
IDS=(
  astropy__astropy-12907
  django__django-10914
  matplotlib__matplotlib-18869
)

for iid in "${IDS[@]}"; do
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
docker images --format '{{.Repository}}:{{.Tag}} {{.Size}}' | grep swebench || true
