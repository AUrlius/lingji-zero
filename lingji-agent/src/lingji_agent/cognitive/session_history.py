"""从 LangGraph checkpoint 提取 Web UI 可渲染的会话历史。"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_UI_HISTORY_LIMIT = 50


def _message_text(msg: dict[str, Any]) -> str:
    content = msg.get("content", "")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                parts.append(str(part.get("text", "")))
            elif isinstance(part, str):
                parts.append(part)
        return "\n".join(p for p in parts if p).strip()
    return str(content).strip() if content else ""


def extract_ui_history(
    messages: list[dict[str, Any]] | None,
    *,
    limit: int = DEFAULT_UI_HISTORY_LIMIT,
) -> list[dict[str, str]]:
    """将 LangGraph messages 转为 Web UI history: [{role: user|agent, text}]。"""
    if not messages:
        return []
    out: list[dict[str, str]] = []
    for msg in messages:
        role = msg.get("role")
        if role in ("system", "tool"):
            continue
        if role == "user":
            text = _message_text(msg)
            if text:
                out.append({"role": "user", "text": text})
        elif role == "assistant":
            text = _message_text(msg)
            if text:
                out.append({"role": "agent", "text": text})
    if len(out) > limit:
        out = out[-limit:]
    return out


async def load_thread_ui_history(
    graph,
    thread_id: str,
    *,
    connector=None,
    registry=None,
    hitl_manager=None,
    sanitizer_force_docker: bool = True,
    limit: int = DEFAULT_UI_HISTORY_LIMIT,
) -> list[dict[str, str]]:
    """读取指定 thread 的 checkpoint 并返回 UI 历史。"""
    from lingji_agent.cognitive.orchestrator import build_run_config

    if not thread_id:
        return []
    config = build_run_config(
        thread_id=thread_id,
        connector=connector,
        registry=registry,
        hitl_manager=hitl_manager,
        sanitizer_force_docker=sanitizer_force_docker,
    )
    try:
        snap = await graph.aget_state(config)
    except Exception as e:
        logger.warning("读取 thread 历史失败 thread=%s: %s", thread_id, e)
        return []
    if not snap or not snap.values:
        return []
    messages = snap.values.get("messages") or []
    return extract_ui_history(messages, limit=limit)
