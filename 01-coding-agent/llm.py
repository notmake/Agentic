"""LLM 层：Transport × ResponsePolicy 两个正交接缝。

沿用 01_deep_research/llm.py 的设计，换后端只加一个 Transport：

    Transport        怎么把 messages 发给服务（HTTP 协议、鉴权、usage 解析）
      ├─ OpenAICompatTransport   openai SDK（开发机、A800 均可用）
      ├─ UrllibTransport         标准库 urllib（容器内零依赖，方案 B）
      └─ MockTransport           脚本化假模型（离线测试 / --mock）

    ResponsePolicy   怎么把返回的 content 变干净（思考模型污染）
      ├─ plain
      └─ strip_think   剥离  thinking...<｜end▁of▁thinking｜> 与孤立 <｜end▁of▁thinking｜>

纯本地约束：所有 base_url 来自 config.py 的本地后端注册表。
"""

from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from sweagent.actions import actions_from_message
from sweagent.exceptions import FormatError
from sweagent.tools import tool_schemas

# ═════════════════════════════════════════════════════════════════════════
# ResponsePolicy
# ═════════════════════════════════════════════════════════════════════════

THINK_BLOCK = re.compile(r"<think\b[^>]*>.*?</think\s*>", re.DOTALL | re.IGNORECASE)
ORPHAN_THINK_CLOSE = re.compile(r"^.*?<｜end▁of▁thinking｜>", re.DOTALL)


def strip_think(content: str) -> str:
    """剥离思考文本（Qwen3.8-27B 实测：content 混入思考段、只有孤立 <｜end▁of▁thinking｜>）。"""
    content = THINK_BLOCK.sub("", content or "")
    content = ORPHAN_THINK_CLOSE.sub("", content)
    return content.strip()


POLICIES = {"plain": lambda s: s or "", "strip_think": strip_think}


# ═════════════════════════════════════════════════════════════════════════
# Transport
# ═════════════════════════════════════════════════════════════════════════


@dataclass
class RawResponse:
    """传输层统一返回：content / tool_calls / usage / 原始消息。"""

    content: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    raw: dict = field(default_factory=dict)


def _to_wire_messages(messages: list[dict]) -> list[dict]:
    """剥掉内部 extra 字段，得到可发给 OpenAI 兼容接口的消息。"""
    wire = []
    for m in messages:
        w = {k: v for k, v in m.items() if k not in ("extra", "role")}
        w["role"] = m["role"]
        if w.get("content") is None:
            w["content"] = ""
        if "tool_calls" in w:
            w["tool_calls"] = [
                tc if isinstance(tc, dict) else tc.model_dump()
                for tc in w["tool_calls"]
            ]
        wire.append(w)
    return wire


class OpenAICompatTransport:
    """openai SDK 作为 HTTP 客户端（纯本地地址）。"""

    def __init__(self, base_url: str, api_key: str, model: str, max_tokens: int = 4096,
                 temperature: float = 0.0):
        from openai import OpenAI

        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature

    def query(self, messages: list[dict], tools: list[dict] | None = None) -> RawResponse:
        kwargs: dict[str, Any] = {}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=_to_wire_messages(messages),
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            **kwargs,
        )
        msg = resp.choices[0].message.model_dump()
        usage = getattr(resp, "usage", None)
        return RawResponse(
            content=msg.get("content") or "",
            tool_calls=msg.get("tool_calls") or [],
            prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
            raw=msg,
        )


class UrllibTransport:
    """标准库实现（容器内零安装）。接口与 OpenAICompatTransport 一致。"""

    def __init__(self, base_url: str, api_key: str, model: str, max_tokens: int = 4096,
                 temperature: float = 0.0, timeout: int = 600):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.timeout = timeout

    def query(self, messages: list[dict], tools: list[dict] | None = None) -> RawResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": _to_wire_messages(messages),
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        choice = data["choices"][0]["message"]
        usage = data.get("usage") or {}
        return RawResponse(
            content=choice.get("content") or "",
            tool_calls=choice.get("tool_calls") or [],
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            raw=choice,
        )


class MockTransport:
    """脚本化假模型：按 plan 逐步输出动作，离线验证整个 loop。

    plan 元素：命令字符串（默认 bash）或 {"tool","args"} 字典。
    计划耗尽后自动 submit。
    """

    def __init__(self, plan: list[Any], protocol: str = "toolcall", final_summary: str = ""):
        self.plan = list(plan)
        self.protocol = protocol
        self.final_summary = final_summary
        self.idx = 0
        self._call_id = 0

    def query(self, messages: list[dict], tools: list[dict] | None = None) -> RawResponse:
        if self.idx >= len(self.plan):
            action: dict = {"tool": "submit", "args": {"summary": self.final_summary}}
        else:
            item = self.plan[self.idx]
            self.idx += 1
            action = {"tool": "bash", "args": {"command": item}} if isinstance(item, str) else item

        if self.protocol == "toolcall":
            self._call_id += 1
            tc = {
                "id": f"mock-{self._call_id}",
                "type": "function",
                "function": {
                    "name": action["tool"],
                    "arguments": json.dumps(action["args"], ensure_ascii=False),
                },
            }
            return RawResponse(content="", tool_calls=[tc], raw={"content": "", "tool_calls": [tc]})
        command = (
            "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"
            if action["tool"] == "submit"
            else action["args"].get("command", "")
        )
        return RawResponse(
            content=f"执行下一步。\n\n```mswea_bash_command\n{command}\n```",
            raw={"content": ""},
        )


# ═════════════════════════════════════════════════════════════════════════
# LLM 门面
# ═════════════════════════════════════════════════════════════════════════


class LLM:
    """Transport + Policy + 协议 → 一条 assistant 消息（含 actions 与 usage）。"""

    def __init__(
        self,
        transport: Any,
        protocol: str = "toolcall",
        response_policy: str = "plain",
    ):
        self.transport = transport
        self.protocol = protocol
        self.policy = POLICIES.get(response_policy, POLICIES["plain"])

    def query(self, messages: list[dict]) -> dict:
        tools = tool_schemas() if self.protocol == "toolcall" else None
        resp = self.transport.query(messages, tools=tools)

        raw = dict(resp.raw) if resp.raw else {}
        raw["content"] = self.policy(resp.content)
        if resp.tool_calls:
            raw["tool_calls"] = [
                tc if isinstance(tc, dict) else tc.model_dump() for tc in resp.tool_calls
            ]

        try:
            actions = actions_from_message(raw, self.protocol)
        except FormatError as e:
            # 请求已发出、token 已消耗：把 usage 回填到报错消息里再抛（原版 mini-agent 注释原话）
            for m in e.messages:
                m.setdefault("extra", {}).update(
                    {"prompt_tokens": resp.prompt_tokens,
                     "completion_tokens": resp.completion_tokens}
                )
            raise

        return {
            "role": "assistant",
            "content": raw.get("content") or "",
            "tool_calls": raw.get("tool_calls") or [],
            "extra": {
                "actions": actions,
                "prompt_tokens": resp.prompt_tokens,
                "completion_tokens": resp.completion_tokens,
            },
        }
