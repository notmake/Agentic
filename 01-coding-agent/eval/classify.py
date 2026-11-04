"""失败分类：七类互斥 + PATCH_ERROR 二级标签。

七类（优先级从上到下，先命中先归类）：
    TEST_ENV_ERROR   镜像/沙箱/评测环境故障（不是模型的锅）
    ENV_ERROR        未分类异常
    FORMAT_ERROR     连续输出格式错误
    LIMIT_ERROR      步数/时间触顶
    LOCATE_ERROR     没定位到问题（空补丁 / 大量探索无修改）
    PATCH_ERROR      补丁没解决问题（5a-5e 二级标签）
    RESOLVED         官方判定 resolved

用法：
    python eval/classify.py --run-dir data/runs/lite-pilot-01
产出：每个实例目录 classification.json + run 级 classifications.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

TEST_COMMAND = re.compile(r"\b(pytest|python -m pytest|unittest|tox|nox|runtests?)\b")


def load_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default if default is not None else {}


def find_official_report(run_dir: Path) -> dict:
    """官方 report.json 结构随版本变化，统一成 {instance_id: {...}}。"""
    for candidate in (run_dir / "official_report.json",):
        data = load_json(candidate, {})
        if not data:
            continue
        # 老格式 {model: {iid: {...}}} / 新格式 {iid: {...}}
        if all(isinstance(v, dict) for v in data.values()) and not any(
            "resolved" in v or "patch_successfully_applied" in v for v in data.values()
        ):
            merged: dict = {}
            for model_result in data.values():
                if isinstance(model_result, dict):
                    merged.update(model_result)
            return merged
        return data
    return {}


def ran_tests(history: list[dict]) -> bool:
    for m in history:
        for a in m.get("extra", {}).get("actions", []):
            cmd = a.get("args", {}).get("command", "")
            if TEST_COMMAND.search(cmd or ""):
                return True
    return False


def classify_instance(inst_dir: Path, official: dict) -> dict:
    traj = load_json(inst_dir / "trajectory.json", {})
    info = traj.get("info", {})
    history = traj.get("messages", [])
    iid = info.get("instance_id") or inst_dir.name

    exit_status = info.get("exit_status", "")
    prediction = {}
    pred_file = inst_dir / "prediction.jsonl"
    if pred_file.exists():
        prediction = json.loads(pred_file.read_text(encoding="utf-8").splitlines()[0])
    patch = prediction.get("model_patch", "")
    result = official.get(iid, {})
    resolved = bool(result.get("resolved", False))
    applied = result.get("patch_successfully_applied", None)

    base = {"instance_id": iid, "exit_status": exit_status,
            "patch_empty": not patch.strip(), "resolved": resolved}

    if resolved:
        return {**base, "category": "RESOLVED", "sublabel": "", "reason": "官方判定 resolved"}
    if exit_status == "SandboxError":
        return {**base, "category": "TEST_ENV_ERROR", "sublabel": "",
                "reason": "沙箱/镜像故障"}
    if exit_status == "Exception":
        return {**base, "category": "ENV_ERROR", "sublabel": "",
                "reason": "未捕获异常，见 trajectory exit 消息"}
    if exit_status == "RepeatedFormatError":
        return {**base, "category": "FORMAT_ERROR", "sublabel": "",
                "reason": "连续输出格式错误"}
    if exit_status in ("LimitsExceeded", "TimeExceeded"):
        return {**base, "category": "LIMIT_ERROR", "sublabel": exit_status,
                "reason": "步数/时间触顶"}
    if applied is False:
        return {**base, "category": "TEST_ENV_ERROR", "sublabel": "patch_apply_failed",
                "reason": "官方评测未能应用补丁（环境或补丁格式）"}
    if not patch.strip():
        # 空补丁：探索很多 → 没定位到；探索很少 → 模型直接放弃
        n_assistant = sum(1 for m in history if m.get("role") == "assistant")
        cat = "LOCATE_ERROR" if n_assistant >= 5 else "PATCH_ERROR"
        return {**base, "category": cat,
                "sublabel": "" if cat == "LOCATE_ERROR" else "5b_never_tested",
                "reason": f"空补丁，模型调用 {n_assistant} 次"}

    sublabel = "5d_partial_f2p"
    reason = "补丁未解决全部 FAIL_TO_PASS"
    tests_status = result.get("tests_status", {}) if isinstance(result, dict) else {}
    if tests_status:
        p2p = tests_status.get("PASS_TO_PASS", {})
        f2p = tests_status.get("FAIL_TO_PASS", {})
        if p2p.get("failure"):
            sublabel, reason = "5e_p2p_regression", "破坏了原本通过的测试"
        elif f2p.get("success"):
            sublabel, reason = "5d_partial_f2p", "只修好部分 FAIL_TO_PASS"
    if not ran_tests(history):
        sublabel = "5b_never_tested"
        reason = "整个轨迹没有运行过测试"
    return {**base, "category": "PATCH_ERROR", "sublabel": sublabel, "reason": reason}


def main() -> None:
    ap = argparse.ArgumentParser(description="失败分类")
    ap.add_argument("--run-dir", required=True)
    args = ap.parse_args()

    run_dir = Path(args.run_dir)
    official = find_official_report(run_dir)
    rows = []
    for inst_dir in sorted(p for p in run_dir.iterdir() if p.is_dir()):
        row = classify_instance(inst_dir, official)
        (inst_dir / "classification.json").write_text(
            json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        rows.append(row)

    out = run_dir / "classifications.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["instance_id"])
        w.writeheader()
        w.writerows(rows)

    from collections import Counter
    counts = Counter(r["category"] for r in rows)
    print(json.dumps(dict(counts), ensure_ascii=False, indent=2))
    print(f"分类结果: {out}")


if __name__ == "__main__":
    main()
