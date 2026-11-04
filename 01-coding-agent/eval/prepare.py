"""数据集准备：下载（pin revision）+ schema 校验 + 分层采样清单。

用法：
    python eval/prepare.py --dataset lite --limit 5
    python eval/prepare.py --dataset lite          # 全量 300
    python eval/prepare.py --dataset verified      # 500（需磁盘/时间预算）

产出（data/datasets/）：
    <dataset>.jsonl             每行一个实例（只保留 agent 需要的字段 + 评测字段）
    <dataset>_instance_ids.txt  实例 id 清单（pull_images.sh / batch.py 用）
    <dataset>_meta.json         dataset id + revision SHA + 时间（可复现性三件套之一）
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 5.x 数据集别名（CLI 把 lite 映射到新 org 命名空间；不硬编码旧 princeton-nlp）
DATASET_ALIASES = {
    "lite": ["SWE-bench/SWE-bench_Lite", "princeton-nlp/SWE-bench_Lite"],
    "verified": ["SWE-bench/SWE-bench_Verified", "princeton-nlp/SWE-bench_Verified"],
}

REQUIRED_FIELDS = [
    "instance_id", "repo", "base_commit", "problem_statement",
    "FAIL_TO_PASS", "PASS_TO_PASS",
]


def resolve_dataset(name: str, revision: str | None):
    from datasets import load_dataset

    errors = []
    for repo_id in DATASET_ALIASES[name]:
        try:
            ds = load_dataset(repo_id, split="test", revision=revision)
            return repo_id, ds
        except Exception as e:  # noqa: BLE001
            errors.append(f"{repo_id}: {e}")
    raise SystemExit("数据集加载失败：\n" + "\n".join(errors))


def resolved_revision(repo_id: str) -> str:
    """拿数据集当前 revision SHA（写进 run 元数据，防悄悄漂移）。"""
    try:
        from huggingface_hub import dataset_info

        return dataset_info(repo_id).sha or "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


def validate_row(row: dict, index: int) -> None:
    missing = [f for f in REQUIRED_FIELDS if f not in row]
    if missing:
        raise SystemExit(f"第 {index} 行缺字段：{missing}")
    # F2P / P2P 在数据集里是 JSON 编码字符串
    for field in ("FAIL_TO_PASS", "PASS_TO_PASS"):
        value = row[field]
        parsed = json.loads(value) if isinstance(value, str) else value
        if not isinstance(parsed, list):
            raise SystemExit(f"{row['instance_id']}: {field} 不是列表")
    if not str(row["base_commit"]).strip():
        raise SystemExit(f"{row['instance_id']}: base_commit 为空")


def stratified_sample(rows: list[dict], limit: int) -> list[dict]:
    """按 repo 轮转采样：优先覆盖多个仓库，而不是全挤在同一个 repo。"""
    by_repo: dict[str, list[dict]] = {}
    for r in rows:
        by_repo.setdefault(r["repo"], []).append(r)
    picked: list[dict] = []
    while len(picked) < limit and any(by_repo.values()):
        for repo in list(by_repo):
            if by_repo[repo]:
                picked.append(by_repo[repo].pop(0))
                if len(picked) >= limit:
                    break
    return picked


def main() -> None:
    ap = argparse.ArgumentParser(description="准备 SWE-bench 数据集")
    ap.add_argument("--dataset", choices=list(DATASET_ALIASES), default="lite")
    ap.add_argument("--limit", type=int, default=None, help="分层采样数量（默认全量）")
    ap.add_argument("--revision", default=os.environ.get("SWE_DATASET_REVISION") or None)
    ap.add_argument("--out-dir", default=str(ROOT / "data/datasets"))
    args = ap.parse_args()

    os.environ.setdefault("HF_ENDPOINT", os.environ.get("HF_ENDPOINT", "https://hf-mirror.com"))

    repo_id, ds = resolve_dataset(args.dataset, args.revision)
    rows = [dict(r) for r in ds]
    for i, row in enumerate(rows):
        validate_row(row, i)

    if args.limit:
        rows = stratified_sample(rows, args.limit)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = out_dir / f"{args.dataset}.jsonl"
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    ids_path = out_dir / f"{args.dataset}_instance_ids.txt"
    ids_path.write_text("\n".join(r["instance_id"] for r in rows) + "\n", encoding="utf-8")

    meta = {
        "dataset": args.dataset,
        "repo_id": repo_id,
        "revision_requested": args.revision,
        "revision_sha": resolved_revision(repo_id),
        "n_instances": len(rows),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    (out_dir / f"{args.dataset}_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(meta, ensure_ascii=False, indent=2))
    print(f"实例清单: {jsonl_path}")


if __name__ == "__main__":
    main()
