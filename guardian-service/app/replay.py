"""Replay recorded decisions through the current policy and fast path, without calling Jev.

Every decision keeps Jev's typed answers, so a policy or fast-path change can be
measured on real traffic before it ships: which verdicts change, and how many
Jev calls and human escalations it saves.

    python dev.py replay                         every recorded decision
    python dev.py replay --session run-634cdc98  one agent session
    python dev.py replay --fast-path "read_file|view_file"
    python dev.py replay --session run-634cdc98 --trace   also send the comparison to NeatLogs

The replay assumes the agent would make the same calls. In a live run, fewer
escalations also mean the agent keeps going instead of waiting, so later steps
can differ.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import asdict, dataclass
from typing import Any

import httpx

from .config import REPO_ROOT, Settings
from .db import DecisionStore
from .models import Decision
from .policy import decide

FAST_PATH_REASON = "Read-only tool: allowed by the fast path without a Jev check."


@dataclass
class Row:
    id: str
    session_id: str | None
    tool: str
    args: dict[str, Any]
    before: str  # verdict recorded live
    after: str  # verdict under the current policy and fast path
    jev_before: bool  # Jev was asked live
    jev_after: bool  # Jev would be asked now
    reasons_after: list[str]


def replay(decisions: list[Decision], settings: Settings, fast_path: str | None = None) -> dict[str, Any]:
    """Decisions Jev couldn't answer (outage) or never saw (fast path) can't be re-scored and are skipped."""
    pattern = fast_path if fast_path is not None else settings.fast_path_tools
    skip = re.compile(pattern) if pattern else None
    rows, skipped = [], 0
    for d in sorted(decisions, key=lambda x: x.created_at):
        if skip and skip.fullmatch(d.tool):
            after, jev_after, reasons = "ALLOW", False, [FAST_PATH_REASON]
        elif d.jev is not None:
            result = decide(d.jev.signals, settings.thresholds)
            after, jev_after, reasons = result.verdict, True, result.reasons
        else:
            skipped += 1
            continue
        rows.append(Row(d.id, d.session_id, d.tool, d.args, d.verdict, after, d.jev is not None, jev_after, reasons))

    def count(attr: str, value: Any) -> int:
        return sum(getattr(r, attr) == value for r in rows)

    totals = {
        "decisions": len(rows),
        "skipped": skipped,
        "jev_calls_before": count("jev_before", True),
        "jev_calls_after": count("jev_after", True),
        **{f"{v.lower()}_before": count("before", v) for v in ("ALLOW", "ESCALATE", "BLOCK")},
        **{f"{v.lower()}_after": count("after", v) for v in ("ALLOW", "ESCALATE", "BLOCK")},
        "changed": sum(r.before != r.after for r in rows),
    }
    return {"fast_path_tools": pattern or "", "thresholds": asdict(settings.thresholds), "totals": totals,
            "rows": [asdict(r) for r in rows]}


def trace_payload(report: dict[str, Any], session: str | None, project: str) -> dict[str, Any]:
    """One NeatLogs trace: an EVALUATOR span per decision, live verdict vs replayed verdict.
    With a session it joins that session's decision traces in NeatLogs."""
    children = [{
        "name": f"replay {r['tool']}",
        "kind": "EVALUATOR",
        "input": json.dumps({"tool": r["tool"], "args": r["args"]}, ensure_ascii=False),
        "output": json.dumps({"before": r["before"], "after": r["after"], "jev_call": r["jev_after"],
                              "reasons": r["reasons_after"]}, ensure_ascii=False),
        "metadata": {"guardian.decision_id": r["id"], "replay.before": r["before"], "replay.after": r["after"],
                     "replay.changed": r["before"] != r["after"]},
    } for r in report["rows"]]
    payload = {
        "name": f"guardian.replay {session or 'all'}",
        "project": project,
        "input": json.dumps({"fast_path_tools": report["fast_path_tools"], "thresholds": report["thresholds"]}),
        "output": json.dumps(report["totals"]),
        "metadata": {f"replay.{k}": v for k, v in report["totals"].items()},
        "children": children,
    }
    if session:
        payload["attributes"] = {"neatlogs.session.id": session}
    return payload


def send_trace(payload: dict[str, Any], settings: Settings, attempts: int = 3) -> str:
    """POST to NeatLogs' HTTP ingest, retrying 5xx; returns the trace URL or raises with the reason."""
    error = ""
    for attempt in range(attempts):
        try:
            resp = httpx.post(f"{settings.neatlogs_ingest_url}/v1/trace", json=payload, timeout=15,
                              headers={"x-api-key": settings.neatlogs_api_key})
            resp.raise_for_status()
            return f"{settings.neatlogs_app_url}/traces/{resp.json()['trace_id']}"
        except httpx.HTTPStatusError as exc:
            error = f"NeatLogs ingest returned {exc.response.status_code}: {exc.response.text[:200]}"
            if exc.response.status_code < 500:
                break
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            error = f"NeatLogs ingest failed: {exc}"
        time.sleep(2**attempt)
    raise RuntimeError(error)


def _short(args: dict[str, Any], limit: int = 48) -> str:
    text = json.dumps(args, ensure_ascii=False)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def print_report(report: dict[str, Any]) -> None:
    t = report["totals"]
    print(f"Replayed {t['decisions']} decisions ({t['skipped']} skipped: no Jev answers to re-score)")
    print(f"fast path: {report['fast_path_tools'] or 'off'}\n")
    for r in report["rows"]:
        mark = "  " if r["before"] == r["after"] else "→ "
        print(f"{mark}{r['tool']:<12} {_short(r['args']):<50} {r['before']:<9} {r['after']:<9}"
              f"{'' if r['jev_after'] else '(no Jev call)'}")
        if r["before"] != r["after"]:
            print(f"     {r['reasons_after'][-1]}")
    print(f"\n{'':<14}{'before':>8}{'after':>8}")
    for label, key in [("Jev calls", "jev_calls"), ("allowed", "allow"), ("escalated", "escalate"), ("blocked", "block")]:
        print(f"{label:<14}{t[key + '_before']:>8}{t[key + '_after']:>8}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Replay recorded decisions through the current policy.")
    parser.add_argument("--session", help="only this session id")
    parser.add_argument("--fast-path", help="regex of tools to skip Jev for (default: GUARDIAN_FAST_PATH_TOOLS)")
    parser.add_argument("--save", action="store_true", help="also write evidence/replays/<time>.json")
    parser.add_argument("--trace", action="store_true", help="also send the comparison to NeatLogs")
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    store = DecisionStore(settings.db_path)
    decisions = [d for d in store.list(10_000) if not args.session or d.session_id == args.session]
    store.close()
    report = replay(decisions, settings, args.fast_path)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print_report(report)
    if args.trace:
        if not settings.neatlogs_api_key:
            sys.exit("--trace needs NEATLOGS_API_KEY")
        try:
            report["neatlogs_url"] = send_trace(trace_payload(report, args.session, settings.neatlogs_project), settings)
            print(f"\nNeatLogs trace: {report['neatlogs_url']}")
        except RuntimeError as exc:
            print(f"\nNeatLogs trace failed: {exc}")
    if args.save:
        out = REPO_ROOT / "evidence" / "replays" / f"{time.strftime('%Y%m%d-%H%M%S')}-{args.session or 'all'}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"session": args.session, **report}, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nsaved {out.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
