"""LangGraph SQLite checkpointer 工厂（async 生产路径用 AsyncSqliteSaver）"""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver


def checkpointer_db_path(db_path: str | None = None) -> str:
    if db_path is None:
        db_path = os.path.expanduser("~/.lingji/langgraph_checkpoints.db")
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


@asynccontextmanager
async def open_checkpointer(
    db_path: str | None = None,
) -> AsyncIterator[AsyncSqliteSaver]:
    """长驻 Agent 使用的 async checkpointer（配合 graph.ainvoke / Command(resume)）。"""
    conn_string = checkpointer_db_path(db_path)
    async with AsyncSqliteSaver.from_conn_string(conn_string) as saver:
        await saver.setup()
        yield saver
