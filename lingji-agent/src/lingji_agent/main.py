"""灵机计划 Agent 入口。

启动序列：PID 锁 → 配置 → DB → LLM → Graph → Gateway。
一次对话决策或一次 Skill 在 `runtime.decision`，不在这个文件里。
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from lingji_agent.cognitive.llm_provider import create_connector
from lingji_agent.cognitive.orchestrator import build_graph
from lingji_agent.cognitive.prompt_manager import PromptManager
from lingji_agent.execution.hitl import HITLManager
from lingji_agent.execution.registry import registry
from lingji_agent.execution.sandbox import create_sandbox
from lingji_agent.execution.tools import (  # noqa: F401  触发 @registry.register
    file_tools,
    fleet_tools,
    fs_tools,
    hitl_delegate_tools,
    job_tools,
    sys_tools,
)
from lingji_agent.foundation import run_metrics
from lingji_agent.foundation.checkpointer import open_checkpointer
from lingji_agent.foundation.config import load_config
from lingji_agent.foundation.db import init_db
from lingji_agent.foundation.logger import get_logger, setup_logging
from lingji_agent.foundation.pid_lock import (
    acquire_pid_lock,
    agent_status,
    release_pid_lock,
    stop_running_agent,
)
from lingji_agent.foundation.scheduler import bind_scheduler_config
from lingji_agent.memory import create_memory_manager
from lingji_agent.network.incoming_files import validate_incoming_dir_config
from lingji_agent.network.ws_client import GatewayClient
from lingji_agent.observability import init_observability, shutdown_observability
from lingji_agent.runtime.service import AgentService
from lingji_agent.runtime.web_client import resolve_web_client as _resolve_web_client

logger = get_logger(__name__)

__all__ = ["cli", "main", "_resolve_web_client"]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="灵机 Agent Client")
    parser.add_argument("config_path", nargs="?", default=None, help="配置文件路径（可选）")
    parser.add_argument("--stop", action="store_true", help="停止已在运行的 Agent 并清理 PID 锁")
    parser.add_argument("--status", action="store_true", help="查看 Agent 是否在运行")
    return parser.parse_args(argv)


def _export_network_env(config) -> None:
    os.environ.setdefault("LINGJI_GATEWAY_HOST", config.network.gateway_host)
    os.environ.setdefault("LINGJI_GATEWAY_PORT", str(config.network.gateway_port))
    if config.network.auth_token:
        os.environ.setdefault("LINGJI_AUTH_TOKEN", config.network.auth_token)
    os.environ.setdefault("LINGJI_DEVICE_ID", config.network.device_id)
    if config.network.display_name:
        os.environ.setdefault("LINGJI_DISPLAY_NAME", config.network.display_name)
    if config.network.aliases:
        os.environ.setdefault("LINGJI_AGENT_ALIASES", ",".join(config.network.aliases))


async def main(config_path: str | None = None):
    if not acquire_pid_lock():
        sys.exit(1)

    config = load_config(config_path)
    bind_scheduler_config(config)
    if config.scheduler.enabled or config.scheduler.scheduler_agent_id:
        logger.info(
            "scheduler: enabled=%s scheduler_agent_id=%s guardians=%s",
            config.scheduler.enabled,
            config.scheduler.scheduler_agent_id or "(auto)",
            config.scheduler.guardian_executor_ids,
        )
    _export_network_env(config)
    setup_logging(trace_log=config.observability.trace_log_enabled and config.observability.enabled)
    init_observability(config.observability)
    logger.info("灵机计划 Agent 启动中...")
    logger.info("Gateway: %s:%s", config.network.gateway_host, config.network.gateway_port)
    logger.info("Device: %s", config.network.device_id)
    try:
        incoming_resolved = validate_incoming_dir_config(config.network.incoming_dir)
    except ValueError as exc:
        logger.error("%s", exc)
        sys.exit(1)
    logger.info("incoming_dir: %s", incoming_resolved)

    sandbox = create_sandbox()
    logger.info("沙箱: %s (docker_available=%s)", type(sandbox).__name__, sandbox.is_available())

    db = init_db()
    logger.info("数据库已就绪")
    hitl_timeout_sec = float(config.security.hitl_timeout_sec)
    hitl = HITLManager(db_conn=db, default_timeout=hitl_timeout_sec)
    logger.info("HITL 管理器已就绪 (timeout=%ds)", int(hitl_timeout_sec))

    connector = create_connector(config)
    logger.info("LLM: %s (%s)", connector.model_name, type(connector).__name__)
    prompt = PromptManager(device_id=config.network.device_id, registry=registry)
    memory = create_memory_manager(config.memory, llm_connector=connector)
    memory_warmup: asyncio.Task | None = None
    if config.memory.enabled:
        logger.info("记忆层已启用 (后台预热，不阻塞 Gateway 连接)")
        memory_warmup = asyncio.create_task(memory.warmup())
    else:
        logger.info("记忆层已关闭")

    async with open_checkpointer() as checkpointer:
        graph = build_graph(
            connector=connector,
            registry=registry,
            hitl_manager=hitl,
            checkpointer=checkpointer,
        )
        logger.info("LangGraph 已编译 (%d 个工具, checkpointer=on)", len(registry.list_all()))
        run_metrics.log_summary()

        service = AgentService(
            config=config,
            db=db,
            graph=graph,
            connector=connector,
            registry=registry,
            hitl=hitl,
            prompt=prompt,
            memory=memory,
            memory_warmup=memory_warmup,
        )
        client = GatewayClient(config.network, service.router)
        service.attach_client(client)
        client.on_connected(service.on_connected)
        try:
            await client.start()
        except KeyboardInterrupt:
            logger.info("收到中断信号，正在退出...")
        finally:
            service.cancel_watchdogs()
            if memory_warmup and not memory_warmup.done():
                memory_warmup.cancel()
            await client.stop()
            shutdown_observability()
            release_pid_lock()
            logger.info("Agent 已停止")


def cli(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    if args.stop:
        sys.exit(0 if stop_running_agent() else 1)
    if args.status:
        pid = agent_status()
        if pid is None:
            print("Agent 未运行")
            sys.exit(1)
        print(f"Agent 运行中 (PID={pid})")
        sys.exit(0)
    asyncio.run(main(args.config_path))


if __name__ == "__main__":
    cli()
