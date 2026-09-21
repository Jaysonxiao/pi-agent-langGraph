"""Scoped SIGINT handling for cooperative CLI cancellation."""

import signal
from collections.abc import Iterator
from contextlib import contextmanager
from types import FrameType

from pi_agent.cli.cancel import CancellationToken


@contextmanager
def sigint_cancels(token: CancellationToken) -> Iterator[None]:
    """Temporarily map Ctrl+C to a cancellation token and restore prior state."""

    # 保存进程当前 SIGINT handler, 离开时必须原样装回去.
    previous = signal.getsignal(signal.SIGINT)

    def handle_sigint(_signum: int, _frame: FrameType | None) -> None:
        # handler 只翻 token; 不写 stdout、不关 graph, 也不抛业务异常.
        token.cancel()

    signal.signal(signal.SIGINT, handle_sigint)
    try:
        yield
    finally:
        # 正常结束或 body 抛错都要恢复, 避免永久替换全局 handler.
        signal.signal(signal.SIGINT, previous)
