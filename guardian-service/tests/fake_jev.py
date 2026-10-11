"""A stand-in for Jev's HTTP API, for tests only.

Answers are in the documented wire format and are picked by keyword so each
test can reach a known verdict through the real JevClient + typesafe-sdk path.
"""

import json

import httpx2


def _answers(p_safe, risk, risk_probs, sev_probs, risk_conf, sev_conf, on_task=0.9):
    return {
        "safe": {"type": "noul", "noul": p_safe},
        "on_task": {"type": "noul", "noul": on_task},
        "risk": {"type": "choice", "choice": risk, "confidence": risk_conf, "probabilities": risk_probs},
        "severity": {
            "type": "score",
            "score": sum(i * p for i, p in enumerate(sev_probs)),
            "confidence": sev_conf,
            "legend": {"0": "Negligible", "1": "Minor", "2": "Serious", "3": "Critical"},
            "probabilities": {str(i): p for i, p in enumerate(sev_probs)},
        },
    }


SAFE = _answers(0.96, "none", {"none": 0.9, "data_loss": 0.04, "exfiltration": 0.02, "system_damage": 0.02,
                               "unclear": 0.02}, [0.8, 0.18, 0.02, 0.0], 0.87, 0.82)
DANGER = _answers(0.03, "data_loss", {"none": 0.01, "data_loss": 0.85, "exfiltration": 0.01, "system_damage": 0.12,
                                      "unclear": 0.01}, [0.0, 0.01, 0.08, 0.91], 0.81, 0.9)
UNCERTAIN = _answers(0.56, "unclear", {"none": 0.25, "data_loss": 0.2, "exfiltration": 0.04, "system_damage": 0.1,
                                       "unclear": 0.41}, [0.12, 0.42, 0.36, 0.1], 0.26, 0.4)


def handler(request: httpx2.Request) -> httpx2.Response:
    body = json.loads(request.content)
    action = json.dumps(body["state"]["proposed_action"])
    answers = DANGER if "rm -rf" in action else UNCERTAIN if "--apply" in action else SAFE
    if "output_ok" in body["questions"]:
        answers = {**answers, "output_ok": {"type": "noul", "noul": 0.9}}
    return httpx2.Response(200, json={"model": "jev-test", "answers": answers, "usage": {"input_tokens": 1}})


def down(request: httpx2.Request) -> httpx2.Response:
    return httpx2.Response(503, json={"error": {"message": "service unavailable"}})
