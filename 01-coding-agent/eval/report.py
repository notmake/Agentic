"""run 级报告：解决率 / 失败分布 / 效率指标 / 按 repo 分表。

用法：
    python eval/report.py --run-dir data/runs/lite-pilot-01
产出：<run_dir>/report.md + <run_dir>/summary.csv
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def main() -> None:
    ap = argparse.ArgumentParser(description="生成 run 报告")
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--dataset", default=str(ROOT / "data/datasets/lite.jsonl"))
    args = ap.parse_args()

    run_dir = Path(args.run_dir)
    classifications = read_csv(run_dir / "classifications.csv")

    dataset_meta = {}
    meta_file = Path(args.dataset).with_name(Path(args.dataset).stem + "_meta.json")
    if meta_file.exists():
        dataset_meta = json.loads(meta_file.read_text(encoding="utf-8"))
    repo_of = {}
    if Path(args.dataset).exists():
        for row in read_jsonl(Path(args.dataset)):
            repo_of[row["instance_id"]] = row.get("repo", "?")

    # 每个实例的轨迹 info（步数/token/耗时）
    stats = {}
    for inst_dir in sorted(p for p in run_dir.iterdir() if p.is_dir()):
        traj = inst_dir / "trajectory.json"
        if traj.exists():
            info = json.loads(traj.read_text(encoding="utf-8")).get("info", {})
            stats[info.get("instance_id", inst_dir.name)] = info

    n = len(classifications)
    resolved = sum(1 for r in classifications if r["category"] == "RESOLVED")
    counts = Counter(r["category"] for r in classifications)
    subcounts = Counter(r["sublabel"] for r in classifications if r.get("sublabel"))
    by_repo: dict[str, list[dict]] = defaultdict(list)
    for r in classifications:
        by_repo[repo_of.get(r["instance_id"], "?")].append(r)

    def pct(a: int, b: int) -> str:
        return f"{100 * a / b:.1f}%" if b else "-"

    lines = [
        f"# Run report: {run_dir.name}", "",
        f"- 实例数：{n}",
        f"- **解决率：{resolved}/{n} = {pct(resolved, n)}**",
        f"- 数据集：{dataset_meta.get('repo_id', '?')} "
        f"@ {dataset_meta.get('revision_sha', '?')[:12]}",
        "", "## 失败分类", "", "| 类别 | 数量 | 占比 |", "|---|---:|---:|",
    ]
    for cat, c in counts.most_common():
        lines.append(f"| {cat} | {c} | {pct(c, n)} |")
    if subcounts:
        lines += ["", "### PATCH_ERROR 二级标签", "", "| 标签 | 数量 |", "|---|---:|"]
        for sub, c in subcounts.most_common():
            lines.append(f"| {sub} | {c} |")
    if by_repo:
        lines += ["", "## 按仓库", "", "| repo | 实例 | 解决 | 解决率 |", "|---|---:|---:|---:|"]
        for repo, rows in sorted(by_repo.items()):
            r = sum(1 for x in rows if x["category"] == "RESOLVED")
            lines.append(f"| {repo} | {len(rows)} | {r} | {pct(r, len(rows))} |")
    if stats:
        avg_calls = sum(s.get("n_calls", 0) for s in stats.values()) / len(stats)
        avg_tok = sum(s.get("prompt_tokens", 0) + s.get("completion_tokens", 0)
                      for s in stats.values()) / len(stats)
        avg_sec = sum(s.get("elapsed_seconds", 0) for s in stats.values()) / len(stats)
        lines += ["", "## 效率", "",
                  f"- 平均模型调用：{avg_calls:.1f} 次/实例",
                  f"- 平均 token：{avg_tok:,.0f}/实例",
                  f"- 平均耗时：{avg_sec:.0f}s/实例"]

    report = "\n".join(lines) + "\n"
    (run_dir / "report.md").write_text(report, encoding="utf-8")

    with open(run_dir / "summary.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["instance_id", "repo", "category", "sublabel", "resolved",
                    "exit_status", "n_calls", "prompt_tokens", "completion_tokens",
                    "elapsed_seconds"])
        for r in classifications:
            s = stats.get(r["instance_id"], {})
            w.writerow([r["instance_id"], repo_of.get(r["instance_id"], "?"),
                        r["category"], r.get("sublabel", ""), r["resolved"],
                        r["exit_status"], s.get("n_calls", ""), s.get("prompt_tokens", ""),
                        s.get("completion_tokens", ""), s.get("elapsed_seconds", "")])

    print(report)
    print(f"报告: {run_dir / 'report.md'}")


if __name__ == "__main__":
    main()
