"""Check every integration with a real call: `python dev.py doctor`."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import sys

import httpx

from .adapters.explainer import ExplainerError, complete
from .adapters.jev_client import JevClient, JevUnavailable
from .config import Settings
from .models import EvaluateRequest

OK, MISSING, FAIL = "\033[32m✓\033[0m", "\033[33m–\033[0m", "\033[31m✗\033[0m"


def version(cmd: str) -> str | None:
    path = shutil.which(cmd)
    if not path:
        return None
    try:
        out = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return (out.stdout or out.stderr).strip().splitlines()[0] if out.returncode == 0 else None


async def check_jev(s: Settings) -> tuple[str, str]:
    if not s.jev_api_key:
        return FAIL, "JEV_API_KEY is not set (required): an OpenCode key from opencode.ai/console → Keys"
    jev = JevClient(s)
    try:
        result = await jev.evaluate(EvaluateRequest(agent_name="doctor", tool="read_file", args={"path": "README.md"}))
    except JevUnavailable as exc:
        return FAIL, f"call failed: {exc}"
    finally:
        await jev.aclose()
    sig = result.signals
    via = s.jev_base_url or "api.typesafe.ai"
    return OK, (f"{result.model} via {via} answered in {result.latency_ms:.0f} ms "
                f"(read_file README.md: P(safe) {sig.p_safe:.2f})")


async def check_llm(s: Settings) -> tuple[str, str]:
    if not (s.llm_base_url and s.llm_api_key):
        return MISSING, ("LLM_BASE_URL and MODAL_PROXY_TOKEN_ID/SECRET (or LLM_API_KEY) not set: "
                         "blocked/escalated actions won't get explanations")
    async with httpx.AsyncClient(timeout=120.0) as http:
        try:
            text, model = await complete(http, s, "Reply with the single word OK.", "Are you there?", max_tokens=256)
        except ExplainerError as exc:
            return FAIL, str(exc)
    return OK, f"{model} replied: {text[:40]!r}"


async def main() -> int:
    s = Settings.from_env()
    jev, llm = await asyncio.gather(check_jev(s), check_llm(s))
    entire = version(s.entire_bin)
    agy = version("agy")
    rows = [
        ("Jev", *jev),
        ("NeatLogs", OK if s.neatlogs_api_key else MISSING,
         f"key set, project '{s.neatlogs_project}' (verified on the first trace)" if s.neatlogs_api_key
         else "NEATLOGS_API_KEY not set: decisions won't be traced"),
        ("Entire CLI", OK if entire else MISSING,
         entire or "not on PATH: install with  irm https://entire.io/install.ps1 | iex  (see docs.entire.io)"),
        ("LLM explainer", *llm),
        ("Antigravity CLI", OK if agy else MISSING,
         agy or "agy not on PATH: install from https://antigravity.google/docs/cli/install/"),
    ]
    width = max(len(r[0]) for r in rows)
    print()
    for name, mark, detail in rows:
        print(f"  {mark} {name:<{width}}  {detail}")
    print()
    return 0 if jev[0] == OK else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(asyncio.run(main()))
