"""机要控制面 — CMD_HERMES_SESSION（不进 LangGraph / 秘书聊天）。

4.0d-4a：配置驱动的 start/stop/health/attach。
4.0d-4b：仅当 chat_url 指向本机 loopback 才 channel_ready。
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import time
from collections.abc import Callable, Sequence
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

NO_START_CMD = (
    "未配置 hermes_session.start_cmd。"
    "请在空城记本地 default_config.yaml 写入 argv 列表后重启 Agent。"
)
NO_CHAT_API = "进程在线，但未配置本机 chat_url，通道未接通。破窗请用飞书/Telegram 原生 Hermes。"
KICK_TO_SECRETARY = "机要只办空城记本机事务。跨机（发给青铜剑/上海）请走中间栏交给秘书。"
NOT_LOOPBACK = "health_url / chat_url 只允许 127.0.0.1 或 localhost。"
BAD_ARGV = "命令必须是不含 shell 元字符的 argv 列表。"

_FLEET_KICK_NEEDLES = (
    "发给青铜剑",
    "发到青铜剑",
    "发到上海",
    "发给上海",
    "fleet_send_file",
    "job_invoke",
    "交给青铜剑",
    "派给青铜剑",
    "lingji-pc",
)

_SHELL_META = set(";&|`$<>\n\r")


def argv_list(cmd: Sequence[Any] | None) -> list[str]:
    """校验 argv；禁止 shell 拼接。"""
    if not cmd:
        return []
    out: list[str] = []
    for part in cmd:
        if not isinstance(part, str) or not part.strip():
            raise ValueError(BAD_ARGV)
        if any(ch in part for ch in _SHELL_META):
            raise ValueError(BAD_ARGV)
        out.append(part)
    return out


def is_loopback_url(url: str) -> bool:
    text = (url or "").strip()
    if not text:
        return False
    parsed = urlparse(text)
    if parsed.scheme not in ("http", "https"):
        return False
    host = (parsed.hostname or "").lower()
    return host in ("127.0.0.1", "localhost", "::1")


def fleet_kick_reason(text: str) -> str:
    lower = (text or "").lower()
    for needle in _FLEET_KICK_NEEDLES:
        if needle.lower() in lower:
            return KICK_TO_SECRETARY
    return ""


def probe_hermes_running(process_names: Sequence[str] | None = None) -> bool:
    """pgrep -x 配置的进程名。"""
    names = [n for n in (process_names or ("hermes", "openclaw")) if isinstance(n, str) and n.strip()]
    pgrep = shutil.which("pgrep")
    if not pgrep or not names:
        return False
    for name in names:
        try:
            result = subprocess.run(
                [pgrep, "-x", name.strip()],
                capture_output=True,
                timeout=2,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if result.returncode == 0:
            return True
    return False


def probe_health_url(url: str, *, get=None) -> bool:
    if not is_loopback_url(url):
        return False
    getter = get or _http_get_ok
    try:
        return bool(getter(url))
    except Exception as exc:
        logger.warning("hermes health_url failed: %s", exc)
        return False


def _http_get_ok(url: str) -> bool:
    import httpx

    with httpx.Client(timeout=2.0) as client:
        resp = client.get(url)
        return 200 <= resp.status_code < 300


def _payload(
    action: str,
    *,
    hermes_status: str,
    channel_ready: bool,
    reason: str,
    ok: bool = True,
) -> dict[str, Any]:
    return {
        "action": action,
        "unimplemented": False,
        "ok": ok,
        "hermes_status": hermes_status,
        "channel_ready": channel_ready,
        "reason": reason,
    }


class HermesSessionClient:
    """本机 HTTP 会话适配。chat_url 必须是 loopback。"""

    def __init__(self, chat_url: str, timeout_sec: float = 60.0, *, post=None):
        self.chat_url = (chat_url or "").strip()
        self.timeout_sec = timeout_sec
        self._post = post

    def available(self) -> bool:
        return is_loopback_url(self.chat_url)

    def send_chat(self, text: str) -> str:
        if not self.available():
            raise RuntimeError(NO_CHAT_API)
        poster = self._post or _http_post_chat
        return poster(self.chat_url, text, self.timeout_sec)


def _http_post_chat(url: str, text: str, timeout_sec: float) -> str:
    import httpx

    with httpx.Client(timeout=timeout_sec) as client:
        resp = client.post(url, json={"text": text})
        resp.raise_for_status()
        ctype = resp.headers.get("content-type") or ""
        if "json" in ctype:
            data = resp.json()
            if isinstance(data, dict):
                for key in ("text", "reply", "message", "content"):
                    val = data.get(key)
                    if isinstance(val, str) and val.strip():
                        return val.strip()
                return str(data)
        body = (resp.text or "").strip()
        if not body:
            raise RuntimeError("本机 Hermes 回空响应")
        return body


def _channel_ready(cfg: Any, running: bool) -> bool:
    url = str(getattr(cfg, "chat_url", "") or "").strip()
    return bool(running and is_loopback_url(url))


def _combined_probe(cfg: Any, probe: Callable[[], bool] | None) -> bool:
    if probe is not None:
        try:
            return bool(probe())
        except Exception as exc:
            logger.warning("hermes probe failed: %s", exc)
            return False
    url = str(getattr(cfg, "health_url", "") or "").strip()
    if url and is_loopback_url(url) and probe_health_url(url):
        return True
    names = list(getattr(cfg, "process_names", None) or ("hermes", "openclaw"))
    return probe_hermes_running(names)


def _wait_running(cfg: Any, probe: Callable[[], bool] | None, timeout: float) -> bool:
    deadline = time.monotonic() + max(float(timeout or 0), 0.0)
    while True:
        if _combined_probe(cfg, probe):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.2)


def _wait_stopped(cfg: Any, probe: Callable[[], bool] | None, timeout: float) -> bool:
    deadline = time.monotonic() + max(float(timeout or 0), 0.0)
    while True:
        if not _combined_probe(cfg, probe):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.2)


def _run_argv(
    argv: list[str],
    *,
    timeout: float = 20.0,
    detach: bool = False,
    runner: Callable[..., Any] | None = None,
) -> tuple[int, str]:
    if runner is not None:
        return runner(argv, detach=detach)
    if detach:
        subprocess.Popen(  # noqa: S603 — argv 已经过 argv_list 校验
            argv,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return 0, ""
    result = subprocess.run(  # noqa: S603
        argv,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    err = (result.stderr or result.stdout or b"").decode("utf-8", errors="replace")[:400]
    return result.returncode, err


def handle_hermes_session(
    action: str,
    *,
    cfg: Any | None = None,
    probe: Callable[[], bool] | None = None,
    runner: Callable[..., Any] | None = None,
    client: HermesSessionClient | None = None,
    text: str = "",
    settle_sec: float | None = None,
) -> dict[str, Any]:
    """返回写入 AGENT_RES.payload 的字段（调用方再补 status/target_*）。"""
    from lingji_agent.foundation.config import HermesSessionConfig

    session_cfg = cfg if cfg is not None else HermesSessionConfig()
    wait = float(
        settle_sec if settle_sec is not None else getattr(session_cfg, "start_wait_sec", 3.0) or 0
    )
    act = (action or "health").strip().lower()
    if act not in ("start", "stop", "health", "chat"):
        act = "health"

    if act == "chat":
        return handle_hermes_chat(text, cfg=session_cfg, probe=probe, client=client)

    running = _combined_probe(session_cfg, probe)
    ready = _channel_ready(session_cfg, running)

    if act == "health":
        reason = (
            ("" if ready else NO_CHAT_API)
            if running
            else "机要未在跑。点启动前请确认空城记已配置 start_cmd。"
        )
        return _payload(
            "health",
            hermes_status="online" if running else "off",
            channel_ready=ready,
            reason=reason,
            ok=True,
        )

    if act == "start":
        if running:
            return _payload(
                "start",
                hermes_status="online",
                channel_ready=ready,
                reason="已附着正在运行的机要，未新开进程。" + ("" if ready else " " + NO_CHAT_API),
            )
        try:
            start_cmd = argv_list(getattr(session_cfg, "start_cmd", None))
        except ValueError as exc:
            return _payload("start", hermes_status="off", channel_ready=False, reason=str(exc), ok=False)
        if not start_cmd:
            return _payload("start", hermes_status="off", channel_ready=False, reason=NO_START_CMD, ok=False)
        exe = start_cmd[0]
        if not shutil.which(exe) and not _path_exists(exe):
            return _payload(
                "start",
                hermes_status="off",
                channel_ready=False,
                reason=f"找不到可执行文件：{exe}。请确认已安装 Hermes。",
                ok=False,
            )
        try:
            code, err = _run_argv(start_cmd, detach=True, runner=runner)
        except FileNotFoundError:
            return _payload(
                "start",
                hermes_status="off",
                channel_ready=False,
                reason=f"找不到可执行文件：{exe}。",
                ok=False,
            )
        except Exception as exc:
            return _payload(
                "start",
                hermes_status="off",
                channel_ready=False,
                reason=f"启动失败：{exc}",
                ok=False,
            )
        if code != 0:
            return _payload(
                "start",
                hermes_status="off",
                channel_ready=False,
                reason=err or f"启动退出码 {code}",
                ok=False,
            )
        running = _wait_running(session_cfg, probe, wait)
        if not running:
            return _payload(
                "start",
                hermes_status="off",
                channel_ready=False,
                reason="已执行 start_cmd，但随后探测不到进程。请检查命令或端口占用。",
                ok=False,
            )
        ready = _channel_ready(session_cfg, True)
        return _payload(
            "start",
            hermes_status="online",
            channel_ready=ready,
            reason="机要已启动。" + ("" if ready else " " + NO_CHAT_API),
        )

    # stop
    if not running:
        return _payload("stop", hermes_status="off", channel_ready=False, reason="机要已不在运行。")
    try:
        stop_cmd = argv_list(getattr(session_cfg, "stop_cmd", None))
    except ValueError as exc:
        return _payload("stop", hermes_status="online", channel_ready=ready, reason=str(exc), ok=False)
    names = [n for n in (getattr(session_cfg, "process_names", None) or ()) if isinstance(n, str) and n.strip()]
    argv = stop_cmd
    if not argv:
        pkill = shutil.which("pkill")
        if not pkill or not names:
            return _payload(
                "stop",
                hermes_status="online",
                channel_ready=ready,
                reason="未配置 stop_cmd，且无法 pkill 配置的 process_names。",
                ok=False,
            )
        argv = [pkill, "-x", names[0]]
    try:
        code, err = _run_argv(argv, detach=False, runner=runner)
    except Exception as exc:
        return _payload(
            "stop",
            hermes_status="online",
            channel_ready=ready,
            reason=f"关闭失败：{exc}",
            ok=False,
        )
    if not _wait_stopped(session_cfg, probe, wait):
        return _payload(
            "stop",
            hermes_status="online",
            channel_ready=_channel_ready(session_cfg, True),
            reason=err or "已执行 stop，但进程仍在。",
            ok=False,
        )
    return _payload("stop", hermes_status="off", channel_ready=False, reason="机要已关闭。")


def handle_hermes_chat(
    text: str,
    *,
    cfg: Any | None = None,
    probe: Callable[[], bool] | None = None,
    client: HermesSessionClient | None = None,
) -> dict[str, Any]:
    from lingji_agent.foundation.config import HermesSessionConfig

    session_cfg = cfg if cfg is not None else HermesSessionConfig()
    kick = fleet_kick_reason(text)
    if kick:
        running = _combined_probe(session_cfg, probe)
        return {
            **_payload(
                "chat",
                hermes_status="online" if running else "off",
                channel_ready=_channel_ready(session_cfg, running),
                reason=kick,
                ok=False,
            ),
            "text": kick,
        }
    running = _combined_probe(session_cfg, probe)
    if not running:
        msg = "机要未在跑，请先点启动。"
        return {**_payload("chat", hermes_status="off", channel_ready=False, reason=msg, ok=False), "text": msg}
    chat_url = str(getattr(session_cfg, "chat_url", "") or "").strip()
    if not is_loopback_url(chat_url):
        return {
            **_payload("chat", hermes_status="online", channel_ready=False, reason=NO_CHAT_API, ok=False),
            "text": NO_CHAT_API,
        }
    sess = client or HermesSessionClient(
        chat_url,
        timeout_sec=float(getattr(session_cfg, "chat_timeout_sec", 60) or 60),
    )
    try:
        reply = sess.send_chat(text)
    except Exception as exc:
        msg = f"本机会话失败：{exc}"
        return {
            **_payload("chat", hermes_status="online", channel_ready=True, reason=msg, ok=False),
            "text": msg,
        }
    return {
        **_payload("chat", hermes_status="online", channel_ready=True, reason="", ok=True),
        "text": reply,
    }


def _path_exists(path: str) -> bool:
    from pathlib import Path

    try:
        return Path(path).expanduser().exists()
    except OSError:
        return False
