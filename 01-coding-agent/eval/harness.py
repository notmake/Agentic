"""官方评测封装：swebench==5.0.2（精确锁版）。

用法：
    # gold 哨兵（环境真阳性，W1 验收）：3/3 resolved 才说明数据集/镜像/评分正确
    python eval/harness.py --gold --dataset lite --instances 3

    # 正常评测（run 目录里的汇总 predictions）
    python eval/harness.py --run-dir data/runs/lite-pilot-01 --dataset lite --max-workers 4

设计要点：
  - 数据集 revision 与 harness 版本写进 run 元数据；
  - 官方结果按 run_id + instance_id 缓存：换预测必换 run_id（前置检查兜底）；
  - 5.0.2 起 harness 不再自动拉镜像 → 先跑 scripts/pull_images.sh；
  - clean_images×并发 grader 竞态：默认 cache_level=env，按批串行收尾。
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_official(
    predictions: str,
    run_id: str,
    instance_ids: list[str] | None,
    max_workers: int,
    cache_level: str,
    timeout: int,
) -> int:
    cmd = [
        sys.executable, "-m", "swebench.harness.run_evaluation",
        "--predictions_path", predictions,
        "--run_id", run_id,
        "--max_workers", str(max_workers),
        "--cache_level", cache_level,
        "--timeout", str(timeout),
    ]
    if instance_ids:
        cmd += ["--instance_ids", *instance_ids]
    print("$", " ".join(cmd))
    return subprocess.run(cmd, cwd=ROOT).returncode


def archive_report(run_id: str, dest: Path) -> Path | None:
    """把官方 report.json 归档进 run 目录（新旧日志路径都找）。"""
    candidates = [
        ROOT / "logs" / "run_evaluation" / run_id,
        ROOT / "logs" / "evaluation" / run_id,      # 5.x CHANGELOG 里的新路径
    ]
    for base in candidates:
        if not base.exists():
            continue
        reports = list(base.rglob("report.json"))
        if reports:
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copy2(reports[0], dest / "official_report.json")
            return dest / "official_report.json"
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description="官方 SWE-bench 评测")
    ap.add_argument("--run-dir", default="", help="data/runs/<run_id>")
    ap.add_argument("--predictions", default="", help="predictions.jsonl（与 --run-dir 二选一）")
    ap.add_argument("--run-id", default="")
    ap.add_argument("--dataset", choices=["lite", "verified"], default="lite")
    ap.add_argument("--max-workers", type=int, default=4)
    ap.add_argument("--cache-level", default="env")
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--gold", action="store_true", help="gold 哨兵：官方内建 golden patch 校验")
    ap.add_argument("--instances", type=int, default=3, help="gold 模式取前 N 个实例")
    ap.add_argument("--force", action="store_true", help="允许在已有官方结果的 run_id 上重跑")
    args = ap.parse_args()

    ids_file = ROOT / "data/datasets" / f"{args.dataset}_instance_ids.txt"
    instance_ids = None
    if ids_file.exists():
        instance_ids = [l.strip() for l in ids_file.read_text(encoding="utf-8").splitlines() if l.strip()]

    if args.gold:
        run_id = args.run_id or f"gold-sentinel-{args.dataset}"
        instance_ids = (instance_ids or [])[: args.instances]
        predictions = "gold"
        dest = ROOT / "data/runs" / run_id
    else:
        run_dir = Path(args.run_dir) if args.run_dir else Path(args.predictions).parent
        run_id = args.run_id or run_dir.name
        predictions = args.predictions or str(run_dir / "predictions.jsonl")
        dest = run_dir
        if not Path(predictions).exists():
            raise SystemExit(f"找不到 predictions：{predictions}（先跑 runner/batch.py）")
        if dest.joinpath("official_report.json").exists() and not args.force:
            raise SystemExit("该 run_id 已有官方结果，换 run_id（缓存按 run_id 记账）或加 --force")

    rc = run_official(predictions, run_id, instance_ids, args.max_workers,
                      args.cache_level, args.timeout)
    report = archive_report(run_id, dest)
    print(f"\n官方报告：{report or '未找到（检查 logs/ 路径）'}")
    raise SystemExit(rc)


if __name__ == "__main__":
    main()
