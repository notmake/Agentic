"""OpenHands 适配器：把一个 SWE-bench 实例交给 OpenHands CLI，产出 predictions 三字段。

与自研 runner 的区别：
  - agent 循环、工具、上下文全部由 OpenHands 框架负责（成熟框架路线）
  - 本项目只负责：工作区准备 → 调用 CLI → 提取 git diff → 官方 predictions 格式
  - 轨迹由 OpenHands 保存在 ~/.openhands/conversations/<id>/，这里复制到 run 目录

用法：
    # 本地目录冒烟（不需要数据集）
    python -m openhands.run_instance --repo-dir /tmp/oh_test --task "修复 add 函数"

    # 真实例（数据集由 eval/prepare.py 准备）
    python -m openhands.run_instance --dataset data/datasets/lite.jsonl \
        --instance-id astropy__astropy-12907 --workspace data/workspaces/<instance_id>

前置：
    export LLM_MODEL=openai/Qwen3-14B-AWQ
    export LLM_BASE_URL=http://127.0.0.1:6790/v1
    export LLM_API_KEY=local
    export PATH=~/venvs/openhands/bin:$PATH
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OPENHANDS_BIN = os.environ.get("OPENHANDS_BIN", str(Path.home() / "venvs/openhands/bin/openhands"))


def load_instance(args) -> dict:
    if args.instance_file:
        return json.loads(Path(args.instance_file).read_text(encoding="utf-8"))
    if args.dataset and args.instance_id:
        with open(args.dataset, encoding="utf-8") as f:
            for line in f:
                row = json.loads(line)
                if row.get("instance_id") == args.instance_id:
                    return row
        raise SystemExit(f"数据集里找不到 {args.instance_id}")
    raise SystemExit("需要 --instance-file 或 --dataset + --instance-id")


def prepare_workspace(instance: dict, workspace: Path) -> None:
    """克隆仓库并 checkout base_commit（本地无 Docker 时的替代方案）。"""
    if (workspace / ".git").exists():
        print(f"工作区已存在：{workspace}")
        return
    repo_url = f"https://github.com/{instance['repo']}.git"
    workspace.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "clone", "--quiet", repo_url, str(workspace)], check=True)
    subprocess.run(["git", "checkout", "--quiet", instance["base_commit"]],
                   cwd=workspace, check=True)


def build_task(instance: dict) -> str:
    return (
        f"Fix the following issue in this repository.\n\n"
        f"{instance['problem_statement']}\n\n"
        f"Work only inside the current directory. Make the smallest change that fixes the issue. "
        f"Do not modify tests. When done, ensure the changes are saved to disk."
    )


def get_patch(workspace: Path) -> str:
    subprocess.run("git add -A", shell=True, cwd=workspace, check=False,
                   capture_output=True)
    r = subprocess.run(
        "git diff --cached --no-color -- . "
        "':(exclude,glob)**/__pycache__/**' ':(exclude,glob)**/*.pyc'",
        shell=True, cwd=workspace, text=True, encoding="utf-8",
        errors="replace", capture_output=True,
    )
    return r.stdout if r.returncode == 0 else ""


def main() -> None:
    ap = argparse.ArgumentParser(description="OpenHands × SWE-bench 适配器")
    ap.add_argument("--repo-dir", default="", help="已有工作区（跳过克隆）")
    ap.add_argument("--dataset", default=str(ROOT / "data/datasets/lite.jsonl"))
    ap.add_argument("--instance-id", default="")
    ap.add_argument("--instance-file", default="")
    ap.add_argument("--task", default="", help="直接给任务（配合 --repo-dir 冒烟）")
    ap.add_argument("--workspace", default="", help="克隆目标目录")
    ap.add_argument("--output-dir", default="")
    ap.add_argument("--timeout", type=int, default=3600)
    args = ap.parse_args()

    if not Path(OPENHANDS_BIN).exists():
        raise SystemExit(f"找不到 OpenHands CLI：{OPENHANDS_BIN}（设 OPENHANDS_BIN 或先安装）")

    if args.repo_dir:
        workspace = Path(args.repo_dir).resolve()
        instance = {"instance_id": "local-smoke", "repo": "local", "base_commit": "HEAD",
                    "problem_statement": args.task or "No task provided."}
        task = args.task or instance["problem_statement"]
    else:
        instance = load_instance(args)
        workspace = Path(args.workspace or ROOT / "data/workspaces" / instance["instance_id"])
        prepare_workspace(instance, workspace)
        task = build_task(instance)

    out_dir = Path(args.output_dir or ROOT / "data/runs/openhands" / instance["instance_id"])
    out_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    cmd = [
        OPENHANDS_BIN, "--headless", "--override-with-envs",
        "--always-approve", "--exit-without-confirmation", "-t", task,
    ]
    print(f"$ {' '.join(cmd[:4])} ...")
    start = time.time()
    try:
        proc = subprocess.run(cmd, cwd=workspace, env=env, text=True, encoding="utf-8",
                              errors="replace", capture_output=True, timeout=args.timeout)
        status = "ok" if proc.returncode == 0 else f"error({proc.returncode})"
    except subprocess.TimeoutExpired as e:
        proc = e
        status = "timeout"
    elapsed = int(time.time() - start)

    (out_dir / "openhands.log").write_text(
        f"status={status} elapsed={elapsed}s\n\n[stdout]\n{getattr(proc, 'stdout', '')}\n"
        f"[stderr]\n{getattr(proc, 'stderr', '')}", encoding="utf-8",
    )
    patch = get_patch(workspace)
    (out_dir / "patch.diff").write_text(patch, encoding="utf-8")
    with open(out_dir / "prediction.jsonl", "w", encoding="utf-8") as f:
        f.write(json.dumps({
            "instance_id": instance["instance_id"],
            "model_name_or_path": os.environ.get("LLM_MODEL", "openhands-local"),
            "model_patch": patch,
        }, ensure_ascii=False) + "\n")

    print(json.dumps({"instance_id": instance["instance_id"], "status": status,
                      "elapsed_seconds": elapsed, "patch_bytes": len(patch)},
                     ensure_ascii=False, indent=2))
    print(f"输出：{out_dir}")


if __name__ == "__main__":
    main()
