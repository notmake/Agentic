"""LLM 容错代理：OpenHands ↔ llama-server 之间的一层 JSON 修复。

问题：27B 偶尔生成不合法的 tool_call arguments（引号未闭合），llama-server 直接返回
500 "Failed to parse tool call arguments as JSON"，OpenHands 原样重试仍会失败 → 空补丁。

做法：
  1. 正常请求透传；
  2. 命中该错误时，重试上游请求，并做两件事：
     - temperature=0（降低随机性）
     - 在末尾追加一条系统提示，强调工具参数必须是合法 JSON、转义引号和换行
  3. 最多重试 N 次；仍失败则原样返回错误。
  4. 所有重试写日志，便于统计修复率。

用法：
    python3 openhands/llm_proxy.py --upstream http://127.0.0.1:6790 --port 6791
    export LLM_BASE_URL=http://127.0.0.1:6791/v1
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PARSE_ERROR = "Failed to parse tool call arguments"
JSON_NUDGE = (
    "IMPORTANT: When you call a tool, the arguments value must be a single valid JSON object. "
    "Every string must use escaped double quotes (\\\") and escaped newlines (\\n); "
    "never emit raw newlines or unescaped quotes inside JSON strings."
)

UPSTREAM = "http://127.0.0.1:6790"
MAX_RETRIES = 3
LOG_PATH = "/tmp/llm_proxy.log"


def log(msg: str) -> None:
    line = f"[llm_proxy] {msg}\n"
    sys.stderr.write(line)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass


def post_json(url: str, payload: dict, timeout: int = 600) -> tuple[int, bytes]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:  # noqa: BLE001
        return 599, str(e).encode()


def repair_request(payload: dict) -> dict:
    fixed = json.loads(json.dumps(payload))  # deep copy
    fixed["temperature"] = 0.0
    messages = fixed.get("messages") or []
    # 追加到最前面的 system，避免破坏 user/assistant 配对。
    # 注意：content 可能是字符串，也可能是 OpenAI 的多段内容列表。
    if messages and messages[0].get("role") == "system":
        content = messages[0].get("content")
        if isinstance(content, list):
            messages[0]["content"] = list(content) + [{"type": "text", "text": JSON_NUDGE}]
        elif content:
            messages[0]["content"] = str(content) + "\n\n" + JSON_NUDGE
        else:
            messages[0]["content"] = JSON_NUDGE
    else:
        messages.insert(0, {"role": "system", "content": JSON_NUDGE})
    fixed["messages"] = messages
    return fixed


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # noqa: A003
        return

    def _send(self, status: int, body: bytes, content_type="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        status, body = 200, b'{"status":"ok"}'
        if self.path.rstrip("/").endswith("/models"):
            status, body = post_json_get(f"{UPSTREAM}{self.path}")
        self._send(status, body)

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw)
        except Exception:  # noqa: BLE001
            self._send(400, b'{"error":"invalid json"}')
            return

        if not self.path.rstrip("/").endswith("/chat/completions"):
            status, body = post_json(f"{UPSTREAM}{self.path}", payload)
            self._send(status, body)
            return

        status, body = post_json(f"{UPSTREAM}/v1/chat/completions", payload)
        text = body.decode("utf-8", "replace")
        if status < 400 or PARSE_ERROR not in text:
            self._send(status, body)
            return

        log(f"upstream {status}: tool-call JSON parse error; retrying")
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                fixed = repair_request(payload)
                status, body = post_json(f"{UPSTREAM}/v1/chat/completions", fixed)
                text = body.decode("utf-8", "replace")
            except Exception as e:  # noqa: BLE001
                log(f"retry {attempt} exception: {e!r}")
                continue
            if status < 400 and PARSE_ERROR not in text:
                log(f"retry {attempt} OK")
                self._send(status, body)
                return
            log(f"retry {attempt} still failing")
        self._send(status, body)


def post_json_get(url: str) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return r.status, r.read()
    except Exception as e:  # noqa: BLE001
        return 599, str(e).encode()


def main() -> None:
    global UPSTREAM
    ap = argparse.ArgumentParser(description="LLM 容错代理")
    ap.add_argument("--upstream", default=UPSTREAM)
    ap.add_argument("--port", type=int, default=6791)
    args = ap.parse_args()
    UPSTREAM = args.upstream.rstrip("/")
    log(f"listening :{args.port} -> {UPSTREAM}, retries={MAX_RETRIES}")
    ThreadingHTTPServer(("0.0.0.0", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
