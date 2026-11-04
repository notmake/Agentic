"""Token 预算：消息级账本 + 整步压缩。

移植自 02_React_Agent/token_budget.py，做了两处关键升级（对抗审查要求）：

1. 账本用后端返回的真实 usage（prompt_tokens），不再按字符估算；
2. 压缩必须**对齐 step 边界**——一个 step = 1 条 assistant + 它引发的所有 tool/user 观测。
   朴素头尾截断会产生孤儿 tool 消息，vLLM 直接 400。这里整步丢弃，配对永不断。

压缩策略（确定性，不额外调用模型）：
    system + 任务原文 + [历史压缩摘要] + 最近 keep_recent_steps 个完整 step
摘要由被丢弃步骤的命令/结果首行拼接而成，保持可追溯。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TokenBudget:
    context_window: int = 32_768
    trigger_ratio: float = 0.80
    keep_recent_steps: int = 6
    system_and_task_tokens: int = 0     # 由 agent 在首轮填充
    summary: str = ""                   # 滚动摘要（跨多次压缩累积）
    n_compressions: int = 0
    n_dropped_steps: int = 0
    dropped_tokens_estimate: int = 0
    _last_prompt_tokens: int = field(default=0, repr=False)

    # ── 账本 ──
    def update_from_usage(self, prompt_tokens: int) -> None:
        """每次 API 返回后调用。vLLM 的 usage.prompt_tokens 是真实值。"""
        self._last_prompt_tokens = prompt_tokens

    def should_compress(self, prompt_tokens: int | None = None) -> bool:
        used = prompt_tokens if prompt_tokens is not None else self._last_prompt_tokens
        return used >= int(self.context_window * self.trigger_ratio)

    # ── 分组 ──
    @staticmethod
    def split_steps(messages: list[dict]) -> tuple[list[dict], list[list[dict]]]:
        """返回 (头部[system+任务], steps)。每个 step 以 assistant 消息开头。"""
        head = messages[:2]
        rest = messages[2:]
        steps: list[list[dict]] = []
        for m in rest:
            if m.get("role") == "assistant" or not steps:
                steps.append([m])
            else:
                steps[-1].append(m)
        return head, steps

    # ── 压缩 ──
    def compress(self, messages: list[dict]) -> list[dict]:
        """丢弃最老的 step，保留最近 keep_recent_steps 个完整 step。"""
        head, steps = self.split_steps(messages)
        if len(steps) <= self.keep_recent_steps:
            return messages

        dropped = steps[: -self.keep_recent_steps]
        kept = steps[-self.keep_recent_steps :]

        lines = [self.summary] if self.summary else []
        lines.append(f"[历史压缩] 已省略 {len(dropped)} 个早期步骤，关键记录如下：")
        for step in dropped:
            for m in step:
                if m.get("role") == "assistant":
                    for a in m.get("extra", {}).get("actions", []):
                        name = a.get("tool", "?")
                        arg = a.get("args", {})
                        brief = arg.get("command") or arg.get("path") or arg.get("summary") or ""
                        lines.append(f"- {name}: {str(brief)[:160]}")
                elif m.get("role") in ("tool", "user"):
                    first = (m.get("content") or "").strip().splitlines()
                    if first:
                        lines.append(f"  → {first[0][:160]}")
        self.summary = "\n".join(lines[-80:])   # 摘要本身也要有界
        self.n_compressions += 1
        self.n_dropped_steps += len(dropped)
        self.dropped_tokens_estimate += sum(
            len(str(m.get("content") or "")) // 3 for step in dropped for m in step
        )

        summary_msg = {
            "role": "user",
            "content": self.summary,
            "extra": {"interrupt_type": "history_summary"},
        }
        return head + [summary_msg] + [m for step in kept for m in step]
