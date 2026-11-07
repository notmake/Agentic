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

**django__django-10914：resolved ✅**

- 耗时 360s，patch 625B：`FILE_UPLOAD_PERMISSIONS = None` → `0o644`（与官方修复一致）
- 官方报告：`resolved=true`，F2P/P2P 全过

**matplotlib__matplotlib-18869：resolved ✅**

- 耗时 992s，patch 1827B：在 `lib/matplotlib/__init__.py` 增加 `_parse_to_version_info`
  与 `version_info` 懒加载（与官方修复思路一致）
- 官方报告：`resolved=true`，F2P 4/4，P2P 无回归

### 首批汇总（3 实例，全部来自 Lite 分层采样）

| 实例 | 耗时 | 结果 |
|---|---:|---|
| astropy__astropy-12907 | 1975s | resolved |
| django__django-10914 | 360s | resolved |
| matplotlib__matplotlib-18869 | 992s | resolved |

**3/3 = 100%**（样本量小，只说明管线 + 27B 在简单实例上可用；下一阶段扩到 10-20 实例看真实分布）。
平均耗时约 18 分钟/实例，单卡 27B Q4 + 32K ctx。

## 2026-11-07 · 自研 agent 对照（同一实例、同一模型、16K 上下文）

**astropy__astropy-12907：LIMIT_ERROR（40 步触顶，空补丁）**

- 自研 sweagent：1556s，40 次模型调用，45 个动作，**0 字节补丁**
- 触发 5 次上下文压缩、丢弃 36 个 step —— 16K 窗口下压缩过于频繁，早期探索信息丢失
- 对比 OpenHands（同为 27B、同实例）：resolved ✅，1975s
- 结论：**框架在上下文管理/工具编排上的成熟度直接决定成败**；自研版需要
  更聪明的压缩策略（保留关键文件内容）或更大上下文，而不是简单按步丢历史
- 分类管线工作正常：`LIMIT_ERROR`

## 2026-11-07 · pilot-10（10 实例）

**6/10 resolved（60%）**。失败 4 例：2 个 FORMAT_ERROR（工具调用 JSON 不合法、空补丁）、
1 个 PATCH_ERROR 5d（flask 部分修复）、1 个 PATCH_ERROR 5b（requests 没跑测试就提交）。
逐实例耗时与 patch 见 `notes/pilot-10-results.md`。

关键结论：

1. 16K 上下文 + 27B Q4 在 6 个实例上够用；复杂实例更易出现长输出与 JSON 解析失败。
2. 工具调用 JSON 健壮性是当前最大短板（服务端 parser 严格），修复优先级高于换模型。
3. 自研 agent 在同实例上 LIMIT_ERROR —— 框架的上下文/工具编排优势被数据证实。

## 待补

- django / matplotlib 实例结果
- 自研 sweagent 与本框架的对照实验
- 失败分类分布（需要更多实例）
