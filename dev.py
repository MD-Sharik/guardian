"""One entry point for the whole monorepo. Works on Windows, macOS and Linux.

    python dev.py setup                       create .venv, install Python + dashboard deps, create .env
    python dev.py doctor                      check each integration (keys, CLIs) with a real call
    python dev.py                             start guardian-service (:8000) and the dashboard (:3000)
    python dev.py install-antigravity <dir>   guard every Antigravity tool call in that project
    python dev.py uninstall-antigravity <dir>
    python dev.py demo danger                 run the LangGraph example agent: happy | danger | uncertain
    python dev.py replay [--session ID]       re-score recorded decisions with the current policy (no Jev calls)
    python dev.py test                        run the test suite
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
VENV_PY = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
HOOK_EXE = VENV / ("Scripts/guardian-antigravity-hook.exe" if os.name == "nt" else "bin/guardian-antigravity-hook")
HOOK_HEADROOM_S = 60  # Antigravity's hook timeout = how long the hook waits for the dashboard + this
DASHBOARD = ROOT / "dashboard"
COLORS = {"service": "\033[36m", "dashboard": "\033[35m"}
RESET = "\033[0m"

if os.name == "nt":
    os.system("")  # enable ANSI colours in the Windows console
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # cp1252 consoles can't print the log prefix


def read_env() -> dict[str, str]:
    env = {}
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                env[key.strip()] = value.strip()
    return env


def python() -> str:
    if not VENV_PY.exists():
        sys.exit("No .venv yet. Run:  python dev.py setup")
    return str(VENV_PY)


def npm() -> str:
    found = shutil.which("npm")
    if not found:
        sys.exit("npm not found. Install Node.js 20+ from https://nodejs.org")
    return found


def run(cmd: list[str], **kwargs) -> None:
    print(f"$ {' '.join(cmd)}", flush=True)
    subprocess.run(cmd, check=True, **kwargs)


def setup() -> None:
    if not VENV_PY.exists():
        print("Creating .venv …")
        venv.create(VENV, with_pip=True)
    run([python(), "-m", "pip", "install", "--upgrade", "pip", "-q"])
    run([python(), "-m", "pip", "install", "-r", "requirements.txt"], cwd=ROOT)
    run([npm(), "install"], cwd=DASHBOARD)
    if not (ROOT / ".env").exists():
        shutil.copy(ROOT / ".env.example", ROOT / ".env")
        print("Created .env from .env.example. Add your keys there, at least JEV_API_KEY.")
    print("\nSetup complete. Next:  python dev.py doctor")


def hooks_file(project: str) -> Path:
    root = Path(project).expanduser().resolve()
    if not root.is_dir():
        sys.exit(f"Not a directory: {root}")
    return root / ".agents" / "hooks.json"


def read_hooks(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def write_hooks(path: Path, hooks: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(hooks, indent=2) + "\n", encoding="utf-8")


def install_antigravity(project: str) -> None:
    if not HOOK_EXE.exists():
        sys.exit("The hook isn't installed yet. Run:  python dev.py setup")
    if os.name == "nt" and " " in str(HOOK_EXE):
        print(f"Warning: {HOOK_EXE} contains a space. Antigravity runs hooks through `cmd /C` on Windows, "
              "and quoted paths there are known to fail. Move the repo to a path without spaces if hooks error.")
    # Antigravity runs hooks with its own environment, so bake Guardian's settings into the command.
    config = read_env()
    host, port = config.get("GUARDIAN_HOST") or "127.0.0.1", config.get("GUARDIAN_PORT") or "8000"
    url = config.get("GUARDIAN_URL") or f"http://{host}:{port}"
    wait = int(float(config.get("GUARDIAN_HOOK_WAIT") or 240))
    on_allow = config.get("GUARDIAN_ON_ALLOW") or "allow"
    path = hooks_file(project)
    hooks = read_hooks(path)  # keep other entries, e.g. the one `entire enable` manages
    hooks["guardian"] = {
        "PreToolUse": [{"matcher": ".*", "hooks": [{
            "type": "command",
            "command": f"{HOOK_EXE} pre --url {url} --wait {wait} --on-allow {on_allow}",
            "timeout": wait + HOOK_HEADROOM_S,
        }]}],
        "PostToolUse": [{"matcher": ".*", "hooks": [
            {"type": "command", "command": f"{HOOK_EXE} post --url {url}", "timeout": 15}]}],
    }
    write_hooks(path, hooks)
    others = [k for k in hooks if k != "guardian"]
    print(f"Guardian hook written to {path}" + (f" (kept: {', '.join(others)})" if others else ""))
    print(f"  talks to {url}, waits {wait}s for the dashboard on ESCALATE, answers ALLOW with '{on_allow}'")
    print("Next: keep `python dev.py` running, then start `agy` in that folder. Every tool call now goes "
          "through Guardian.\nAntigravity only loads workspace hooks for trusted folders, so trust it when asked.")


def uninstall_antigravity(project: str) -> None:
    path = hooks_file(project)
    hooks = read_hooks(path)
    if hooks.pop("guardian", None) is None:
        print(f"No Guardian hook in {path}")
        return
    write_hooks(path, hooks)
    print(f"Removed the Guardian hook from {path}")


def stream(name: str, proc: subprocess.Popen) -> None:
    prefix = f"{COLORS[name]}{name:>9}{RESET} │ "
    for line in proc.stdout:  # keep draining no matter what, or the child blocks on a full pipe
        try:
            sys.stdout.write(prefix + line)
            sys.stdout.flush()
        except (OSError, ValueError):
            pass


def start(name: str, cmd: list[str], cwd: Path, env: dict[str, str]) -> subprocess.Popen:
    kwargs = (
        {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    )
    proc = subprocess.Popen(
        cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", **kwargs,
    )
    threading.Thread(target=stream, args=(name, proc), daemon=True).start()
    return proc


def stop(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if os.name == "nt":  # npm/uvicorn spawn children; kill the whole tree
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
    else:
        os.killpg(proc.pid, signal.SIGTERM)


def dev() -> None:
    config = read_env()
    if not (config.get("JEV_API_KEY") or os.getenv("JEV_API_KEY")):
        sys.exit("JEV_API_KEY isn't set. Add your OpenCode key to .env (opencode.ai/console, Keys tab), "
                 "then check with:  python dev.py doctor")
    host, port = config.get("GUARDIAN_HOST") or "127.0.0.1", config.get("GUARDIAN_PORT") or "8000"
    env = {**os.environ, **{k: v for k, v in config.items() if v}, "PYTHONUNBUFFERED": "1"}
    env.setdefault("NEXT_PUBLIC_GUARDIAN_URL", f"http://{host}:{port}")

    procs = [
        start("service", [python(), "-m", "uvicorn", "app.main:app", "--app-dir", "guardian-service",
                          "--host", host, "--port", port], ROOT, env),
        start("dashboard", [npm(), "run", "dev"], DASHBOARD, env),
    ]
    print(f"\n  Guardian API   http://{host}:{port}\n  Dashboard      http://localhost:3000\n"
          f"  Run a demo     python dev.py demo happy   (or danger / uncertain)\n  Ctrl+C to stop\n", flush=True)
    try:
        while all(p.poll() is None for p in procs):
            threading.Event().wait(0.5)
        print("A process exited; shutting down.")
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs:
            stop(p)


def main() -> None:
    args = sys.argv[1:]
    command = args[0] if args else "dev"
    if command == "setup":
        setup()
    elif command == "dev":
        dev()
    elif command == "doctor":
        sys.exit(subprocess.run([python(), "-m", "app.doctor"], cwd=ROOT / "guardian-service").returncode)
    elif command in ("install-antigravity", "uninstall-antigravity"):
        if len(args) < 2:
            sys.exit(f"Usage: python dev.py {command} <project folder>")
        (install_antigravity if command.startswith("install") else uninstall_antigravity)(args[1])
    elif command == "demo":
        subprocess.run([python(), str(ROOT / "demo-agent" / "run.py"), *args[1:]])
    elif command == "replay":
        sys.exit(subprocess.run([python(), "-m", "app.replay", *args[1:]], cwd=ROOT / "guardian-service").returncode)
    elif command == "test":
        sys.exit(subprocess.run([python(), "-m", "pytest", *args[1:]], cwd=ROOT).returncode)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
