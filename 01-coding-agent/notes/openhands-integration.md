# OpenHands 集成方案（2026-11-04 方向调整）

## 背景与决策

用户决定：**A800 暂缓、本机开发、不自研 agent 循环、改用成熟框架 OpenHands**。
原有自研 `sweagent/` 保留（两套并存），评测与失败分类管线（`eval/`）继续复用。

## 本机现实约束

| 约束 | 实测 | 影响 |
|---|---|---|
| GPU | 双 RTX 3060 12G，共 24G | 27B Q4 占 ~18G，余量小 |
| 27B 服务 | `llama_cpp.server` :6790，n_ctx 32768 | **不支持原生 tool_calls**（实测返回 XML 文本 + 思考污染） |
| llama.cpp C++ | 未安装；官方源码下载中 | `llama-server --jinja` 才能原生工具调用 |
| vLLM | 0.17.1 在 conda `vllm` 环境，未启动 | 14B-AWQ 备选路径 |
| Docker | 无 daemon 权限 | OpenHands 的 Docker 沙箱不可用；SWE-bench 评测也被阻塞 |
| OpenHands | V1 CLI 1.x（Python 3.12 venv `~/venvs/openhands`） | 需确认 local runtime 与 headless 用法 |

## 目标架构（本机）

```
OpenHands CLI (Python 3.12 venv)
   │  openai/Qwen3.8-27B  http://127.0.0.1:6790/v1
   ▼
llama-server (C++ llama.cpp, --jinja, tool calls)
   │  27B Q4_K_M GGUF, 双 3060
   ▼
目标仓库（SWE-bench instance 的 /testbed 或本地目录）
   │
   ▼
eval/ 官方 swebench harness（需 Docker，权限修复后）
```

## 与自研 sweagent 并存

| 维度 | sweagent（自研） | OpenHands |
|---|---|---|
| agent 循环 | `sweagent/agent.py` | 框架内置 |
| 工具/沙箱 | `environment.py`（local/docker） | 框架 runtime |
| 评测 | `eval/`（共用） | `eval/`（共用） |
| 输出 | predictions.jsonl | 需适配器转 predictions.jsonl |

对比实验价值：同一模型、同一数据集、同一评测管线，比较两套 agent 的解决率与失败分布。

## 待验证清单（按顺序）

- [x] `openhands --help` / `openhands --version` 可用（CLI 1.16.0 / SDK 1.21.0）
- [x] V1 支持 **local runtime**（无 Docker）：CLI 直接在当前目录执行
- [x] headless：`--headless --override-with-envs --always-approve --exit-without-confirmation`
- [x] 自定义后端：`LLM_MODEL=openai/<name>` + `LLM_BASE_URL` + `LLM_API_KEY`
- [x] 原生 function calling 必需（llama-cpp-python 不行；vLLM hermes parser 可以）
- [x] 单任务跑通并产出 git diff（14B-AWQ，calc 修复 ~287s）
- [x] 适配器：`openhands/run_instance.py` → predictions.jsonl

## 实测结果（2026-11-05）

| 验证项 | 结果 |
|---|---|
| gold 3/3 哨兵（astropy / django / matplotlib） | ✅ 全部 `resolved=true`，`infra_failure=false` |
| OpenHands + 27B 跑 astropy__astropy-12907 | ✅ 1975s，patch 504B，修改 `separable.py` 的 `_cstack`（与官方修复一致） |
| 14B-AWQ 冒烟 | ✅ 287s，正确修复 calc.py |
| 27B 冒烟 | ✅ 381s，正确修复 calc.py |

**踩坑：reasoning_effort**。OpenHands 默认发 `high`，Qwen3.8 GGUF 模板只接受
`xhigh/medium/low` → llama-server 返回 Jinja Exception，agent 重试后空手结束（空补丁）。
修复：`~/.openhands/agent_settings.json` 固定 `reasoning_effort=medium`，详见
`openhands/README.md`。

**镜像**：daocloud/xuanyuan 不放行 `swebench` 命名空间（403），实测 `docker.1panel.live`
可用；拉取会偶发 connection reset，`scripts/pull_gold_retry.sh` 自动重试并复用已下载层。

## 风险

1. **OpenHands V1 可能强依赖沙箱/Docker**：若 local runtime 被移除，需要用户先修复 docker 权限（`sudo usermod -aG docker wit627`）。
2. **27B Q4 + 32K 上下文 + OpenHands 长提示**：显存与速度都紧张（11-16 tok/s），单实例可能 30-60 分钟；先跑通再谈批量。
3. **SWE-bench 官方评测仍需 Docker**：无权限前只能做「能改代码、能出 patch」的冒烟，不能出解决率。
4. **OpenHands 上下文要求 ≥32K**：llama-server 需 `-c 32768` 以上，KV cache 可能挤爆双卡；必要时降到 32K 并限制 agent 步数。
