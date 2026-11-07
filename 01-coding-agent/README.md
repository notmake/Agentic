# 01-coding-agent

> A from-scratch coding agent evaluated on SWE-bench Lite — zero agent framework, local LLM only.
> 自研 Coding Agent + SWE-bench 评测闭环（零 agent 框架，纯本地推理）

[![status](https://img.shields.io/badge/status-W0%20skeleton-yellow)]()
[![python](https://img.shields.io/badge/python-3.10-blue)]()
[![license](https://img.shields.io/badge/license-MIT-green)]()

---

## 中文

### 这是什么

从零手写的 coding agent：输入一个 GitHub issue 和它的仓库，agent 自主探索代码、修改文件、跑测试，
最终产出一份可审查的 `git diff` 补丁；再由 SWE-bench 官方 harness 在隔离容器里自动判定是否解决。

设计原则（来自 `notes/00_学习.md` 的案例复盘）：

- **评测先行**：先用 gold patch 跑通官方评测（resolved≈100%），再写 agent
- **最小上下文**：只给模型 issue 描述 + 必要的仓库信息，不塞隐藏测试
- **可审查中间产物**：输出 `git diff`，不是自由文本
- **隔离沙箱**：agent 与评测共用同一官方镜像，环境一致
- **失败分类比分数更有价值**：七类失败归因 + 因果迭代

### 架构

```
configs/<run_id>.yaml
  └─> eval/prepare.py      数据集 pin revision + 校验 + 分层采样
  └─> runner/batch.py      按 instance_id 断点续跑（4-8 并发）
        └─> Docker 官方镜像（reset base_commit）
              └─> sweagent 主循环：query → execute → observe
                    └─> llm.py ──透明──> A800 vLLM（SSH 隧道 8001）
        └─> predictions.jsonl（instance_id / model_name_or_path / model_patch）
  └─> eval/harness.py      官方 swebench==5.0.2（--predictions_path gold 作哨兵）
  └─> eval/classify.py     七类失败归因
  └─> eval/report.py       run 级报告
```

推理在 A800（80GB），编排/沙箱/评测在开发机（双 3060）。纯本地：`openai` SDK 只当本地服务的
HTTP 客户端，不接任何外部 LLM API；`swebench` 是官方评测工具，不属于 agent 框架。

### 快速开始（GPU-free 路径，只需 Docker）

```bash
git clone <this-repo> && cd 01-coding-agent
cp .env.example .env
pip install -e ".[dev]"
pytest                       # 冒烟测试

# 1) 环境真阳性：gold patch 必须 3/3 resolved
python eval/prepare.py --dataset lite --limit 3
bash scripts/pull_images.sh --lite-batch 3
python eval/harness.py --gold --dataset lite --instances 3
# 2) agent 离线全流程（MockModel，秒级，无需数据集/模型）
python -m runner.run_instance --mock
```

真模型链路需要 ≥48GB GPU（A800）——见 `ARCHITECTURE.md`。

### 两条 agent 路线（并存）

| 路线 | 实现 | 状态 |
|---|---|---|
| 自研 | `sweagent/` 手写循环（零框架） | ✅ 离线全绿，`--mock` 可跑 |
| 成熟框架 | `openhands/`（OpenHands CLI 1.16 + 本地 vLLM） | ✅ 本机跑通，适配器可出 patch |

OpenHands 路线使用本机 Qwen3-14B-AWQ（vLLM，16K 上下文，原生 tool calls）；
27B GGUF 需 C++ `llama-server --jinja`，编译中。

### 项目状态

| 阶段 | 内容 | 状态 |
|---|---|---|
| W0 | 环境摸底 + 仓库骨架 | ✅ |
| W1 | 本机模型服务 + gold 评测闭环 | 🟡 模型已通；gold 评测待 Docker |
| W2 | sweagent v1 离线全绿 | ✅ |
| W3 | OpenHands 集成 + 适配器 | ✅ |
| W4 | 10 实例 pilot：**6/10 resolved（60%）**，含失败分类 | ✅ |
| W5 | 扩量（更多实例 / 更大上下文 / 解析稳定性） | ⬜ |
| W6 | 工程收尾 + 开源 | ⬜ |

### 文档

- [ENV_CHECKLIST.md](ENV_CHECKLIST.md) — 双机环境实测值
- `ARCHITECTURE.md` — 架构与 ADR（W5 定稿）
- `LEARNINGS.md` — 失败分类案例与迭代结论（持续更新）
- `notes/` — 学习笔记

---

## English

### What is this

A coding agent written from scratch: given a GitHub issue and its repository, it explores the code,
edits files, runs tests, and produces a reviewable `git diff` patch. The official SWE-bench harness
then judges, inside an isolated container, whether the patch resolves the issue.

Principles: evaluation-first (gold-patch sentinel before any agent code), minimal context, reviewable
artifacts (`git diff`), isolated sandbox (agent and harness share the same official image), and
failure taxonomy over raw score.

### Stack

- Zero agent framework — the loop is ~500 lines of hand-written Python
- Local inference only: vLLM on a remote A800 (SSH-tunnelled), Qwen-family models
- Official `swebench==5.0.2` harness, pinned dataset revisions

### Status

W0 (skeleton) in progress. See the table above.

---

## 目录结构

```
sweagent/    自研 agent 包（零框架，不 import eval）
runner/      单实例 CLI + 批量调度
eval/        数据集准备 / 官方 harness / 失败分类 / 报告
configs/     实验配置卡（与 run_id 绑定）
tests/       pytest
scripts/     部署 / 隧道 / 镜像预热
notes/       学习笔记与实验结论
data/        运行数据（gitignore）
```
