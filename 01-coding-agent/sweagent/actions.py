"""把模型输出解析成可执行的 action 列表。

两种协议：
  toolcall  模型通过原生工具调用输出（A800 vLLM --enable-auto-tool-choice）
  text      模型在 ```mswea_bash_command``` 代码块里输出命令（4B/GGUF 无工具调用时兜底）

关键约束（对抗审查发现的配对 bug，回归测试见 tests/test_pairing.py）：
  1. assistant 消息一旦带 tool_calls，后续每条 tool 结果/错误必须带同一个 tool_call_id；
  2. 解析失败也要按 tool 角色回灌，不能用 role=user 污染配对；
  3. content 为空但 tool_calls 合法 → 正常继续（思考模型的空 content 坑）。
"""

from __future__ import annotations

import json
import re
from typing import Any

from sweagent.exceptions import FormatError
from sweagent.tools import TEXT_PROTOCOL_TOOLS, validate_tool_call

ACTION_REGEX = r"```mswea_bash_command\s*\n(.*?)\n```"
SUBMIT_SENTINEL = "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"


def parse_tool_calls(tool_calls: list[Any]) -> list[dict]:
    """[toolcall 协议] 校验工具调用 → action 列表。失败抛带 tool 角色消息的 FormatError。"""
    if not tool_calls:
        raise FormatError.for_text(
            "No tool calls found in the response. Every response MUST include at least one tool call."
        )

    actions: list[dict] = []
    errors: list[str] = []
    ids: list[str] = []
    for tc in tool_calls:
        tcid = getattr(tc, "id", None) or (tc.get("id") if isinstance(tc, dict) else "") or ""
        fn = getattr(tc, "function", None) or (tc.get("function") if isinstance(tc, dict) else None)
        name = getattr(fn, "name", None) or (fn.get("name") if isinstance(fn, dict) else "")
        raw_args = getattr(fn, "arguments", None) or (fn.get("arguments") if isinstance(fn, dict) else "")

        if fn is None or not name:
            errors.append("Malformed tool call (missing function name).")
            ids.append(tcid)
            continue
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
        except Exception as e:  # noqa: BLE001
            errors.append(f"Error parsing arguments for {name!r}: {e}.")
            ids.append(tcid)
            continue

        err = validate_tool_call(name, args)
        if err:
            errors.append(err)
            ids.append(tcid)
            continue

        actions.append({"tool": name, "args": args, "tool_call_id": tcid})

    if errors:
        raise FormatError.for_tool_calls(errors, ids)
    return actions


def parse_text_actions(content: str) -> list[dict]:
    """[text 协议] 从文本里抓 bash 命令，必须恰好 1 条。"""
    commands = [a.strip() for a in re.findall(ACTION_REGEX, content or "", re.DOTALL)]
    if len(commands) != 1:
        raise FormatError.for_text(
            f"Format error: expected exactly 1 command in a ```mswea_bash_command``` code block, "
            f"found {len(commands)}. Please retry in the required format."
        )
    command = commands[0]
    return [{"tool": "bash", "args": {"command": command}}]


def actions_from_message(raw: dict, protocol: str) -> list[dict]:
    """统一入口：assistant 原始消息 → actions。

    raw 是 model_dump 后的 dict：{content, tool_calls, ...}
    注意：先看 tool_calls，再看 content —— 思考模型可能出现 content 为空、只有 tool_calls。
    """
    if protocol == "toolcall":
        tool_calls = raw.get("tool_calls") or []
        if tool_calls:
            return parse_tool_calls(tool_calls)
        # 没有 tool_calls，但正文可能是 text 格式（模型退化成文本输出）→ 尝试兜底
        if raw.get("content"):
            try:
                return parse_text_actions(raw["content"])
            except FormatError:
                pass
        raise FormatError.for_text(
            "No tool calls found in the response. Every response MUST include at least one tool call."
        )

    return parse_text_actions(raw.get("content") or "")


def is_submit_action(action: dict) -> bool:
    """submit 工具 或 文本协议里的哨兵命令，都视为提交。"""
    if action.get("tool") == "submit":
        return True
    if action.get("tool") == "bash":
        cmd = action["args"].get("command", "").strip()
        return cmd == SUBMIT_SENTINEL
    return False


def check_text_protocol_tool(action: dict) -> None:
    """text 协议只允许 bash（写死约束，防止模型调用不存在的工具）。"""
    if action.get("tool") not in TEXT_PROTOCOL_TOOLS:
        raise FormatError.for_text(
            f"Tool {action.get('tool')!r} is not available in text protocol. Only 'bash' is allowed."
        )
