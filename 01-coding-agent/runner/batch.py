"""批量调度：多实例并发 + 按 instance_id 断点续跑 + 汇总 predictions。

用法：
    python -m runner.batch --backend a800_27b --run-id lite-pilot-01 \
        --dataset data/datasets/lite.jsonl --limit 20 --workers 4

断点续跑：<run_dir>/<instance_id>/prediction.jsonl 已存在则跳过（--force 重跑）。
单实例失败不影响其他实例：每个子进程独立，退出码非零只记录不中断。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import load_env  # noqa: E402


def read_instance_ids(dataset: Path, limit: int | None = None) -> list[str]:
    ids: list[str] = []
    with open(dataset, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                ids.append(json.loads(line)["instance_id"])
    return ids[:limit] if limit else ids


def run_one(instance_id: str, args: argparse.Namespace, run_dir: Path) -> dict:
    inst_dir = run_dir / instance_id
    prediction = inst_dir / "prediction.jsonl"
    if prediction.exists() and not args.force:
        return {"instance_id": instance_id, "status": "skipped"}

    cmd = [
        sys.executable, "-m", "runner.run_instance",
        "--backend", args.backend,
        "--dataset", args.dataset,
        "--instance-id", instance_id,
        "--output-dir", str(inst_dir),
    ]
    if args.protocol:
        cmd += ["--protocol", args.protocol]
    start = time.time()
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    (inst_dir / "runner.log").parent.mkdir(parents=True, exist_ok=True)
    (inst_dir / "runner.log").write_text(
        f"$ {' '.join(cmd)}\n\n[stdout]\n{proc.stdout}\n[stderr]\n{proc.stderr}",
        encoding="utf-8",
    )
    return {
        "instance_id": instance_id,
        "status": "ok" if proc.returncode == 0 else f"error({proc.returncode})",
        "elapsed": round(time.time() - start, 1),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="批量跑 SWE-bench 实例")
    ap.add_argument("--backend", required=True)
    ap.add_argument("--protocol", default=None)
    ap.add_argument("--dataset", default=str(ROOT / "data/datasets/lite.jsonl"))
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--runs-root", default=str(ROOT / "data/runs"))
    args = ap.parse_args()

    load_env()
    run_dir = Path(args.runs_root) / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    instance_ids = read_instance_ids(Path(args.dataset), args.limit)
    if not instance_ids:
        raise SystemExit(f"数据集为空：{args.dataset}（先跑 eval/prepare.py）")
    print(f"run_id={args.run_id} 实例数={len(instance_ids)} 并发={args.workers}")
    (run_dir / "run_config.json").write_text(
        json.dumps(vars(args), ensure_ascii=False, indent=2), encoding="utf-8"
    )

    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(run_one, iid, args, run_dir): iid for iid in instance_ids}
        for fut in as_completed(futures):
            r = fut.result()
            results.append(r)
            print(f"[{len(results)}/{len(instance_ids)}] {r['instance_id']} {r['status']} "
                  f"{r.get('elapsed', '')}s")

    # 汇总 predictions（官方三字段）
    merged = run_dir / "predictions.jsonl"
    with open(merged, "w", encoding="utf-8") as out:
        for inst_dir in sorted(run_dir.iterdir()):
            pred = inst_dir / "prediction.jsonl"
            if pred.is_file():
                out.write(pred.read_text(encoding="utf-8").strip() + "\n")
    (run_dir / "batch_results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n完成：{len([r for r in results if r['status'] != 'skipped'])} 个，"
          f"汇总 predictions: {merged}")


if __name__ == "__main__":
    main()
