"""红队用例回归 — 四期 4.1（YAML 驱动，无 LLM）"""

from pathlib import Path

import pytest
import yaml

from lingji_agent.execution.sandbox import validate_command, validate_path
from lingji_agent.security.guardrails import SecurityGuardrail
from lingji_agent.security.sanitizer import AdversarialTextSanitizer

_CASES_PATH = Path(__file__).parent / "red_team" / "cases.yaml"


def _load_cases() -> list[dict]:
    with open(_CASES_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f) or []


CASES = _load_cases()


@pytest.fixture
def guardrail():
    return SecurityGuardrail()


@pytest.fixture
def sanitizer():
    return AdversarialTextSanitizer()


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_red_team_case(case, guardrail, sanitizer):
    layer = case["layer"]
    expect = case["expect"]
    payload = case.get("payload", "")
    context = case.get("context", "")

    if layer == "guardrail":
        result = guardrail.inspect(payload, context=context)
        if expect == "blocked":
            assert not result.allowed, case["id"]
            if case.get("rule_id"):
                assert result.rule_id == case["rule_id"], case["id"]
        elif expect == "allowed":
            assert result.allowed, case["id"]
        else:
            pytest.fail(f"unknown guardrail expect: {expect}")

    elif layer == "sanitizer":
        result = sanitizer.sanitize(payload)
        if expect == "force_docker":
            assert result.threats_detected > 0, case["id"]
        else:
            pytest.fail(f"unknown sanitizer expect: {expect}")

    elif layer == "sandbox":
        if expect == "command_rejected":
            cmd = case.get("command") or payload.split()
            ok, _reason = validate_command(cmd)
            assert not ok, case["id"]
        elif expect == "path_rejected":
            path = case.get("path") or payload
            assert not validate_path(path), case["id"]
        else:
            pytest.fail(f"unknown sandbox expect: {expect}")

    else:
        pytest.fail(f"unknown layer: {layer}")
