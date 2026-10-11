import pytest

from app.config import Thresholds
from app.models import JevSignals
from app.policy import decide

SAFE = dict(
    p_safe=0.96, p_on_task=0.9, risk="none",
    risk_probabilities={"none": 0.9, "data_loss": 0.05, "exfiltration": 0.02, "system_damage": 0.02, "unclear": 0.01},
    risk_confidence=0.87, severity=0.2, severity_confidence=0.85,
    severity_probabilities={"0": 0.8, "1": 0.2, "2": 0.0, "3": 0.0}, output_ok=None, confidence=0.85,
)


def signals(**overrides) -> JevSignals:
    return JevSignals(**{**SAFE, **overrides})


def verdict(**overrides) -> str:
    return decide(signals(**overrides), Thresholds()).verdict


def test_confident_safe_action_is_allowed():
    assert verdict() == "ALLOW"


@pytest.mark.parametrize(
    "overrides",
    [
        {"p_safe": 0.1},
        {"severity": 2.6},
        {"risk": "data_loss", "risk_probabilities": {**SAFE["risk_probabilities"], "data_loss": 0.8}},
        {"risk": "exfiltration", "risk_probabilities": {**SAFE["risk_probabilities"], "exfiltration": 0.75}},
    ],
)
def test_block_rules(overrides):
    assert verdict(**overrides) == "BLOCK"


@pytest.mark.parametrize(
    "overrides",
    [
        {"confidence": 0.3},
        {"p_safe": 0.6},
        {"severity": 1.8},
        {"p_on_task": 0.2, "severity": 1.1},  # off-task and could change something
        {"output_ok": 0.2},
        {"risk": "unclear", "risk_probabilities": {**SAFE["risk_probabilities"], "unclear": 0.4}},
        # a dangerous category Jev isn't sure about is a question for a human, not a block
        {"p_safe": 0.6, "risk": "data_loss", "risk_probabilities": {**SAFE["risk_probabilities"], "data_loss": 0.5}},
    ],
)
def test_escalate_rules(overrides):
    assert verdict(**overrides) == "ESCALATE"


def test_harmless_off_task_actions_are_allowed_with_a_note():
    # From a live run: the agent read README.md while investigating; Jev called it off-task but harmless.
    result = decide(signals(p_safe=0.94, p_on_task=0.25, severity=0.33, confidence=0.66), Thresholds())
    assert result.verdict == "ALLOW"
    assert any("unrelated to the task" in r for r in result.reasons)
    assert decide(signals(p_on_task=0.25, severity=0.33), Thresholds(off_task_severity=0.0)).verdict == "ESCALATE"


def test_block_wins_and_keeps_every_reason():
    result = decide(signals(p_safe=0.1, severity=2.8, confidence=0.3), Thresholds())
    assert result.verdict == "BLOCK"
    assert any("unsafe" in r for r in result.reasons)
    assert any("critical" in r for r in result.reasons)
    assert any("uncertain" in r for r in result.reasons)


def test_thresholds_are_configurable():
    s = signals(p_safe=0.6)
    assert decide(s, Thresholds()).verdict == "ESCALATE"
    assert decide(s, Thresholds(allow_safe_above=0.5)).verdict == "ALLOW"
    assert decide(s, Thresholds(block_safe_below=0.7)).verdict == "BLOCK"
