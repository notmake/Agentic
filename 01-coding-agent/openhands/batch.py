"""OpenHands 批量跑实例（单 GPU 顺序执行，按 instance_id 断点续跑）。

用法：
    export PATH=$HOME/venvs/openhands/bin:$PATH
    export LLM_MODEL=openai/Qwen3.8-27B LLM_BASE_URL=http://127.0.0.1:6790/v1 LLM_API_KEY=local
    python -m openhands.batch --limit 10 --run-id pilot-10

行为：
  - 顺序执行（27B 单服务，并发只会互相拖慢）
  - <run_dir>/<instance_id>/prediction.jsonl 已存在则跳过（--force 重跑）
  - 若镜像不存在，先尝试 docker pull（需 MIRROR，见 scripts/pull_images.sh）
  - 结束后合并 predictions.jsonl，供 eval/harness.py 一次评测
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import load_env  # noqa: E402


def read_ids(dataset: Path, limit: int | None) -> list[str]:
    rows = [json.loads(l) for l in dataset.read_text(encoding="utf-8").splitlines() if l.strip()]
    ids = [r["instance_id"] for r in rows]
    return ids[:limit] if limit else ids


def main() -> None:
    ap = argparse.ArgumentParser(description="OpenHands 批量跑 SWE-bench 实例")
    ap.add_argument("--dataset", default=str(ROOT / "data/datasets/lite.jsonl"))
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--timeout", type=int, default=3600)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--runs-root", default=str(ROOT / "data/runs/openhands-batch"))
    args = ap.parse_args()

    load_env()
    run_dir = Path(args.runs_root) / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    ids = read_ids(Path(args.dataset), args.limit)
    print(f"run_id={args.run_id} 实例数={len(ids)} 顺序执行")

    results = []
    for idx, iid in enumerate(ids, 1):
        out_dir = run_dir / iid
        pred = out_dir / "prediction.jsonl"
        if pred.exists() and not args.force:
            print(f"[{idx}/{len(ids)}] {iid} 已存在，跳过")
            results.append({"instance_id": iid, "status": "skipped"})
            continue
        cmd = [
            sys.executable, "-m", "openhands.run_instance",
            "--dataset", args.dataset, "--instance-id", iid,
            "--from-image", "--output-dir", str(out_dir),
            "--timeout", str(args.timeout),
        ]
        start = time.time()
        proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
        elapsed = int(time.time() - start)
        status = "ok" if proc.returncode == 0 else f"error({proc.returncode})"
        print(f"[{idx}/{len(ids)}] {iid} {status} {elapsed}s")
        (out_dir / "batch_runner.log").write_text(
            f"status={status} elapsed={elapsed}s\n\n{proc.stdout}\n{proc.stderr}",
            encoding="utf-8",
        )
        results.append({"instance_id": iid, "status": status, "elapsed": elapsed})

    merged = run_dir / "predictions.jsonl"
    with open(merged, "w", encoding="utf-8") as out:
        for iid in ids:
            p = run_dir / iid / "prediction.jsonl"
            if p.exists():
                out.write(p.read_text(encoding="utf-8").strip() + "\n")
    (run_dir / "batch_results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    ok = sum(1 for r in results if r["status"] == "ok")
    print(f"\n完成：ok={ok} skipped={sum(1 for r in results if r['status']=='skipped')} "
          f"total={len(results)}\n汇总：{merged}")


if __name__ == "__main__":
    main()
