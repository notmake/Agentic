"""异常家族 —— 复用并扩展 mini-agent-v0.1 的设计。

原版要点：异常不只用来"报错"，还用来"携带消息 + 打断主循环"。
主循环统一 except InterruptAgentFlow，把异常自带的 messages 追加进对话。

扩展：
  SandboxError   容器/环境层故障（镜像不在、exec 失败），与"模型犯错"区分开
  FormatError.tool_messages()  按 tool_call_id 构造合法的 tool 角色回灌（配对约束）
"""

from __future__ import annotations


class InterruptAgentFlow(Exception):
    """抛出即打断主循环，并把自带的 messages 追加进对话。"""

    def __init__(self, *messages: dict):
        self.messages = messages
        super().__init__()

    @classmethod
    def for_text(cls, message: str) -> "InterruptAgentFlow":
        """用 role=user 的一条消息回灌（仅用于没有 tool_call_id 可配对的场景）。"""
        return cls(
            {
                "role": "user",
                "content": message,
                "extra": {"interrupt_type": cls.__name__},
            }
        )


class Submitted(InterruptAgentFlow):
    """任务完成，携带最终提交内容。"""


class LimitsExceeded(InterruptAgentFlow):
    """超过步数 / token 预算上限。"""


class TimeExceeded(LimitsExceeded):
    """超过墙钟时间上限。"""


class FormatError(InterruptAgentFlow):
    """模型输出不是合法格式（没给工具调用/参数不合法/多工具校验失败）。

    构造约定：
      FormatError.for_tool_calls(errors)  → 每个失败的工具调用回一条 role=tool 消息
      FormatError.for_text(message)       → 文本协议用 role=user 消息
    这样 assistant(tool_calls) 后面永远跟同 id 的 tool 消息，满足 OpenAI 兼容协议，
    不会让 vLLM 报 400（对抗审查发现的配对 bug，见 tests/test_pairing.py）。
    """

    @classmethod
    def for_tool_calls(cls, errors: list[str], tool_call_ids: list[str]) -> "FormatError":
        msgs = []
        for err, tcid in zip(errors, tool_call_ids):
            msgs.append(
                {
                    "role": "tool",
                    "tool_call_id": tcid,
                    "content": f"Tool call error: {err}",
                    "extra": {"interrupt_type": "FormatError"},
                }
            )
        return cls(*msgs)


class SandboxError(InterruptAgentFlow):
    """环境层故障：镜像缺失、容器起不来、exec 超时等。

    与 FormatError 分开，是为了让失败分类能区分"模型不行"和"环境不行"。
    """


def exit_message(status: str, submission: str = "", **extra) -> dict:
    """构造一条 role=='exit' 的消息。主循环看到它就 break。"""
    payload = {"exit_status": status, "submission": submission, **extra}
    return {"role": "exit", "content": status, "extra": payload}
