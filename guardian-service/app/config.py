"""Environment-driven settings. Every value has a demo-friendly default."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env")


def _str(name: str, default: str = "") -> str:
    return os.getenv(name, "").strip() or default


def _float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    return float(raw) if raw else default


def llm_api_key() -> str:
    """LLM_API_KEY, or a Modal proxy token, which Modal expects as `Bearer <id>.<secret>`."""
    token_id, secret = _str("MODAL_PROXY_TOKEN_ID"), _str("MODAL_PROXY_TOKEN_SECRET")
    return _str("LLM_API_KEY") or (f"{token_id}.{secret}" if token_id and secret else "")


@dataclass(frozen=True)
class Thresholds:
    """Policy knobs. See policy.py for how each one is applied."""

    block_safe_below: float = 0.30
    allow_safe_above: float = 0.75
    min_confidence: float = 0.50
    severity_escalate: float = 1.5
    severity_block: float = 2.3
    risk_block: float = 0.70
    on_task_min: float = 0.40
    # Off-task actions escalate only from this impact up (1 = minor); harmless ones are allowed.
    off_task_severity: float = 1.0
    output_ok_min: float = 0.40

    @classmethod
    def from_env(cls) -> Thresholds:
        return cls(
            block_safe_below=_float("GUARDIAN_BLOCK_SAFE_BELOW", cls.block_safe_below),
            allow_safe_above=_float("GUARDIAN_ALLOW_SAFE_ABOVE", cls.allow_safe_above),
            min_confidence=_float("GUARDIAN_MIN_CONFIDENCE", cls.min_confidence),
            severity_escalate=_float("GUARDIAN_SEVERITY_ESCALATE", cls.severity_escalate),
            severity_block=_float("GUARDIAN_SEVERITY_BLOCK", cls.severity_block),
            risk_block=_float("GUARDIAN_RISK_BLOCK", cls.risk_block),
            on_task_min=_float("GUARDIAN_ON_TASK_MIN", cls.on_task_min),
            off_task_severity=_float("GUARDIAN_OFF_TASK_SEVERITY", cls.off_task_severity),
            output_ok_min=_float("GUARDIAN_OUTPUT_OK_MIN", cls.output_ok_min),
        )


@dataclass(frozen=True)
class Settings:
    jev_api_key: str = ""
    jev_model: str = "jev-latest"
    jev_base_url: str = ""

    neatlogs_api_key: str = ""
    neatlogs_project: str = "guardian"
    neatlogs_ingest_url: str = "https://ingest.neatlogs.com"
    neatlogs_app_url: str = "https://app.neatlogs.com"

    entire_repo_path: str = ""
    entire_bin: str = "entire"

    # Explainer: any OpenAI-compatible /chat/completions endpoint (e.g. a Modal Shared Endpoint)
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = "deepseek-ai/DeepSeek-V4.1-Flash"

    db_path: Path = REPO_ROOT / "guardian-service" / "guardian.db"
    escalation_timeout_s: float = 300.0
    # Regex of read-only tool names allowed without a Jev check; empty = check every tool.
    fast_path_tools: str = ""
    thresholds: Thresholds = field(default_factory=Thresholds)

    @classmethod
    def from_env(cls) -> Settings:
        db_path = Path(_str("GUARDIAN_DB_PATH", "guardian-service/guardian.db"))
        return cls(
            jev_api_key=_str("JEV_API_KEY") or _str("TYPESAFE_API_KEY"),
            jev_model=_str("JEV_MODEL", "jev-latest"),
            jev_base_url=_str("JEV_BASE_URL"),
            neatlogs_api_key=_str("NEATLOGS_API_KEY"),
            neatlogs_project=_str("NEATLOGS_PROJECT", "guardian"),
            neatlogs_ingest_url=_str("NEATLOGS_INGEST_URL", "https://ingest.neatlogs.com").rstrip("/"),
            neatlogs_app_url=_str("NEATLOGS_APP_URL", "https://app.neatlogs.com").rstrip("/"),
            entire_repo_path=_str("ENTIRE_REPO_PATH"),
            entire_bin=_str("ENTIRE_BIN", "entire"),
            llm_base_url=_str("LLM_BASE_URL"),
            llm_api_key=llm_api_key(),
            llm_model=_str("LLM_MODEL", "deepseek-ai/DeepSeek-V4.1-Flash"),
            db_path=db_path if db_path.is_absolute() else REPO_ROOT / db_path,
            escalation_timeout_s=_float("GUARDIAN_ESCALATION_TIMEOUT", 300.0),
            fast_path_tools=_str("GUARDIAN_FAST_PATH_TOOLS"),
            thresholds=Thresholds.from_env(),
        )
