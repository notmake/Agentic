"""主循环：query → execute → observe，直到出现 role=='exit'。

升级自 mini-agent-v0.1（保留其异常家族 + 每步落盘 + 格式错误回灌）：
  - 多工具观测（tool 角色 + tool_call_id 配对）
  - TokenBudget 真实 usage 记账 + 整步压缩（history 全量保留供复盘）
  - submit 前 git apply --check 预校验：补丁不可用 → 回灌继续修，不直接退出
  - 卡死检测：连续格式错误上限；步数 / 墙钟上限

输出：
  self.history   完整轨迹（含 extra 元数据），供失败分类与复盘
  run() 返回 {"exit_status","submission","patch","patch_check",...}
"""

from __future__ import annotations

import json
import time
import traceback
from dataclasses import asdict, dataclass, field
from pathlib import Path

from sweagent.exceptions import (
    FormatError,
    InterruptAgentFlow,
    LimitsExceeded,
    SandboxError,
    Submitted,
    TimeExceeded,
    exit_message,
)
from sweagent.token_budget import TokenBudget


@dataclass
class AgentConfig:
    step_limit: int = 40
    wall_time_limit: int = 2400
    max_consecutive_format_errors: int = 3
    max_patch_check_failures: int = 2
    context_window: int = 32_768
    trigger_ratio: float = 0.80
    keep_recent_steps: int = 6
    instance_id: str = ""
    backend: str = ""
    output_dir: str = ""          # 轨迹落到 <output_dir>/trajectory.json


