"""Development SQLite checkpoint lifecycle."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver


class SessionCheckpointError(RuntimeError):
    """Raised when durable checkpoint storage cannot be read safely."""


@contextmanager
def open_sqlite_checkpointer(database_path: Path) -> Iterator[SqliteSaver]:
    """Open an app-owned SQLite checkpointer and always close its connection."""
    path = database_path.resolve(strict=False)
    if path.exists() and not path.is_file():
        raise ValueError(f"Checkpoint path must be a file: {path}")
    if not path.parent.is_dir():
        raise ValueError(f"Checkpoint parent directory does not exist: {path.parent}")

    try:
        # SQL 往往发生在 yield 之后的 get_state/invoke, 必须把调用方也包进同一 try.
        with SqliteSaver.from_conn_string(str(path)) as checkpointer:
            yield checkpointer
    except sqlite3.OperationalError:
        # 锁冲突等可操作错误不是“损坏 checkpoint”, 原样抛出.
        raise
    except sqlite3.DatabaseError as error:
        raise SessionCheckpointError(f"Checkpoint database is unreadable: {path}") from error
