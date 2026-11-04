# OpenHands 路线（成熟框架）

自研 `sweagent/` 之外的第二套 agent：用 [OpenHands](https://github.com/OpenHands/OpenHands) CLI
（框架负责循环/工具/上下文），本项目负责工作区准备、任务下发、补丁提取、官方评测对接。

## 本机实测（2026-11-04）

| 项 | 结果 |
|---|---|
| OpenHands CLI | **1.16.0**（SDK 1.21.0），Python 3.12 venv：`~/venvs/openhands` |
| 本地模型 | Qwen3-14B-AWQ + vLLM 0.17.1（TP=2，16K ctx，`--tool-call-parser hermes`） |
| 工具调用 | ✅ 原生 tool_calls 正常 |
| Local runtime | ✅ 不需要 Docker，CLI 直接在当前目录执行 |
| 冒烟 | ✅ "创建 hello.txt 写入 hi" 成功，3 条消息完成 |

## 启动本地模型

```bash
# 14B-AWQ（已验证可用；双 3060，16K 上下文）
FLASHINFER_DISABLE_VERSION_CHECK=1 PYTORCH_ALLOC_CONF=expandable_segments:True \
python -m vllm.entrypoints.openai.api_server \
  --model /home/wit627/project/models/Qwen3-14B-AWQ \
  --served-model-name Qwen3-14B-AWQ \
  --port 6790 --tensor-parallel-size 2 \
  --max-model-len 16384 --gpu-memory-utilization 0.85 \
  --enable-auto-tool-choice --tool-call-parser hermes \
  --enable-prefix-caching --disable-custom-all-reduce \
  --enforce-eager --max-num-seqs 4

# 27B GGUF（等 llama.cpp 官方源码编译出 llama-server 后启用）
bash openhands/serve_llama.sh
```

## 跑一个实例

```bash
export PATH=$HOME/venvs/openhands/bin:$PATH
export LLM_MODEL=openai/Qwen3-14B-AWQ
export LLM_BASE_URL=http://127.0.0.1:6790/v1
export LLM_API_KEY=local

# 本地目录冒烟
python -m openhands.run_instance --repo-dir /tmp/some_repo \
    --task "Fix the bug in calc.py: add(2,3) should return 5"

# SWE-bench 实例（需先 eval/prepare.py）
python -m openhands.run_instance --dataset data/datasets/lite.jsonl \
    --instance-id astropy__astropy-12907
```

输出：`data/runs/openhands/<instance_id>/{openhands.log, patch.diff, prediction.jsonl}`，
与自研 runner 的输出格式一致，可直接走 `eval/harness.py` + `eval/classify.py`。

## 已知限制

- **16K 上下文**：OpenHands 官方建议 32K+；14B 在双 12G 卡上开 32K 会 OOM（实测）。
  复杂实例可能因上下文不足失败，这本身是失败分类里的 `LIMIT_ERROR` 一类。
- **无 Docker**：官方 SWE-bench 评测仍需 Docker（当前用户不在 docker 组），暂时只能产出 patch，
  不能出官方解决率。
- **27B**：现有 llama-cpp-python 服务不支持原生 tool_calls，需 C++ `llama-server --jinja`
  （官方源码下载/编译中）。
