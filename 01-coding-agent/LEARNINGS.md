# LEARNINGS — 失败案例与实验结论

> 记录每次实验的因果结论，供迭代和面试复盘。分数不是终点，失败分类才是。

## 2026-11-05 · 环境真阳性（gold 哨兵）

- 数据集：SWE-bench Lite，revision `b0dde1093fe4`
- harness：swebench 5.0.2
- 结果：**gold 3/3 resolved**（astropy-12907 / django-10914 / matplotlib-18869），`infra_failure=false`
- 结论：数据集、官方镜像、评测脚本、磁盘链路全部正确，后续 agent 失败可归因于模型/脚手架

## 2026-11-05 · OpenHands + Qwen3.8-27B（首个真实实例）

**astropy__astropy-12907：resolved ✅**

- 耗时 1975s（27B Q4，双 3060，32K ctx）
- patch：`astropy/modeling/separable.py` 中 `_cstack` 的 `cright[...] = 1` → `= right`
- 官方报告：`resolved=true`，F2P 全过，P2P 无回归
- 关键坑：OpenHands 默认 `reasoning_effort=high`，Qwen3.8 模板只接受
  `xhigh/medium/low` → llama-server 抛 Jinja Exception，agent 重试后空手结束（空补丁）。
  修复：`~/.openhands/agent_settings.json` 设 `reasoning_effort=medium`。

**方法论收获**

1. 先跑 gold（3/3），再评 agent —— 否则无法区分"模型不行"和"环境不行"。
2. 首次空补丁不是模型能力问题，是协议不兼容（reasoning_effort）；看 llama-server 日志才定位到。
3. 用官方镜像导出的 `/testbed` 作为 OpenHands 工作区，避免 GitHub 慢速克隆，且保证与评测环境同源。

## 待补

- django / matplotlib 实例结果
- 自研 sweagent 与本框架的对照实验
- 失败分类分布（需要更多实例）
