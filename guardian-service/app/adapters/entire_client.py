"""Entire adapter: pull the captured agent session behind a decision.

Entire (https://docs.entire.io) records coding-agent sessions (prompts,
transcripts, tool calls, files touched) as checkpoints linked to Git
commits. This adapter reads them through the documented CLI's JSON output,
run inside the agent's repository:

  entire session info <id> --json   (or `entire session current --json`)
  entire session info <id> --transcript         raw JSONL, agent-specific
  entire checkpoint explain HEAD --json --no-pager
  entire checkpoint explain HEAD --short --no-pager

Which repository and session: the action's context names them. Antigravity
sends its workspace path, and its conversation ID is the session ID Entire
records (`entire session resume` prints `agy --conversation SESSION_ID`).
ENTIRE_REPO_PATH is the fallback repository for other agents.

The JSON field names aren't fully specified in the docs, so the documents
pass through mostly untouched and the explainer LLM reads them.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from ..config import Settings
from ..models import Decision

log = logging.getLogger("guardian.entire")

TRANSCRIPT_LINES = 8
LINE_CHARS = 600


def _trim(value: Any, limit: int = 4000) -> Any:
    text = json.dumps(value, default=str)
    return value if len(text) <= limit else text[:limit] + "…[truncated]"


class EntireClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.bin = shutil.which(settings.entire_bin)
        self.mode = "live" if self.bin else "off"

    def repo_for(self, d: Decision) -> Path | None:
        for candidate in (d.context.metadata.get("workspace"), self.settings.entire_repo_path):
            if candidate and Path(candidate).is_dir():
                return Path(candidate)
        return None

    async def _run(self, repo: Path, *args: str, timeout: float = 15.0) -> str | None:
        # subprocess.run in a thread: uvicorn on Windows may use a selector
        # event loop, which can't spawn asyncio subprocesses.
        try:
            proc = await asyncio.to_thread(
                subprocess.run, [self.bin, *args], cwd=repo, capture_output=True, timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            log.warning("entire %s failed: %s", " ".join(args), exc)
            return None
        if proc.returncode != 0:
            log.info("entire %s exited %s: %s", " ".join(args), proc.returncode, proc.stderr.decode()[:300])
            return None
        return proc.stdout.decode("utf-8", errors="replace")

    async def _run_json(self, repo: Path, *args: str) -> Any:
        out = await self._run(repo, *args)
        if not out:
            return None
        try:
            return json.loads(out)
        except json.JSONDecodeError:
            return None

    async def session_context(self, d: Decision) -> dict[str, Any] | None:
        """The Entire session for this decision, an {"error": ...} dict, or None when off."""
        if self.mode == "off":
            return None
        repo = self.repo_for(d)
        if repo is None:
            return {"source": "entire-cli", "error": "No repository to read: the agent sent no workspace "
                    "path and ENTIRE_REPO_PATH is not set."}

        sid = d.context.entire_session_id
        session = await self._run_json(repo, "session", "info", sid, "--json") if sid else None
        if session is None:  # unknown to Entire yet (e.g. first turn) -> most recent session in this repo
            session = await self._run_json(repo, "session", "current", "--json")
            if isinstance(session, dict):
                sid = sid or session.get("session_id") or session.get("id")

        checkpoint, summary, transcript = await asyncio.gather(
            self._run_json(repo, "checkpoint", "explain", "HEAD", "--json", "--no-pager"),
            self._run(repo, "checkpoint", "explain", "HEAD", "--short", "--no-pager"),
            self._run(repo, "session", "info", sid, "--transcript") if sid else asyncio.sleep(0, None),
        )
        if session is None and checkpoint is None:
            return {"source": "entire-cli", "repo": str(repo), "error": f"Entire returned no session or "
                    f"checkpoint in {repo}. Is `entire enable` set up there?"}
        return {
            "source": "entire-cli",
            "repo": str(repo),
            "session_id": sid,
            "session": _trim(session),
            "checkpoint": _trim(checkpoint),
            "summary": (summary or "").strip()[:2000] or None,
            "transcript_excerpt": self._excerpt(transcript, d),
            "fetched_at": time.time(),
        }

    @staticmethod
    def _excerpt(transcript: str | None, d: Decision) -> list[str]:
        """Transcript lines that mention this action, most recent last."""
        if not transcript:
            return []
        needles = [d.tool] + [str(v)[:80] for v in d.args.values() if isinstance(v, str) and v.strip()]
        lines = [ln for ln in transcript.splitlines() if ln.strip()]
        hits = [ln for ln in lines if any(n in ln for n in needles)] or lines
        return [ln[:LINE_CHARS] for ln in hits[-TRANSCRIPT_LINES:]]
