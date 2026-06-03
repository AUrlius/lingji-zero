"""认知层安全护栏 — Sprint 9 子集（四期 4.1）

规则引擎：在 LLM 调用前检测明显恶意意图并硬阻断。
与 sanitizer 分工：Guardrail 阻断意图；Sanitizer 清洗隐蔽字符并触发 Docker 升级。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class GuardrailRule:
    rule_id: str
    description: str
    match: Callable[[str], bool]


@dataclass
class GuardrailResult:
    allowed: bool
    reason: str = ""
    rule_id: str = ""


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    lower = text.lower()
    return any(n in lower for n in needles)


def _compile_pattern(rule_id: str, description: str, pattern: str) -> GuardrailRule:
    compiled = re.compile(pattern, re.IGNORECASE | re.DOTALL)

    def match(text: str) -> bool:
        return bool(compiled.search(text))

    return GuardrailRule(rule_id=rule_id, description=description, match=match)


def default_guardrail_rules() -> list[GuardrailRule]:
    """内置 MVP 规则（确定性，无 ML）。"""
    return [
        GuardrailRule(
            rule_id="inj.ignore_previous",
            description="Prompt injection: ignore previous instructions",
            match=lambda t: _contains_any(
                t,
                (
                    "ignore previous",
                    "ignore all previous",
                    "disregard previous",
                    "忽略之前",
                    "忽略先前",
                    "无视之前",
                ),
            ),
        ),
        GuardrailRule(
            rule_id="inj.role_override",
            description="Prompt injection: role override",
            match=lambda t: _contains_any(
                t,
                ("you are now", "you are a dan", "jailbreak", "越狱"),
            ),
        ),
        GuardrailRule(
            rule_id="inj.system_separator",
            description="Prompt injection: system separator",
            match=lambda t: "---system---" in t.lower() or "====end====" in t.lower(),
        ),
        GuardrailRule(
            rule_id="destruct.rm_rf_root",
            description="Destructive rm -rf /",
            match=lambda t: "rm -rf /" in t.lower() or "rm -rf  /" in t.lower(),
        ),
        GuardrailRule(
            rule_id="destruct.chmod_777",
            description="Dangerous chmod 777",
            match=lambda t: "chmod 777" in t.lower(),
        ),
        GuardrailRule(
            rule_id="destruct.docker_privileged",
            description="Privileged Docker container",
            match=lambda t: _contains_any(
                t,
                ("docker run --privileged", "docker run -it --privileged"),
            ),
        ),
        GuardrailRule(
            rule_id="destruct.fork_bomb",
            description="Fork bomb pattern",
            match=lambda t: ":(){ :|:& };:" in t or ":(){:|:&};:" in t.replace(" ", ""),
        ),
        _compile_pattern(
            "exfil.http_exfiltration",
            "Data exfiltration via HTTP client",
            r"(curl|wget)\s+\S*(https?://[^\s'\"]+|evil\.com|attacker\.com)"
            r"|requests\.(post|get)\s*\(\s*['\"]https?://",
        ),
        GuardrailRule(
            rule_id="exfil.sensitive_path",
            description="Sensitive credential path access",
            match=lambda t: _contains_any(
                t,
                (
                    "~/.ssh",
                    "id_rsa",
                    ".aws/credentials",
                    "/etc/shadow",
                    "/etc/passwd",
                ),
            ),
        ),
    ]


class SecurityGuardrail:
    """LLM 前安检门：命中规则则阻断请求。"""

    def __init__(self, rules: list[GuardrailRule] | None = None):
        self._rules = rules if rules is not None else default_guardrail_rules()

    def inspect(self, user_input: str, *, context: str = "") -> GuardrailResult:
        combined = f"{user_input}\n{context}".strip()
        if not combined:
            return GuardrailResult(allowed=True)

        for rule in self._rules:
            if rule.match(combined):
                return GuardrailResult(
                    allowed=False,
                    reason=rule.description,
                    rule_id=rule.rule_id,
                )

        return GuardrailResult(allowed=True)

    @staticmethod
    def block_message(result: GuardrailResult) -> str:
        """对用户可见的阻断文案（不泄露完整规则列表）。"""
        return (
            "⚠️ 请求被安全策略拦截：检测到可能危害系统或泄露敏感信息的指令。"
            "请修改请求后重试。若认为误拦，请联系管理员。"
        )
