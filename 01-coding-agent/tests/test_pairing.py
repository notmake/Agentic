# -*- coding: utf-8 -*-
"""配对约束回归测试（对抗审查发现的两个正确性 bug）。

1. TokenBudget 压缩必须整步丢弃，不能产生孤儿 tool 消息；
2. FormatError 回灌必须用 role=tool + 原 tool_call_id；
3. 思考模型 content 为空但 tool_calls 合法时，必须正常解析。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sweagent.actions import actions_from_message
from sweagent.exceptions import FormatError
from sweagent.token_budget import TokenBudget


def _tool_call(tcid: str, name: str = "bash", args: str = '{"command": "ls"}') -> dict:
    return {"id": tcid, "type": "function", "function": {"name": name, "arguments": args}}


def test_empty_content_with_tool_calls_is_valid():
    raw = {"content": "", "tool_calls": [_tool_call("call_1")]}
    actions = actions_from_message(raw, "toolcall")
    assert actions == [{"tool": "bash", "args": {"command": "ls"}, "tool_call_id": "call_1"}]


def test_format_error_uses_tool_role_and_same_ids():
    raw = {"content": "", "tool_calls": [_tool_call("call_1", args="not-json")]}
    try:
        actions_from_message(raw, "toolcall")
    except FormatError as e:
        assert len(e.messages) == 1
        msg = e.messages[0]
        assert msg["role"] == "tool"
        assert msg["tool_call_id"] == "call_1"
    else:
        raise AssertionError("应当抛 FormatError")


def test_multiple_bad_tool_calls_get_one_error_each():
    raw = {"content": "", "tool_calls": [
        _tool_call("c1", name="bash", args="{}"),
        _tool_call("c2", name="nope", args="{}"),
    ]}
    try:
        actions_from_message(raw, "toolcall")
    except FormatError as e:
        assert [m["tool_call_id"] for m in e.messages] == ["c1", "c2"]
        assert all(m["role"] == "tool" for m in e.messages)
    else:
        raise AssertionError("应当抛 FormatError")


def test_compression_drops_whole_steps_only():
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "task"},
    ]
    for i in range(10):
        messages.append({
            "role": "assistant",
            "content": "",
            "tool_calls": [_tool_call(f"call_{i}")],
            "extra": {"actions": [{"tool": "bash", "args": {"command": f"cmd{i}"}, "tool_call_id": f"call_{i}"}]},
        })
        messages.append({"role": "tool", "tool_call_id": f"call_{i}", "content": f"out{i}"})

    budget = TokenBudget(keep_recent_steps=3)
    compressed = budget.compress(messages)

    # 头部保留
    assert compressed[0]["role"] == "system"
    assert compressed[1]["role"] == "user"
    # 摘要之后，assistant / tool 必须成对且 id 对应
    body = [m for m in compressed[2:] if m.get("role") in ("assistant", "tool")]
    for i in range(0, len(body), 2):
        assert body[i]["role"] == "assistant", f"第 {i} 条不是 assistant：{body[i]['role']}"
        assert body[i + 1]["role"] == "tool"
        assert body[i + 1]["tool_call_id"] == body[i]["tool_calls"][0]["id"]
    # 且只保留最近 3 个完整 step
    assert sum(1 for m in compressed if m["role"] == "assistant") == 3
