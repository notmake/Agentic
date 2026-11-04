"""执行环境：一个 action 换一个观测结果。

两种实现：
  LocalEnvironment   开发机本地目录（W2 离线测试、mock 演示）
  DockerEnvironment  官方 SWE-bench 评测镜像里的 /testbed（W3 真评测）

共同契约：
  execute(action) -> {"tool", "output", "returncode", "exception_info"}
  submit 工具 / 文本哨兵 → 抛 Submitted(exit_message(...)) 打断主循环
  工具输出统一截断（bash 20k / view 10k 字符，预算见 config.AgentLimits）
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from sweagent.actions import SUBMIT_SENTINEL
from sweagent.exceptions import SandboxError, Submitted, exit_message


class BaseEnvironment:
    """环境基类：dispatch + 截断 + 行号格式化 + 哨兵。"""

    def __init__(
        self,
        workdir: str = ".",
        bash_output_limit: int = 20_000,
        view_output_limit: int = 10_000,
        command_timeout: int = 120,
    ):
        self.workdir = workdir
        self.bash_output_limit = bash_output_limit
        self.view_output_limit = view_output_limit
        self.command_timeout = command_timeout

    # ── 统一入口 ──
    def execute(self, action: dict) -> dict:
        tool = action.get("tool", "")
        args = action.get("args", {})
        if tool == "bash":
            return self._bash(args.get("command", ""))
        if tool == "view":
            return self._view(args["path"], args.get("start_line"), args.get("end_line"))
        if tool == "write":
            return self._write(args["path"], args["content"])
        if tool == "submit":
            raise Submitted(exit_message("Submitted", args.get("summary", "")))
        raise SandboxError.for_text(f"Unknown tool {tool!r} reached the environment.")

    # ── 补丁 ──
    def get_patch(self) -> str:
        """产出可被 git apply 的补丁（含新文件）。子类实现。"""
        raise NotImplementedError

    def apply_check(self, patch: str) -> tuple[bool, str]:
        """在干净 base_commit 上试应用补丁。返回 (ok, 错误信息)。子类实现。"""
        raise NotImplementedError

    # ── 子类实现 ──
    def _bash(self, command: str) -> dict:
        raise NotImplementedError

    def _view(self, path: str, start: int | None, end: int | None) -> dict:
        raise NotImplementedError

    def _write(self, path: str, content: str) -> dict:
        raise NotImplementedError

    # ── 公共工具方法 ──
    @staticmethod
    def _truncate(text: str, limit: int, what: str) -> str:
        if len(text) <= limit:
            return text
        head = text[: limit * 2 // 3]
        tail = text[-limit // 3 :]
        return f"{head}\n... [{what} 输出过长，已截断 {len(text) - limit} 字符] ...\n{tail}"

    @staticmethod
    def _format_lines(content: str, start: int | None, end: int | None) -> str:
        lines = content.splitlines()
        lo = max(start or 1, 1)
        hi = min(end or len(lines), len(lines))
        width = len(str(hi))
        return "\n".join(f"{i:>{width}}\t{lines[i - 1]}" for i in range(lo, hi + 1))

    @staticmethod
    def _check_submit(command: str) -> None:
        """命令本身就是哨兵时直接结束（等价于模型直接 submit）。"""
        if command.strip() == SUBMIT_SENTINEL:
            raise Submitted(exit_message("Submitted", ""))

    @staticmethod
    def _check_submitted_output(output: str, returncode: int) -> None:
        """哨兵语义（对齐 mini-agent）：输出首行是 SENTINEL 且命令成功 → 任务结束，
        其余行作为 submission。文本协议 `echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT` 走这里。"""
        lines = (output or "").lstrip().splitlines(keepends=True)
        if lines and lines[0].strip() == SUBMIT_SENTINEL and returncode == 0:
            raise Submitted(exit_message("Submitted", "".join(lines[1:]).strip()))


class LocalEnvironment(BaseEnvironment):
    """本机目录执行（仅开发/测试用，不是评测沙箱）。"""

    def __init__(self, workdir: str = ".", **kwargs):
        self.root = Path(workdir).resolve()
        super().__init__(workdir=str(self.root), **kwargs)

    def _safe_path(self, path: str) -> Path:
        p = (self.root / path).resolve()
        if not str(p).startswith(str(self.root)):
            raise SandboxError.for_text(f"Path escapes the workspace: {path}")
        return p

    def _bash(self, command: str) -> dict:
        self._check_submit(command)
        try:
            result = subprocess.run(
                command, shell=True, text=True, cwd=self.workdir,
                encoding="utf-8", errors="replace",
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                timeout=self.command_timeout,
            )
            self._check_submitted_output(result.stdout or "", result.returncode)
            return {
                "tool": "bash",
                "output": self._truncate(result.stdout or "", self.bash_output_limit, "bash"),
                "returncode": result.returncode,
                "exception_info": "",
            }
        except subprocess.TimeoutExpired:
            return {"tool": "bash", "output": "", "returncode": -1,
                    "exception_info": f"Command timed out after {self.command_timeout}s"}

    def _view(self, path: str, start: int | None, end: int | None) -> dict:
        p = self._safe_path(path)
        if not p.is_file():
            return {"tool": "view", "output": "", "returncode": 1,
                    "exception_info": f"File not found: {path}"}
        content = p.read_text(encoding="utf-8", errors="replace")
        out = self._format_lines(content, start, end)
        return {"tool": "view", "output": self._truncate(out, self.view_output_limit, "view"),
                "returncode": 0, "exception_info": ""}

    def _write(self, path: str, content: str) -> dict:
        p = self._safe_path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return {"tool": "write", "output": f"Wrote {len(content)} bytes to {path}",
                "returncode": 0, "exception_info": ""}

    def get_patch(self) -> str:
        r = subprocess.run(
            "git add -A && git diff --cached --no-color -- . "
            "':(exclude,glob)**/__pycache__/**' ':(exclude,glob)**/*.pyc'",
            shell=True, cwd=self.workdir, text=True,
            encoding="utf-8", errors="replace", capture_output=True,
        )
        return r.stdout if r.returncode == 0 else ""

    def apply_check(self, patch: str) -> tuple[bool, str]:
        """本地模式：直接在逆应用自检（真评测由 DockerEnvironment 在纯净 worktree 校验）。"""
        if not patch.strip():
            return False, "empty patch"
        r = subprocess.run(
            "git apply --check --reverse -", shell=True, cwd=self.workdir,
            input=patch, text=True, capture_output=True, encoding="utf-8",
        )
        return r.returncode == 0, (r.stderr or "").strip()


# ═════════════════════════════════════════════════════════════════════════
# Docker 沙箱（W3）
# ═════════════════════════════════════════════════════════════════════════

CONDA_SETUP = "source /opt/miniconda3/bin/activate && conda activate testbed"


class DockerEnvironment(BaseEnvironment):
    """官方 sweb.eval 镜像里的 /testbed。容器内 exec，conda testbed 环境跑测试。"""

    def __init__(
        self,
        image: str,
        container_name: str,
        base_commit: str,
        workdir: str = "/testbed",
        conda_setup: str = CONDA_SETUP,
        **kwargs,
    ):
        self.image = image
        self.container_name = container_name
        self.base_commit = base_commit
        self.conda_setup = conda_setup
        self._started = False
        super().__init__(workdir=workdir, **kwargs)

    # ── 生命周期 ──
    def start(self) -> None:
        self._run(["docker", "rm", "-f", self.container_name], check=False)
        self._run([
            "docker", "run", "-d", "--name", self.container_name,
            "--network", "host",
            "-v", f"{_host_project()}:/opt/sweagent:ro",
            self.image, "sleep", "infinity",
        ])
        self._started = True
        # 入口对齐：硬的 base_commit + 清掉 test_patch 等污染
        self._exec_raw(f"cd {self.workdir} && git reset --hard {self.base_commit} && git clean -fdq")

    def stop(self) -> None:
        if self._started:
            self._run(["docker", "rm", "-f", self.container_name], check=False)
            self._started = False

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()

    # ── 子类实现 ──
    def _bash(self, command: str) -> dict:
        self._check_submit(command)
        wrapped = f"{self.conda_setup} && cd {self.workdir} && {command}"
        try:
            r = self._exec_raw(wrapped, timeout=self.command_timeout)
            self._check_submitted_output(r.stdout or "", r.returncode)
            return {"tool": "bash",
                    "output": self._truncate(r.stdout or "", self.bash_output_limit, "bash"),
                    "returncode": r.returncode, "exception_info": ""}
        except subprocess.TimeoutExpired:
            return {"tool": "bash", "output": "", "returncode": -1,
                    "exception_info": f"Command timed out after {self.command_timeout}s"}

    def _view(self, path: str, start: int | None, end: int | None) -> dict:
        r = self._exec_raw(f"cat {self.workdir}/{path}")
        if r.returncode != 0:
            return {"tool": "view", "output": "", "returncode": r.returncode,
                    "exception_info": f"File not found: {path}"}
        out = self._format_lines(r.stdout or "", start, end)
        return {"tool": "view", "output": self._truncate(out, self.view_output_limit, "view"),
                "returncode": 0, "exception_info": ""}

    def _write(self, path: str, content: str) -> dict:
        target = f"{self.workdir}/{path}"
        self._exec_raw(f"mkdir -p $(dirname {target})")
        r = subprocess.run(
            ["docker", "exec", "-i", self.container_name, "bash", "-c", f"cat > {target}"],
            input=content, text=True, capture_output=True, encoding="utf-8",
        )
        return {"tool": "write", "output": f"Wrote {len(content)} bytes to {path}",
                "returncode": r.returncode, "exception_info": (r.stderr or "").strip()}

    def get_patch(self) -> str:
        r = self._exec_raw(
            f"cd {self.workdir} && git add -A && git diff --cached --no-color -- . "
            f"':(exclude,glob)**/__pycache__/**' ':(exclude,glob)**/*.pyc'",
            timeout=self.command_timeout,
        )
        return r.stdout if r.returncode == 0 else ""

    def apply_check(self, patch: str) -> tuple[bool, str]:
        """在干净 base_commit 的临时 worktree 上 `git apply --check`。"""
        if not patch.strip():
            return False, "empty patch"
        # 补丁写进容器
        subprocess.run(
            ["docker", "exec", "-i", self.container_name, "bash", "-c", "cat > /tmp/_candidate.patch"],
            input=patch, text=True, capture_output=True, encoding="utf-8",
        )
        cmd = (
            f"cd {self.workdir} && rm -rf /tmp/_patch_check && "
            f"git worktree add --detach /tmp/_patch_check {self.base_commit} >/dev/null 2>&1 && "
            f"git -C /tmp/_patch_check apply --check /tmp/_candidate.patch; "
            f"rc=$?; git worktree remove --force /tmp/_patch_check >/dev/null 2>&1; exit $rc"
        )
        r = self._exec_raw(cmd, timeout=self.command_timeout)
        return r.returncode == 0, "" if r.returncode == 0 else (r.stdout or "").strip()

    # ── 底层 ──
    def _exec_raw(self, command: str, timeout: int = 120):
        return subprocess.run(
            ["docker", "exec", self.container_name, "bash", "-lc", command],
            text=True, encoding="utf-8", errors="replace",
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout,
        )

    @staticmethod
    def _run(cmd: list[str], check: bool = True):
        r = subprocess.run(cmd, text=True, capture_output=True, encoding="utf-8")
        if check and r.returncode != 0:
            raise SandboxError.for_text(f"Command failed: {' '.join(cmd)}\n{r.stderr}")
        return r


def _host_project() -> str:
    return str(Path(__file__).resolve().parents[1])
