"""Explicit iterator teardown that does not start unstarted generators."""


def close_iterator(iterator: object) -> None:
    """Call ``close()`` when present; never ``next()`` an unstarted producer."""

    close = getattr(iterator, "close", None)
    if callable(close):
        close()
