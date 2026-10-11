"""Map Jev's typed answers + confidence thresholds to ALLOW / BLOCK / ESCALATE.

Rules are evaluated in severity order. Every rule that fires adds a
human-readable reason, and the most severe verdict wins:

  BLOCK     P(safe) is very low, the impact is rated critical, or Jev
            confidently puts the action in a dangerous risk category.
  ESCALATE  Jev is not confident, the action is not clearly safe, the
            impact is serious, the action looks off-task, or the content
            being written looks poor.
  ALLOW     none of the above.
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import Thresholds
from .models import JevSignals, Verdict

DANGEROUS_RISKS = {"data_loss", "exfiltration", "system_damage"}
RISK_LABELS = {
    "none": "no meaningful risk",
    "data_loss": "data loss",
    "exfiltration": "data exfiltration",
    "system_damage": "system damage",
    "unclear": "unclear effects",
}
SEVERITY_LABELS = ["negligible", "minor", "serious", "critical"]


@dataclass(frozen=True)
class PolicyResult:
    verdict: Verdict
    confidence: float
    reasons: list[str]


def severity_label(score: float) -> str:
    return SEVERITY_LABELS[max(0, min(3, round(score)))]


def decide(s: JevSignals, t: Thresholds) -> PolicyResult:
    block: list[str] = []
    escalate: list[str] = []
    risk_p = s.risk_probabilities.get(s.risk, 0.0)

    if s.p_safe < t.block_safe_below:
        block.append(f"Jev rates this action unsafe (P(safe) = {s.p_safe:.2f}).")
    if s.severity >= t.severity_block:
        block.append(f"Potential impact rated {severity_label(s.severity)} ({s.severity:.1f} / 3).")
    if s.risk in DANGEROUS_RISKS and risk_p >= t.risk_block:
        block.append(f"Classified as {RISK_LABELS[s.risk]} risk (p = {risk_p:.2f}).")

    if s.confidence < t.min_confidence:
        escalate.append(f"Jev is uncertain about this action (confidence {s.confidence:.2f}).")
    if t.block_safe_below <= s.p_safe < t.allow_safe_above:
        escalate.append(f"Not confidently safe (P(safe) = {s.p_safe:.2f}).")
    if t.severity_escalate <= s.severity < t.severity_block:
        escalate.append(f"Potential impact rated {severity_label(s.severity)} ({s.severity:.1f} / 3).")
    if s.p_on_task < t.on_task_min:
        escalate.append(f"Looks unrelated to the agent's task (P(on task) = {s.p_on_task:.2f}).")
    if s.output_ok is not None and s.output_ok < t.output_ok_min:
        escalate.append(f"Content being written looks incomplete or wrong (P(ok) = {s.output_ok:.2f}).")
    if s.risk == "unclear" and not block:
        escalate.append(f"Effects cannot be determined from the request (p = {risk_p:.2f}).")

    if block:
        return PolicyResult("BLOCK", s.confidence, block + escalate)
    if escalate:
        return PolicyResult("ESCALATE", s.confidence, escalate)
    return PolicyResult(
        "ALLOW",
        s.confidence,
        [f"Jev rates this action safe (P(safe) = {s.p_safe:.2f}, impact {severity_label(s.severity)})."],
    )
