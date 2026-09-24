"""Async SQLite checkpoint lifecycle for the M8.8 session runner."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver


@asynccontextmanager
async def open_async_sqlite_checkpointer(
    database_path: Path,
) -> AsyncIterator[AsyncSqliteSaver]:
    """Yield one app-owned async SQLite saver and close it on every exit path."""
    path = database_path.resolve(strict=False)
    # 打开前拒绝目录或缺失父目录, 与同步 saver 同一路径边界.
    if path.exists() and not path.is_file():
        raise ValueError(f"Checkpoint path must be a file: {path}")
    if not path.parent.is_dir():
        raise ValueError(f"Checkpoint parent directory does not exist: {path.parent}")

    # yield 必须在 from_conn_string 内部, 图调用、异常和取消都会关闭连接.
    async with AsyncSqliteSaver.from_conn_string(str(path)) as checkpointer:
        yield checkpointer
