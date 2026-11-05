#!/usr/bin/env bash
# gold 哨兵：环境真阳性验证（3/3 resolved 才说明数据集/镜像/harness 全链路正确）
#
# 用法（需要 docker 组权限；工具 shell 里用 sg docker -c 包一层）：
#   sg docker -c 'bash scripts/run_gold.sh'
set -eu
cd "$(dirname "$0")/.."

export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
export PYTHONPATH="${PYTHONPATH:-}:$(pwd)"

python3 eval/harness.py --gold --dataset lite --instances 3 "$@"
