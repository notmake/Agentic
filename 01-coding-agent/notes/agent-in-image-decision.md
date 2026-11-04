# 决策：agent 代码如何进入官方评测镜像（W0 必交付项）

## 问题

官方 `swebench/sweb.eval.x86_64.*` 镜像只为**跑测试**构建：内含 `/opt/miniconda3` 与
`testbed` conda 环境、仓库代码在 `/testbed`。它**不含** sweagent 代码与 openai SDK。
如果不解决"代码怎么进去、依赖怎么装、轨迹怎么出来"，W3 会翻倍。

## 两个方案

### 方案 A：薄封装镜像（默认备选）

```dockerfile
FROM swebench/sweb.eval.x86_64.astropy_1776_astropy-12907:latest
COPY . /opt/sweagent
RUN /opt/miniconda3/envs/testbed/bin/pip install --no-deps openai  # 或装进 base
```

- 优点：镜像自包含、可复现
- 缺点：每个实例镜像都要构建 300 次；`pip install` 会改 testbed 环境（若装错 env）→ 必须
  只动 base env，**testbed 保持原样**，否则"圈内=圈外"被破坏
- 依赖：构建时要有网（或用 wheelhouse 预置）

### 方案 B：bind-mount + 标准库客户端（**首选**）

```bash
docker run -d --name sw-$IID \
  -v "$PWD:/opt/sweagent:ro" \
  swebench/sweb.eval.x86_64.<iid>:latest sleep infinity
docker exec sw-$IID bash -lc 'python3 /opt/sweagent/runner/agent_in_container.py ...'
```

- 零安装：agent 只用 Python 标准库（`urllib.request` 调 LLM HTTP 接口、`subprocess` 调 git）
- 不在镜像里装任何东西 → **testbed 环境 100% 不受污染**
- 镜像层零重复构建，300 个实例直接复用官方镜像
- 轨迹通过 stdout 输出（JSON 一行）或 `docker cp` 取出

### 裁决

**采用方案 B 为首选**：`llm.py` 同时提供 `UrllibTransport`（标准库，供容器内使用）和
`OpenAICompatTransport`（开发机调试用）。只有当 urllib 传输在 A800 上遇到协议不兼容时才回退方案 A。

## 待实测确认（W1/W3）

- [ ] 官方镜像 base env 的 Python 版本是否 ≥3.10（影响 dataclasses/typing 用法）
- [ ] 容器内能否访问开发机（`--network host` 下 `127.0.0.1:8001` 是否可用）
- [ ] `/testbed` 的 git 状态与 conda 环境名（预期 `testbed`）
- [ ] base env python 能否直接执行 `/opt/sweagent`（只读挂载）下的代码

> 阻塞：当前用户无 docker daemon 权限（见 ENV_CHECKLIST.md），以上实测待权限修复后进行。
