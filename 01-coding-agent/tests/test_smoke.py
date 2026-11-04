# -*- coding: utf-8 -*-
"""冒烟测试：配置层可用、后端注册表合法。

W0 验收：pytest 绿。
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import BACKENDS_NAMES, ConfigError, build_backends, get_backend, load_limits


def test_backends_registry_complete():
    backends = build_backends()
    assert set(backends) == {"a800_27b", "a800_30b", "dev_4b", "dev_27b", "mock"}
    assert BACKENDS_NAMES == tuple(backends)


def test_backend_defaults_are_local():
    """硬约束回归：所有后端地址必须是本地/隧道地址，不允许外部 LLM API。"""
    for b in build_backends().values():
        if b.name == "mock":
            continue
        assert b.base_url.startswith("http://127.0.0.1") or b.base_url.startswith(
            "http://localhost"
        ), f"{b.name} 指向了非本地地址：{b.base_url}"


def test_unknown_backend_fails_fast():
    try:
        get_backend("not-exist")
    except ConfigError as e:
        assert "未知后端" in str(e)
    else:
        raise AssertionError("未知后端应当 fail-fast")


def test_limits_from_env(monkeypatch):
    monkeypatch.setenv("SWEAGENT_STEP_LIMIT", "12")
    monkeypatch.setenv("SWEAGENT_WALL_TIME_LIMIT", "60")
    limits = load_limits()
    assert limits.step_limit == 12
    assert limits.wall_time_limit == 60
