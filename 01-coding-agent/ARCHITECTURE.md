# ARCHITECTURE

> 目标：在本机（双 RTX 3060）用**本地模型**跑通一个可信的 Coding Agent 评测闭环，
> 并把"为什么行/为什么不行"变成可复现的工程结论。

## 1. 约束与目标

| 约束 | 现实 | 后果 |
|---|---|---|
| 纯本地推理 | 27B Q4 GGUF，双卡 24G | 上下文 16K；单实例 5–60 分钟 |
| 无 A800（暂缓） | 只能跑 27B/14B | 解决率上限受限，靠工程与归因体现价值 |
| Docker 可用 | 官方评测镜像可跑 | 评测可信，但镜像拉取受网络影响 |
| 求职向 | 需要可审查的作品集 | 文档、失败分类、单变量实验比分数重要 |

## 2. 两条 agent 路线（并存）

```
                         ┌─────────────────────────────┐
   SWE-bench Lite ──────▶│ eval/prepare.py             │  pin revision + 分层采样
                         └──────────────┬──────────────┘
                                        │ instance: repo/base_commit/problem
              ┌─────────────────────────┴─────────────────────────┐
              ▼                                                   ▼
   ┌──────────────────────┐                            ┌──────────────────────┐
   │ 路线 A：自研 sweagent │                            │ 路线 B：OpenHands     │
   │ sweagent/ + runner/   │                            │ openhands/ 适配器     │
   └──────────┬───────────┘                            └──────────┬───────────┘
              │ 同一 LLM 接口                                       │
              └──────────────────────┬──────────────────────────────┘
                                     ▼
                     llama-server :6790（Qwen3.8-27B Q4，16K）
                                     │
                                     ▼
                   工作区（官方镜像导出的 /testbed）
                                     │
                                     ▼
             predictions.jsonl（instance_id / model / patch）
                                     ▼
             eval/harness.py（swebench 5.0.2 + Docker）→ report.json
                                     ▼
             eval/classify.py（七类）→ eval/report.py（解决率/分布/效率）
```

**为什么两套并存**：自研版用于理解和对照（同实例上它 LIMIT_ERROR 而框架 resolved，
直接证明框架在上下文/工具编排上的价值）；框架版用于产出可信的简历基线。

## 3. 关键设计决策（ADR 摘要）

### ADR-1 评测先行
先跑 **gold patch 哨兵**（官方内建 `--predictions_path gold`），3/3 resolved 才写 agent。
否则无法区分"模型不行"和"环境不行"。实测 3/3 通过。

### ADR-2 agent 与评测共用同一官方镜像
工作区从 `swebench/sweb.eval.x86_64.<instance>` 镜像导出 `/testbed`（tar 流，文件属主为
当前用户），保证 agent 看到的仓库与评测环境同源；入口 `git reset --hard base_commit`
防测试补丁污染。

### ADR-3 16K 上下文 + 单槽 + q8 KV
32K + `n_slots=4` 曾导致 CUDA 崩溃（Xid 154，双卡掉线）。稳定档：16K、`parallel=1`、
`cache-type-k/v q8_0`、`flash-attn on`。显存约 19G/24G。

### ADR-4 非原生工具调用（native_tool_calling=False）
llama-server 的原生 tool parser 对非法 JSON 直接 500；27B 长输出时偶发引号不闭合。
代理层 `temperature=0 + 提示` 重试无效（错误在服务端解析）。最终启用 OpenHands 的
prompt-mocked 工具协议：工具描述进 prompt，框架解析文本动作，服务端不再碰 JSON。
代价：prompt 更长、速度更慢；收益：空补丁清零。

### ADR-5 run_id 与配置卡绑定
每次实验一张 `configs/<run_id>.yaml`（数据集 revision、模型、协议、上下文、限额）。
官方评测缓存按 run_id 记账，换预测必换 run_id，避免拿到旧结果。

### ADR-6 失败七分类
`TEST_ENV_ERROR / ENV_ERROR / FORMAT_ERROR / LIMIT_ERROR / LOCATE_ERROR / PATCH_ERROR /
RESOLVED`，PATCH_ERROR 再分 5a–5e。分类规则吃三类信号：官方 report、轨迹、
框架日志（如 tool-call JSON 解析失败、是否跑过测试）。

## 4. 接口契约

| 产物 | 位置 | 说明 |
|---|---|---|
| predictions | `<run_dir>/predictions.jsonl` | 官方三字段，逐行一个实例 |
| 单实例补丁 | `<run_dir>/<instance>/patch.diff` | `git diff`，可审查 |
| 轨迹 | `<run_dir>/<instance>/trajectory.json`（自研）/ `openhands.log`（框架） | 复盘与分类证据 |
| 官方报告 | `<run_dir>/official_report.json` | 合并后的 `{instance_id: {...}}` |
| 分类 | `<run_dir>/classifications.csv` | 七类 + 二级标签 |
| 汇总 | `<run_dir>/report.md`、`summary.csv` | 解决率/分布/效率 |

## 5. 可复现性

- 数据集 pin revision（Lite `b0dde109…`），写入 `data/datasets/*_meta.json`
- harness 精确 `swebench==5.0.2`；任何升级重跑 gold 哨兵
- 模型/服务参数写进配置卡；`temperature=0`
- 运行环境状态（Docker 镜像、llama-server 版本、Jinja 缓存）记录在 `ENV_CHECKLIST.md` / `LEARNINGS.md`

## 6. 已知限制

1. 16K 上下文限制复杂实例的探索深度；24K 显存风险高，暂不采用
2. 27B Q4 能力上限；14B-AWQ 为备选，未做规模化对照
3. 本地 runtime 无沙箱隔离（仅适合受控实验）；评测侧仍有 Docker 隔离
4. 网络不稳定：镜像拉取需重试/换源；Docker Hub 直连不稳
5. 样本量：pilot-10、lite20 仍是小样本，不能外推为全量结论

## 7. 目录地图

```
sweagent/      自研循环（零框架）
runner/        自研单实例/批量入口
openhands/     框架适配器、批量调度、LLM 代理（参考实现）
eval/          数据集准备、官方 harness 封装、七分类、报告
configs/       实验配置卡（与 run_id 绑定）
scripts/       镜像拉取/重试、testbed 导出、pilot 调度、gold 哨兵
tests/         配对约束、主循环、分类等回归测试
notes/         实验结论与心智模型
data/          数据集/工作区/运行产物（gitignore）
```
