#!/usr/bin/env bash
# SSH 隧道保活：开发机 8001 -> A800 8000（开发机 8000 已被占用）
#
# 用法：
#   A800_HOST=user@10.x.x.x bash tunnel.sh          # 有 autossh 用 autossh
#   A800_HOST=user@10.x.x.x NO_AUTOSSH=1 bash tunnel.sh
#
# 验证：curl http://127.0.0.1:8001/v1/models
set -eu

A800_HOST="${A800_HOST:?请用 A800_HOST=user@ip 指定远程服务器}"
LOCAL_PORT="${LOCAL_PORT:-8001}"
REMOTE_PORT="${REMOTE_PORT:-8000}"

SSH_OPTS="-o ServerAliveInterval=30 -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes"

if command -v autossh >/dev/null 2>&1 && [ "${NO_AUTOSSH:-0}" != "1" ]; then
  echo "autossh: 127.0.0.1:$LOCAL_PORT -> $A800_HOST:$REMOTE_PORT"
  exec autossh -M 0 -N -L "127.0.0.1:$LOCAL_PORT:127.0.0.1:$REMOTE_PORT" $SSH_OPTS "$A800_HOST"
else
  echo "ssh: 127.0.0.1:$LOCAL_PORT -> $A800_HOST:$REMOTE_PORT（断线需手动重连）"
  exec ssh -N -L "127.0.0.1:$LOCAL_PORT:127.0.0.1:$REMOTE_PORT" $SSH_OPTS "$A800_HOST"
fi
