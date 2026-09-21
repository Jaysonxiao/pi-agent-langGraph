"""Acceptance tests for scoped SIGINT cancellation handling."""

import signal
from collections.abc import Callable
from typing import cast

import pytest

from pi_agent.cli import CancellationToken, sigint_cancels


def test_sigint_cancels_token_and_restores_previous_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = CancellationToken()
    previous = object()
    installed: list[object] = []

    monkeypatch.setattr(signal, "getsignal", lambda signum: previous)

    def fake_signal(signum: int, handler: object) -> object:
        installed.append(handler)
        return previous

    monkeypatch.setattr(signal, "signal", fake_signal)

    with sigint_cancels(token):
        handler = cast(Callable[[int, object], None], installed[0])
        handler(signal.SIGINT, None)
        assert token.cancelled

    assert installed[-1] is previous


def test_sigint_handler_is_restored_when_body_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    previous = object()
    installed: list[object] = []

    monkeypatch.setattr(signal, "getsignal", lambda signum: previous)

    def fake_signal(signum: int, handler: object) -> object:
        installed.append(handler)
        return previous

    monkeypatch.setattr(signal, "signal", fake_signal)

    with pytest.raises(RuntimeError, match="body failed"), sigint_cancels(CancellationToken()):
        raise RuntimeError("body failed")

    assert installed[-1] is previous
