# -*- coding: utf-8 -*-
"""主循环离线测试：MockTransport + LocalEnvironment。

覆盖四条路径（计划 W2 验收）：
  成功提交 / FormatError 回灌 / step_limit 触顶 / 哨兵提交
"""

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from llm import LLM, MockTransport
from sweagent.agent import Agent, AgentConfig
from sweagent.environment import LocalEnvironment


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("x = 1\n", encoding="utf-8")
    for cmd in (["git", "init", "-q"], ["git", "add", "-A"],
                ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"]):
        subprocess.run(cmd, cwd=repo, check=True)
    return repo


def _run(repo: Path, plan, protocol="toolcall", **cfg):
    llm = LLM(MockTransport(plan, protocol=protocol), protocol=protocol)
    config = AgentConfig(instance_id="test-instance", **cfg)
    return Agent(llm, LocalEnvironment(str(repo)), config).run("sys", "task")


def test_successful_submit_produces_patch(tmp_path):
    repo = _init_repo(tmp_path)
    result = _run(repo, ["echo 'fixed' > app.py"], )
    assert result["exit_status"] == "Submitted"
    assert "app.py" in result["patch"]
    assert "fixed" in result["patch"]


def test_step_limit_exceeded(tmp_path):
    repo = _init_repo(tmp_path)
    result = _run(repo, ["true"] * 5, step_limit=2)
    assert result["exit_status"] == "LimitsExceeded"
    assert result["n_calls"] == 2


def test_text_protocol_sentinel_submit(tmp_path):
    repo = _init_repo(tmp_path)
    result = _run(repo, ["echo 'text-fix' > app.py", "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"],
                  protocol="text")
    assert result["exit_status"] == "Submitted"


def test_repeated_format_errors(tmp_path):
    """模型输出无法解析 → 连续格式错误达到上限后退出。"""
    repo = _init_repo(tmp_path)

    class BrokenTransport:
        def query(self, messages, tools=None):
            from llm import RawResponse
            return RawResponse(content="我不知道该怎么调用工具", tool_calls=[])

    agent = Agent(LLM(BrokenTransport(), protocol="toolcall"),
                  LocalEnvironment(str(repo)),
                  AgentConfig(instance_id="bad", max_consecutive_format_errors=2))
    result = agent.run("sys", "task")
    assert result["exit_status"] == "RepeatedFormatError"


def test_trajectory_written(tmp_path):
    repo = _init_repo(tmp_path)
    out = tmp_path / "run"
    result = _run(repo, ["true"], output_dir=str(out))
    assert (out / "trajectory.json").exists()
    import json
    data = json.loads((out / "trajectory.json").read_text(encoding="utf-8"))
    assert data["messages"][0]["role"] == "system"
    assert result["exit_status"] == "Submitted"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
