"""The demo agent's tools. Everything happens inside demo-agent/workspace.

Safety, independent of Guardian (the sandbox must hold even if Guardian
allows something it shouldn't, or a human approves a mistake):
  - file tools resolve paths and refuse anything outside the workspace
  - run_shell executes only `ls`, `cat`, `echo` and screened Python scripts,
    one at a time; it refuses every other command (rm, curl, git, ...), and
    pipes, chaining and redirection, and says so
  - http_request makes real GET requests only; other methods are refused
"""

from __future__ import annotations

import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import httpx
from langchain_core.tools import tool

HERE = Path(__file__).resolve().parent
SEED = HERE / "seed"
WORKSPACE = HERE / "workspace"

UNSAFE_PYTHON = re.compile(
    r"\b(import|from)\s+(os|subprocess|shutil|pathlib|socket|ctypes|importlib|urllib|http|requests)\b|"
    r"__import__|\beval\(|\bexec\(|\.\./|\.\.\\|['\"]/|['\"][A-Za-z]:\\",
)
MAX_OUTPUT = 4000
SHELL_OPERATORS = re.compile(r"[;&|<>`]|\$\(")


def reset_workspace() -> Path:
    if WORKSPACE.exists():
        shutil.rmtree(WORKSPACE)
    shutil.copytree(SEED, WORKSPACE)
    return WORKSPACE


def _resolve(path: str) -> Path:
    root = WORKSPACE.resolve()
    target = (root / path).resolve()
    if not target.is_relative_to(root):
        raise ValueError(f"'{path}' is outside the sandbox workspace")
    return target


def _rel(p: Path) -> str:
    return p.relative_to(WORKSPACE.resolve()).as_posix() or "."


@tool
def read_file(path: str) -> str:
    """Read a text file from the project workspace. `path` is relative to the project root."""
    return _resolve(path).read_text(encoding="utf-8")[:MAX_OUTPUT]


@tool
def write_file(path: str, content: str) -> str:
    """Create or overwrite a text file in the project workspace with `content`."""
    target = _resolve(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"wrote {len(content)} characters to {_rel(target)}"


@tool
def delete_file(path: str) -> str:
    """Delete a file from the project workspace."""
    target = _resolve(path)
    if not target.is_file():
        return f"no such file: {path}"
    target.unlink()
    return f"deleted {_rel(target)}"


@tool
def run_shell(command: str) -> str:
    """Run one shell command (ls, cat, echo, or python path/to/script.py) in the project root and return its output.
    One command per call: pipes, `;`, `&&` and redirection are refused."""
    if SHELL_OPERATORS.search(command):
        return (f"[sandbox] refused to run `{command}`: run one command at a time "
                "(no pipes, chaining or redirection).")
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        return f"could not parse command: {exc}"
    if not argv:
        return ""
    name, rest = argv[0], argv[1:]
    if name == "echo":
        return " ".join(rest)
    if name == "ls":
        return _ls([a for a in rest if not a.startswith("-")] or ["."])
    if name == "cat" and rest:
        return "\n".join(_resolve(p).read_text(encoding="utf-8") for p in rest)[:MAX_OUTPUT]
    if name in ("python", "python3") and rest and rest[0].endswith(".py"):
        return _run_python(rest[0], rest[1:])
    return f"[sandbox] refused to run `{command}`: this sandbox only runs ls, cat, echo and screened Python scripts."


def _ls(paths: list[str]) -> str:
    out = []
    for path in paths:
        target = _resolve(path)
        if target.is_dir():
            entries = "\n".join(sorted(_rel(p) + ("/" if p.is_dir() else "") for p in target.iterdir()))
            out.append(f"{_rel(target)}:\n{entries}" if len(paths) > 1 else entries)
        elif target.exists():
            out.append(_rel(target))
        else:
            out.append(f"ls: cannot access '{path}': No such file or directory")
    return "\n\n".join(out)


def _run_python(script: str, args: list[str]) -> str:
    path = _resolve(script)
    if not path.is_file():
        return f"python: can't open file '{script}'"
    if UNSAFE_PYTHON.search(path.read_text(encoding="utf-8")):
        return f"[sandbox] refused to run {script}: it uses modules or paths that could reach outside the workspace."
    proc = subprocess.run(
        [sys.executable, "-I", str(path), *args],
        cwd=WORKSPACE, capture_output=True, text=True, timeout=20,
    )
    return (proc.stdout + proc.stderr).strip()[:MAX_OUTPUT] or f"(exit code {proc.returncode})"


@tool
def http_request(url: str, method: str = "GET", body: str = "") -> str:
    """Send an HTTP request and return the status and response body."""
    if method.upper() != "GET":
        return f"[sandbox] refused to send {method.upper()} {url}: this sandbox only sends GET requests."
    try:
        resp = httpx.get(url, timeout=10, follow_redirects=True)
    except httpx.HTTPError as exc:
        return f"request failed: {exc}"
    return f"{resp.status_code}\n{resp.text[:MAX_OUTPUT]}"


TOOLS = [read_file, write_file, run_shell, delete_file, http_request]
