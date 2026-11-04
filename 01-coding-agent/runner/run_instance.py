"""单实例 CLI：输入一个 SWE-bench 实例，输出 predictions 三字段 + 轨迹。

用法：
    # 1) 离线演示（无需模型/无需数据集）：建临时仓库 → MockModel 修 bug → 出 patch
    python -m runner.run_instance --mock

    # 2) 真实例（W1 之后；数据集先用 eval/prepare.py 下载）
    python -m runner.run_instance --backend a800_27b \
        --dataset data/datasets/lite.jsonl --instance-id astropy__astropy-12907

    # 3) 本地目录调试（不起 Docker）
    python -m runner.run_instance --backend dev_4b --local-dir /tmp/repo --instance-file inst.json

输出（<output_dir>/）：
    trajectory.json   完整轨迹
    patch.diff        可被 git apply 的补丁
    prediction.jsonl  官方 predictions 格式（instance_id / model_name_or_path / model_patch）
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import get_backend, load_env  # noqa: E402
from llm import LLM, MockTransport, OpenAICompatTransport, UrllibTransport  # noqa: E402
from sweagent.agent import Agent, AgentConfig  # noqa: E402
from sweagent.environment import DockerEnvironment, LocalEnvironment  # noqa: E402
from sweagent.prompts import build_system_prompt, build_task_prompt  # noqa: E402

DEMO_BUGGY = '''def add(a, b):
    """Return the sum of a and b."""
    return a - b
'''

DEMO_FIXED = '''def add(a, b):
    """Return the sum of a and b."""
    return a + b
'''

DEMO_PLAN = [
    {"tool": "view", "args": {"path": "calc.py"}},
    {"tool": "write", "args": {"path": "calc.py", "content": DEMO_FIXED}},
    {"tool": "bash", "args": {"command": "python -c \"from calc import add; assert add(2,3)==5; print('ok')\""}},
    {"tool": "submit", "args": {"summary": "fix add(): minus -> plus"}},
]


def make_demo_repo() -> Path:
    """建一个带 bug 的临时 git 仓库（mock 演示用）。"""
    base = Path(tempfile.mkdtemp(prefix="sweagent_demo_"))
    repo = base / "repo"
    repo.mkdir(parents=True)
    (repo / "calc.py").write_text(DEMO_BUGGY, encoding="utf-8")
    (repo / ".gitignore").write_text("__pycache__/\n*.pyc\n", encoding="utf-8")
    for cmd in (
        ["git", "init", "-q"],
        ["git", "add", "-A"],
        ["git", "-c", "user.email=demo@local", "-c", "user.name=demo", "commit", "-qm", "init"],
    ):
        subprocess.run(cmd, cwd=repo, check=True)
    return repo


def load_instance(args) -> dict:
    if args.instance_file:
        return json.loads(Path(args.instance_file).read_text(encoding="utf-8"))
    if args.dataset and args.instance_id:
        with open(args.dataset, encoding="utf-8") as f:
            for line in f:
                row = json.loads(line)
                if row.get("instance_id") == args.instance_id:
                    return row
        raise SystemExit(f"数据集里找不到实例 {args.instance_id}")
    raise SystemExit("非 mock 模式需要 --instance-file 或 --dataset + --instance-id")


def build_llm(backend_name: str, protocol: str | None):
    if backend_name == "mock":
        return LLM(MockTransport(DEMO_PLAN), protocol="toolcall")
    backend = get_backend(backend_name)
    proto = protocol or backend.protocol
    transport = OpenAICompatTransport(
        base_url=backend.base_url, api_key=backend.api_key,
        model=backend.model, max_tokens=backend.max_tokens,
    )
    return LLM(transport, protocol=proto, response_policy=backend.response_policy)


def image_name(instance_id: str) -> str:
    return f"swebench/sweb.eval.x86_64.{instance_id.replace('__', '_1776_')}:latest"


def main() -> None:
    ap = argparse.ArgumentParser(description="运行单个 SWE-bench 实例")
    ap.add_argument("--backend", default=None, help="a800_27b | a800_30b | dev_4b | dev_27b | mock")
    ap.add_argument("--protocol", default=None, help="toolcall | text（覆盖后端默认）")
    ap.add_argument("--dataset", default=str(ROOT / "data/datasets/lite.jsonl"))
    ap.add_argument("--instance-id", default="")
    ap.add_argument("--instance-file", default="")
    ap.add_argument("--local-dir", default="", help="用本地目录代替 Docker 沙箱（调试）")
    ap.add_argument("--output-dir", default="")
    ap.add_argument("--mock", action="store_true", help="离线演示：自建仓库 + MockModel")
    args = ap.parse_args()

    load_env()
    backend_name = "mock" if args.mock else (args.backend or "a800_27b")

    if args.mock:
        repo = make_demo_repo()
        instance = {
            "instance_id": "demo__calc-bug",
            "repo": "demo/calc",
            "base_commit": "HEAD",
            "problem_statement": "add(2, 3) 返回了 -1，应该是 5。请修复 calc.py。",
        }
        env = LocalEnvironment(str(repo))
        # 运行产物放仓库外：轨迹/补丁不能污染 git 状态（否则 get_patch 会把它们也打进补丁）
        out_dir = Path(args.output_dir or repo.parent / "run_output")
    else:
        instance = load_instance(args)
        out_dir = Path(args.output_dir or ROOT / "data/runs" / instance["instance_id"])
        if args.local_dir:
            env = LocalEnvironment(args.local_dir)
        else:
            env = DockerEnvironment(
                image=image_name(instance["instance_id"]),
                container_name=f"sweagent-{instance['instance_id'].replace('__', '-')}",
                base_commit=instance["base_commit"],
            )
            env.start()

    protocol = "toolcall" if args.mock else (args.protocol or get_backend(backend_name).protocol)
    llm = build_llm(backend_name, protocol)

    config = AgentConfig(
        instance_id=instance["instance_id"],
        backend=backend_name,
        output_dir=str(out_dir),
        context_window=32_768,
    )
    agent = Agent(llm, env, config)
    result = agent.run(
        build_system_prompt(protocol),
        build_task_prompt(
            instance["problem_statement"], instance["repo"], instance["base_commit"]
        ),
    )

    if not args.mock and not args.local_dir:
        env.stop()

    # 落盘三件套
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "patch.diff").write_text(result["patch"], encoding="utf-8")
    with open(out_dir / "prediction.jsonl", "w", encoding="utf-8") as f:
        f.write(json.dumps({
            "instance_id": instance["instance_id"],
            "model_name_or_path": result.get("backend", backend_name),
            "model_patch": result["patch"],
        }, ensure_ascii=False) + "\n")

    print(json.dumps({k: result[k] for k in
                      ("instance_id", "exit_status", "n_calls", "prompt_tokens",
                       "completion_tokens", "elapsed_seconds")}, ensure_ascii=False, indent=2))
    print(f"轨迹: {out_dir / 'trajectory.json'}")
    print(f"补丁: {out_dir / 'patch.diff'}")
    print(f"预测: {out_dir / 'prediction.jsonl'}")


if __name__ == "__main__":
    main()
