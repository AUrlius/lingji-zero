"""coding_run 监工 — Fleet 4.0e。不进 LangGraph。"""

from __future__ import annotations

from urllib.parse import urlparse, urlunparse

JOBS_ROOT_SENTINEL = "$JOBS_ROOT"
INPUT_NEEDLES = ("Waiting for input", "Please choose")


def normalize_git_url(url: str) -> str:
    text = (url or "").strip()
    if not text:
        return ""
    parsed = urlparse(text)
    path = (parsed.path or "").rstrip("/").lower()
    if path.endswith(".git"):
        path = path[:-4]
    host = (parsed.netloc or "").lower()
    scheme = (parsed.scheme or "https").lower()
    if not host:
        return text.lower().rstrip("/").removesuffix(".git")
    return urlunparse((scheme, host, path, "", "", ""))


def git_url_allowed(url: str, allowlist: list[str] | None) -> bool:
    if not url or not allowlist:
        return False
    target = normalize_git_url(url)
    return any(normalize_git_url(item) == target for item in allowlist if item)


def detect_needs_input(log_text: str) -> bool:
    text = log_text or ""
    return any(needle in text for needle in INPUT_NEEDLES)
