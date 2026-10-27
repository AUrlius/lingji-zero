"""Record that a hallucination check ran for this decision.

The check looks for ``[[citation]]`` markers that are not in the retrieved
context. It stores only whether the check ran and whether a marker was missing.
It does not score accuracy and it does not keep the reply text.
"""

from __future__ import annotations

import re

from lingji_agent.observability.decision_trace import note_hallucination_check

_CITATION = re.compile(r"\[\[([^\]]{1,80})\]\]")


def run_hallucination_check(reply: str, retrieved_context: str) -> None:
    source = retrieved_context or ""
    unsupported = False
    for citation in _CITATION.findall(reply or ""):
        if citation not in source:
            unsupported = True
            break
    note_hallucination_check(unsupported_citation=unsupported)
