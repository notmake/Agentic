"""补丁提取与预校验。

设计要点（来自 notes/00_学习.md）：
  - 输出物是 git diff：可审查、可回滚、可评测；
  - 提交前先做 `git apply --check`：把"补丁不可用"从评测期失败变成 loop 内可恢复信号；
  - 新文件必须 `git add -A` 才进 diff（否则评测丢文件）。
"""

from __future__ import annotations

# 在容器/仓库内执行的命令：暂存全部改动（含 untracked），输出可被 git apply 的补丁
DIFF_COMMAND = "cd /testbed && git add -A && git diff --cached --no-color"

# 预校验：在干净的 base_commit 工作树上试应用
CHECK_COMMAND_TEMPLATE = (
    "cd /testbed && rm -rf /tmp/_patch_check && "
    "git worktree add --detach /tmp/_patch_check {base_commit} >/dev/null 2>&1 && "
    "git -C /tmp/_patch_check apply --check /tmp/_candidate.patch; "
    "rc=$?; git worktree remove --force /tmp/_patch_check >/dev/null 2>&1; exit $rc"
)


def looks_like_diff(text: str) -> bool:
    return "diff --git" in text


def extract_patch_from_tool_output(output: str) -> str:
    """从 bash 输出里截出 git diff 正文（容忍前后有噪声行）。"""
    idx = output.find("diff --git")
    if idx < 0:
        return ""
    return output[idx:].rstrip() + "\n"
