# OpenHands 路线（成熟框架）

自研 `sweagent/` 之外的第二套 agent：用 [OpenHands](https://github.com/OpenHands/OpenHands) CLI
（框架负责循环/工具/上下文），本项目负责工作区准备、任务下发、补丁提取、官方评测对接。

## 本机实测（2026-11-04）

| 项 | 结果 |
|---|---|
| OpenHands CLI | **1.16.0**（SDK 1.21.0），Python 3.12 venv：`~/venvs/openhands` |
| 本地模型（主） | **Qwen3.8-27B-Q4_K_M GGUF + llama-server**（32K ctx，`--jinja`），工具调用 ✅，OpenHands 冒烟 381s |
| 本地模型（备） | Qwen3-14B-AWQ + vLLM 0.17.1（TP=2，16K ctx，hermes parser），工具调用 ✅，冒烟 287s |
| Local runtime | ✅ 不需要 Docker，CLI 直接在当前目录执行 |
| 冒烟 | ✅ "创建 hello.txt"（14B/27B 均通过）；修复 calc.py 产出正确 patch |

## 启动本地模型

```bash
# 主：27B GGUF（已验证可用，32K 上下文，原生 tool calls）
LLAMA_SERVER=/home/wit627/tools/llama-vendor/build/bin/llama-server \
bash openhands/serve_llama.sh

# 备：14B-AWQ + vLLM（16K 上下文）
FLASHINFER_DISABLE_VERSION_CHECK=1 PYTORCH_ALLOC_CONF=expandable_segments:True \
python -m vllm.entrypoints.openai.api_server \
  --model /home/wit627/project/models/Qwen3-14B-AWQ \
  --served-model-name Qwen3-14B-AWQ \
  --port 6790 --tensor-parallel-size 2 \
  --max-model-len 16384 --gpu-memory-utilization 0.85 \
  --enable-auto-tool-choice --tool-call-parser hermes \
  --enable-prefix-caching --disable-custom-all-reduce \
  --enforce-eager --max-num-seqs 4
```

> llama-server 编译要点：源码取 PyPI `llama-cpp-python` sdist 的 `vendor/llama.cpp`（官方源镜像），
> gcc-12 主机编译器 + CUDA 12.8；需关掉 `-compress-mode`（nvcc 12.8 不认）。
> 编译产物：`/home/wit627/tools/llama-vendor/build/bin/llama-server`。

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

## 关键坑：reasoning_effort

OpenHands 默认发 `reasoning_effort="high"`，而 Qwen3.8 GGUF 的 chat template 只接受
`xhigh / medium / low` → llama-server 返回 `Jinja Exception: Unexpected reasoning effort high`，
agent 重试几次后空手结束（patch 为空）。

修复：生成 `~/.openhands/agent_settings.json`，把 LLM 的 `reasoning_effort` 设为 `medium`
（`--override-with-envs` 只覆盖 model/base_url/api_key，会保留该字段）：

```bash
~/venvs/openhands/bin/python - <<'EOF'
from openhands.sdk import LLM
from openhands_cli.utils import get_default_cli_agent
import pathlib
llm = LLM(model="openai/Qwen3.8-27B", api_key="local",
          base_url="http://127.0.0.1:6790/v1", usage_id="agent",
          reasoning_effort="medium")
p = pathlib.Path.home()/".openhands/agent_settings.json"
p.write_text(get_default_cli_agent(llm).model_dump_json(context={"expose_secrets": True}))
EOF
```

## 已知限制

- **14B 备选只有 16K 上下文**：OpenHands 官方建议 32K+；双 12G 卡开 32K 会 OOM（实测）。
  复杂实例可能因上下文不足失败，属于失败分类里的 `LIMIT_ERROR`。
- **27B 用 32K 上下文**：双卡显存约 21G/24G，余量小；`n_slots=4` 时并发会挤爆，批量时需 `--parallel 1`。
- **无 Docker**：官方 SWE-bench 评测仍需 Docker（当前用户不在 docker 组），暂时只能产出 patch，
  不能出官方解决率。
- **llama-cpp-python 不可用**：0.3.35 不支持原生 tool_calls（返回 XML 文本），必须用 C++ `llama-server --jinja`。