class Agent:
    def __init__(self, llm, env, config: AgentConfig | None = None):
        self.llm = llm
        self.env = env
        self.config = config or AgentConfig()
        self.history: list[dict] = []      # 全量轨迹（不压缩）
        self.context: list[dict] = []      # 发给模型（可压缩）
        self.budget = TokenBudget(
            context_window=self.config.context_window,
            trigger_ratio=self.config.trigger_ratio,
            keep_recent_steps=self.config.keep_recent_steps,
        )
        self.n_calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.n_consecutive_format_errors = 0
        self.n_patch_check_failures = 0
        self._start_time = time.time()

    # ═════════════════════════════════════════════════════════════════
    # 入口
    # ═════════════════════════════════════════════════════════════════
    def run(self, system_prompt: str, task_prompt: str) -> dict:
        self._reset(system_prompt, task_prompt)
        exit_info: dict = {"exit_status": "Unknown", "submission": "", "patch": ""}

        while True:
            try:
                self._step()
                self.n_consecutive_format_errors = 0
            except FormatError as e:
                self._add(*e.messages)
                self.n_consecutive_format_errors += 1
                if 0 < self.config.max_consecutive_format_errors <= self.n_consecutive_format_errors:
                    exit_info = self._exit("RepeatedFormatError")
                    break
            except Submitted as e:
                submission = e.messages[0].get("extra", {}).get("submission", "") if e.messages else ""
                patch = self._safe_patch()
                # 空补丁：模型选择不改代码直接提交，允许结束（评测会判未解决），不算补丁错误
                ok, err = (True, "") if not patch.strip() else self._safe_apply_check(patch)
                if ok or self.n_patch_check_failures >= self.config.max_patch_check_failures:
                    exit_info = self._exit(
                        "Submitted" if ok else "SubmittedPatchCheckFailed",
                        submission=submission, patch=patch, patch_check_ok=ok,
                    )
                    break
                # 补丁不可用 → 回灌，让模型继续修
                self.n_patch_check_failures += 1
                self._add({
                    "role": "user",
                    "content": f"Your submitted patch does not apply cleanly:\n{err}\n"
                               f"Fix the repository state and submit again.",
                    "extra": {"interrupt_type": "PatchCheckFailed"},
                })
            except (LimitsExceeded, TimeExceeded) as e:
                exit_info = self._exit(type(e).__name__, patch=self._safe_patch())
                break
            except SandboxError as e:
                self._add(*e.messages)
                exit_info = self._exit("SandboxError", patch=self._safe_patch())
                break
            except Exception:  # noqa: BLE001
                tb = traceback.format_exc()
                self._add(exit_message("Exception", tb))
                exit_info = self._exit("Exception", error=tb)
                break
            finally:
                self._save()

            if self.history and self.history[-1].get("role") == "exit":
                last = self.history[-1].get("extra", {})
                exit_info = {
                    "exit_status": last.get("exit_status", "Unknown"),
                    "submission": last.get("submission", ""),
                    "patch": last.get("patch", ""),
                }
                break

        self._save()
        return {
            **exit_info,
            "instance_id": self.config.instance_id,
            "backend": self.config.backend,
            "n_calls": self.n_calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "elapsed_seconds": int(time.time() - self._start_time),
            "n_compressions": self.budget.n_compressions,
            "n_dropped_steps": self.budget.n_dropped_steps,
            "history_len": len(self.history),
        }

    # ═════════════════════════════════════════════════════════════════
    # 单步
    # ═════════════════════════════════════════════════════════════════
    def _step(self) -> None:
        message = self._query()
        actions = message.get("extra", {}).get("actions", [])
        outputs = []
        for action in actions:
            outputs.append(self.env.execute(action))
        observations = [self._format_observation(a, o) for a, o in zip(actions, outputs)]
        self._add(*observations)
        self._maybe_compress()

    def _query(self) -> dict:
        if 0 < self.config.step_limit <= self.n_calls:
            raise LimitsExceeded(exit_message("LimitsExceeded"))
        if 0 < self.config.wall_time_limit <= int(time.time() - self._start_time):
            raise TimeExceeded(exit_message("TimeExceeded"))
        self.n_calls += 1
        message = self.llm.query(self.context)
        usage = message.get("extra", {})
        self.prompt_tokens += usage.get("prompt_tokens", 0)
        self.completion_tokens += usage.get("completion_tokens", 0)
        self.budget.update_from_usage(usage.get("prompt_tokens", 0))
        self._add(message)
        return message

    def _format_observation(self, action: dict, output: dict) -> dict:
        payload = {
            "returncode": output.get("returncode"),
            "output": output.get("output", ""),
        }
        if output.get("exception_info"):
            payload["exception_info"] = output["exception_info"]
        content = json.dumps(payload, ensure_ascii=False)

        msg = {
            "role": "tool" if "tool_call_id" in action else "user",
            "content": content,
            "extra": {
                "raw_output": output.get("output", ""),
                "returncode": output.get("returncode"),
                "exception_info": output.get("exception_info", ""),
                "tool": action.get("tool", ""),
            },
        }
        if "tool_call_id" in action:
            msg["tool_call_id"] = action["tool_call_id"]
        return msg

    # ═════════════════════════════════════════════════════════════════
    # 内部
    # ═════════════════════════════════════════════════════════════════
    def _reset(self, system_prompt: str, task_prompt: str) -> None:
        self.history = []
        self.context = []
        self._start_time = time.time()
        self._add(
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": task_prompt},
        )

    def _add(self, *messages: dict) -> None:
        self.history.extend(messages)
        self.context.extend(messages)

    def _maybe_compress(self) -> None:
        if self.budget.should_compress():
            self.context = self.budget.compress(self.context)

    def _exit(self, status: str, **extra) -> dict:
        msg = exit_message(status, **extra)
        self._add(msg)
        return {"exit_status": status, "submission": extra.get("submission", ""),
                "patch": extra.get("patch", "")}

    def _safe_patch(self) -> str:
        try:
            return self.env.get_patch()
        except Exception:  # noqa: BLE001
            return ""

    def _safe_apply_check(self, patch: str) -> tuple[bool, str]:
        try:
            return self.env.apply_check(patch)
        except Exception as e:  # noqa: BLE001
            return False, str(e)

    def serialize(self) -> dict:
        return {
            "info": {
                "instance_id": self.config.instance_id,
                "backend": self.config.backend,
                "exit_status": self.history[-1].get("extra", {}).get("exit_status", "")
                if self.history else "",
                "n_calls": self.n_calls,
                "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
                "elapsed_seconds": int(time.time() - self._start_time),
                "config": asdict(self.config),
                "budget": {
                    "n_compressions": self.budget.n_compressions,
                    "n_dropped_steps": self.budget.n_dropped_steps,
                },
            },
            "messages": self.history,
        }

    def _save(self) -> None:
        if not self.config.output_dir:
            return
        out = Path(self.config.output_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "trajectory.json").write_text(
            json.dumps(self.serialize(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
