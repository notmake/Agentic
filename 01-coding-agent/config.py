"""统一配置：后端注册表 + .env 加载 + fail-fast。

风格沿用 01_deep_research/config.py：所有地址/密钥集中在此，缺失立即报错，
不允许散落在业务代码里。纯本地约束：BACKENDS 只允许指向本地推理服务。

五个后端（与计划一致）：
    a800_27b  A800 上的 vLLM（经 SSH 隧道到 127.0.0.1:8001）—— 主后端
    a800_30b  A800 升级档（Qwen3-Coder-30B-A3B，决策门通过后启用）
    dev_4b    开发机 vLLM Qwen3.5-4B :6789（text 协议 + strip_think 兜底）
    dev_27b   开发机 llama.cpp Qwen3.8-27B :6790（与 4B 互斥）
    mock      离线假模型，零依赖跑通主循环
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class ConfigError(RuntimeError):
    """配置缺失或非法：fail-fast，中文报错说明怎么修。"""


def load_env(path: Path | None = None) -> None:
    """极简 .env 加载（不引入 python-dotenv）：KEY=VALUE，忽略注释与空行。

    已存在的环境变量优先（方便临时覆盖调试）。
    """
    env_path = path or ROOT / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.split(" #", 1)[0].strip()
        if key and key not in os.environ:
            os.environ[key] = value


def env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None or value == "":
        raise ConfigError(
            f"缺少环境变量 {name}。请复制 .env.example 为 .env 并填写（或 export {name}=...）。"
        )
    return value


def env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError as e:
        raise ConfigError(f"环境变量 {name} 必须是整数，当前值：{os.environ.get(name)!r}") from e


@dataclass(frozen=True)
class BackendConfig:
    """一个推理后端的全部连接参数。"""

    name: str
    base_url: str
    model: str
    protocol: str = "toolcall"       # toolcall | text
    response_policy: str = "plain"   # plain | strip_think（思考模型污染剥离）
    api_key: str = "EMPTY"           # vLLM 接受任意值
    temperature: float = 0.0         # 评测统一 temperature=0（可复现性）
    max_tokens: int = 4096


def _backend(
    name: str,
    url_env: str,
    default_url: str,
    model_env: str,
    default_model: str,
    *,
    protocol: str = "toolcall",
    response_policy: str = "plain",
) -> BackendConfig:
    return BackendConfig(
        name=name,
        base_url=os.environ.get(url_env, default_url),
        model=os.environ.get(model_env, default_model),
        protocol=protocol,
        response_policy=response_policy,
        api_key=os.environ.get("LOCAL_API_KEY", "EMPTY"),
        temperature=0.0,
        max_tokens=4096,
    )


BACKENDS_NAMES = ("a800_27b", "a800_30b", "dev_4b", "dev_27b", "mock")


def build_backends() -> dict[str, BackendConfig]:
    """读取环境变量构造五后端注册表。mock 不需要任何地址。"""
    return {
        "a800_27b": _backend(
            "a800_27b", "A800_BASE_URL", "http://127.0.0.1:8001/v1",
            "A800_MODEL", "Qwen3.8-27B-Q4_K_M",
        ),
        "a800_30b": _backend(
            "a800_30b", "A800_30B_BASE_URL", "http://127.0.0.1:8001/v1",
            "A800_30B_MODEL", "Qwen3-Coder-30B-A3B-Instruct",
        ),
        "dev_4b": _backend(
            "dev_4b", "DEV_4B_BASE_URL", "http://127.0.0.1:6789/v1",
            "DEV_4B_MODEL", "Qwen3.5-4B",
            protocol="text", response_policy="strip_think",   # 4B 思考模型实测坑
        ),
        "dev_27b": _backend(
            "dev_27b", "DEV_27B_BASE_URL", "http://127.0.0.1:6790/v1",
            "DEV_27B_MODEL", "Qwen3.8-27B-Q4_K_M",
            protocol="text", response_policy="strip_think",
        ),
        "mock": BackendConfig(name="mock", base_url="", model="mock"),
    }


def get_backend(name: str | None = None) -> BackendConfig:
    name = name or os.environ.get("DEFAULT_BACKEND", "a800_27b")
    backends = build_backends()
    if name not in backends:
        raise ConfigError(
            f"未知后端 {name!r}，可选：{', '.join(backends)}（改 .env 的 DEFAULT_BACKEND）"
        )
    return backends[name]


@dataclass(frozen=True)
class AgentLimits:
    """单实例额度（全部来自环境变量，配置卡可覆盖）。"""

    step_limit: int = 40
    wall_time_limit: int = 2400        # 秒
    max_consecutive_format_errors: int = 3
    bash_output_limit: int = 20_000    # 字符
    view_output_limit: int = 10_000
    token_budget_ratio: float = 0.8    # 超过上下文窗口 80% 触发整步压缩


def load_limits() -> AgentLimits:
    return AgentLimits(
        step_limit=env_int("SWEAGENT_STEP_LIMIT", 40),
        wall_time_limit=env_int("SWEAGENT_WALL_TIME_LIMIT", 2400),
    )
