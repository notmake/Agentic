#!/usr/bin/env bash
# A800 环境摸底（只读，不改任何东西）
# 用法：scp 到 A800 或直接 ssh 后粘贴运行；把输出贴回 ENV_CHECKLIST.md
set -u
echo "========== 1. GPU / 驱动 =========="
nvidia-smi || echo "[!] nvidia-smi 不可用"
echo
echo "========== 2. 磁盘 =========="
df -h / /home 2>/dev/null || df -h
echo
echo "========== 3. CPU / 内存 =========="
nproc; free -h
echo
echo "========== 4. Docker =========="
if command -v docker >/dev/null 2>&1; then
  docker --version
  docker info --format 'ServerVersion={{.ServerVersion}} Driver={{.Driver}} RootDir={{.DockerRootDir}}' 2>&1 | head -3
  echo "当前用户是否在 docker 组：$(id -nG | tr ' ' '\n' | grep -x docker || echo 否)"
else
  echo "未安装 Docker"
fi
echo
echo "========== 5. 网络可达性 =========="
for url in https://huggingface.co https://hf-mirror.com https://registry-1.docker.io/v2/ https://pypi.org/simple/; do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 "$url" || echo TIMEOUT)
  echo "$url -> $code"
done
echo
echo "========== 6. Python 环境 =========="
which python3 && python3 --version
python3 -c "import vllm; print('vllm', vllm.__version__)" 2>&1 | head -2
python3 -c "import torch; print('torch', torch.__version__, 'cuda', torch.version.cuda)" 2>&1 | head -2
echo
echo "========== 7. 常驻方式 =========="
command -v tmux >/dev/null && echo "tmux 可用" || echo "tmux 不可用"
command -v screen >/dev/null && echo "screen 可用" || echo "screen 不可用"
systemctl --user status >/dev/null 2>&1 && echo "systemd user 可用" || echo "systemd user 不可用"
echo
echo "========== 8. 已有模型权重 =========="
echo "（请在下面手动确认 27B 权重的路径）"
find "$HOME" -maxdepth 4 \( -name '*.gguf' -o -name 'config.json' \) -size +1M 2>/dev/null | head -20
echo
echo "========== 9. 端口占用 =========="
ss -ltnp 2>/dev/null | grep -E ':8000|:8001' || echo "8000/8001 空闲"
echo
echo "========== 10. SSH 免密 / sudo =========="
echo "（从开发机侧另行验证：ssh -o BatchMode=yes <host> true）"
sudo -n true 2>/dev/null && echo "sudo 免密可用" || echo "sudo 需要密码或不可用"
