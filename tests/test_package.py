"""Package-boundary tests for the M1 foundation milestone."""

from importlib.metadata import version

import pi_agent


def test_package_exports_distribution_version() -> None:
    """The public package version should come from installed distribution metadata."""
    assert getattr(pi_agent, "__version__", None) == version("pi-agent-langgraph")
