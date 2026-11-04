# 环境摸底清单（W0 验收物）

> 规则：每项必须有实测值 + 日期，不许留"应该可以"。

## 开发机（dev，双 3060）

| 项 | 实测值 | 备注 |
|---|---|---|
| 磁盘 | `/` 915G，已用 534G，**可用 336G**（2026-11-04） | 评测镜像 ~120GiB + artifacts ≤50GB 预算内 |
| CPU | 16 核 | 评测 `max_workers` 可从 4 起上调 |
| 内存 | 31Gi，已用 15Gi，**交换 8G 已用 7.7G**（2026-11-04） | 跑批量评测前必须停 27B/4B 服务腾内存 |
| Docker | 29.3.0，**当前用户无 daemon 权限**（permission denied） | 待办：`sudo usermod -aG docker $USER` 后重登，或全程 sudo |
| Python | conda env `pytorch`，Python 3.10.20 | `uv` 未安装，用 pip 即可 |
| git | 2.43.0 | |
| 端口 8000 | **被占用**（`backend/api_server/run.py`，pid 1599959） | → A800 隧道改用 **8001** |
| 端口 6789 | 4B vLLM（按需启动） | |
| 端口 6790 | 27B llama.cpp（当前在跑，pid 1535534） | 与 6789 互斥 |
| 端口 8001 | 空闲 | 预留给 A800 隧道 |

## 已有模型权重（dev）

| 文件 | 大小 | 备注 |
|---|---|---|
| `/home/wit627/project/models/Qwen3.8-27B-Q4_K_M.gguf` | 18G | **唯一 27B 权重**，Q4_K_M 量化；无 3.5 系 27B 全精度 |
| `models/Qwen3.5-4B/` | — | 开发冒烟用 |
| `models/Qwen3-14B-AWQ` | — | 备选：vLLM 原生 AWQ，工具调用可能更稳 |

> 影响：计划里的"已有 27B"实际是 **Q4 量化 GGUF**。vLLM 加载 GGUF 属实验性支持，W1 必须实测；
> 若 GGUF+toolcall 不成立，优先级：① text 协议兜底 ② Qwen3-14B-AWQ（已有） ③ 决策门下载 30B-Coder。

## A800（远程，≥500G 盘、可访问 HuggingFace）

| 项 | 实测值 | 备注 |
|---|---|---|
| GPU / 驱动 | 待测 | 跑 `scripts/a800_survey.sh` |
| 磁盘 | 待测（用户确认 ≥500GB） | |
| Docker | **无**（用户确认） | 评测沙箱留在开发机，A800 只做推理 |
| HF 直连 | **可**（用户确认） | 权重可直下；备 hf-mirror |
| vLLM 版本 | 待测 | |
| 常驻方式 | 待测（tmux/systemd） | |
| 27B 权重路径 | 待测 | 确认是否用 dev 机同一个 gguf（需上传 18G）或 A800 本地已有 |
| SSH 免密 | 待测 | |

## 待办（W0 收尾前）

- [ ] 用户在 A800 上运行 `scripts/a800_survey.sh`，结果回填上表
- [ ] 开发机 docker 组权限处理（`sudo usermod -aG docker wit627 && newgrp docker`）
- [ ] 确定 A800 上 27B 权重来源：本地上传 vs 远程下载（建议远程 `hf-mirror` 下 Qwen 官方 27B 的 GGUF 或直接用已有的 4B/14B-AWQ 做管线验证）
