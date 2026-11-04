"""工具注册表：工具 schema 与参数校验的唯一来源。

V1 四件套（数据驱动原则：LOCATE 类失败占比高才在 V1.1 加 search/str_replace）：

    bash    执行任意 shell 命令（主武器）
    view    带行号查看文件（读代码，避免 cat 无行号）
    write   全量写文件（写代码；多行内容不进 shell 转义，规避本地模型高频失败点）
    submit  提交并结束

text 协议（本地小模型没有 tool_calls）固定降级为 bash-only，见 actions.py。
"""

from __future__ import annotations

from typing import Any

TOOL_SCHEMAS: dict[str, dict] = {
    "bash": {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "Execute a bash command in the repository. Each call runs in a fresh subshell.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The bash command to execute"},
                },
                "required": ["command"],
            },
        },
    },
    "view": {
        "type": "function",
        "function": {
            "name": "view",
            "description": "View a file with line numbers. Optionally limit to a line range.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path relative to the repository root"},
                    "start_line": {"type": "integer", "description": "1-based start line (optional)"},
                    "end_line": {"type": "integer", "description": "1-based end line (optional)"},
                },
                "required": ["path"],
            },
        },
    },
    "write": {
        "type": "function",
        "function": {
            "name": "write",
            "description": "Create or overwrite a file with the given content. Parent directories are created.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path relative to the repository root"},
                    "content": {"type": "string", "description": "Full file content"},
                },
                "required": ["path", "content"],
            },
        },
    },
    "submit": {
        "type": "function",
        "function": {
            "name": "submit",
            "description": "Submit your changes and finish the task. Call this only after you verified your fix.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "Short summary of what you changed"},
                },
                "required": ["summary"],
            },
        },
    },
}

# text 协议只允许 bash
TEXT_PROTOCOL_TOOLS = ("bash",)

# 参数校验规则：必填字段 + 类型
_REQUIRED: dict[str, dict[str, type]] = {
    "bash": {"command": str},
    "view": {"path": str},
    "write": {"path": str, "content": str},
    "submit": {"summary": str},
}

_OPTIONAL: dict[str, dict[str, type]] = {
    "view": {"start_line": int, "end_line": int},
}


def tool_schemas() -> list[dict]:
    """给 OpenAI 兼容接口的 tools 参数。"""
    return list(TOOL_SCHEMAS.values())


def validate_tool_call(name: str, args: Any) -> str | None:
    """校验一个工具调用，返回错误信息（None = 合法）。

    只做结构校验；语义（文件是否存在等）由 environment 执行时反馈。
    """
    if name not in TOOL_SCHEMAS:
        return f"Unknown tool {name!r}. Available tools: {', '.join(TOOL_SCHEMAS)}."
    if not isinstance(args, dict):
        return f"Arguments for {name!r} must be a JSON object, got {type(args).__name__}."

    for field_name, field_type in _REQUIRED.get(name, {}).items():
        if field_name not in args:
            return f"Missing required argument {field_name!r} for {name!r}."
        if not isinstance(args[field_name], field_type):
            return f"Argument {field_name!r} must be {field_type.__name__}, got {type(args[field_name]).__name__}."

    for field_name, field_type in _OPTIONAL.get(name, {}).items():
        if field_name in args and not isinstance(args[field_name], field_type):
            return f"Argument {field_name!r} must be {field_type.__name__}, got {type(args[field_name]).__name__}."

    if name == "bash" and not args["command"].strip():
        return "The 'command' argument must not be empty."
    return None
