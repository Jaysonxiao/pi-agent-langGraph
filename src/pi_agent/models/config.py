"""M8.1 configuration scaffold: implement only resolve_model_config."""

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urlsplit

from pydantic import SecretStr

Provider = Literal["fake", "compatible"]
ConfigField = Literal[
    "provider",
    "model",
    "base_url",
    "api_key_env",
    "api_key",
    "timeout_seconds",
    "max_attempts",
    "run_timeout_seconds",
]

DEFAULT_API_KEY_ENV = "PI_AGENT_API_KEY"
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_RUN_TIMEOUT_SECONDS = 120.0


class ModelConfigError(ValueError):
    """Expose a field identifier, never the rejected value or SDK exception."""

    def __init__(self, field_name: ConfigField) -> None:
        self.field = field_name
        super().__init__(f"Missing or invalid model configuration: {field_name}.")


@dataclass(frozen=True, slots=True)
class ModelOptions:
    """Explicit options; None means absent, while blank values are invalid."""

    provider: str | None = field(default=None, repr=False)
    model: str | None = field(default=None, repr=False)
    base_url: str | None = field(default=None, repr=False)
    api_key_env: str | None = field(default=None, repr=False)
    timeout_seconds: float | None = None
    max_attempts: int | None = None
    run_timeout_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class ModelConfig:
    """Resolved runtime dependency; do not place this object in graph state.

    This DTO does not validate its constructor arguments. The resolver owns
    validation; public_dict is the only supported diagnostic projection.
    """

    provider: Provider
    model: str | None
    base_url: str | None
    api_key: SecretStr | None = field(repr=False)
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    run_timeout_seconds: float = DEFAULT_RUN_TIMEOUT_SECONDS

    def public_dict(self) -> dict[str, str | float | int | None]:
        """Project operational settings without serializing the secret field."""
        return {
            "provider": self.provider,
            "model": self.model,
            "base_url": self.base_url,
            "timeout_seconds": self.timeout_seconds,
            "max_attempts": self.max_attempts,
            "run_timeout_seconds": self.run_timeout_seconds,
        }


ENV_PROVIDER = "PI_AGENT_PROVIDER"
ENV_MODEL = "PI_AGENT_MODEL"
ENV_BASE_URL = "PI_AGENT_BASE_URL"
ENV_API_KEY_ENV = "PI_AGENT_API_KEY_ENV"
ENV_TIMEOUT_SECONDS = "PI_AGENT_TIMEOUT_SECONDS"
ENV_MAX_ATTEMPTS = "PI_AGENT_MAX_ATTEMPTS"
ENV_RUN_TIMEOUT_SECONDS = "PI_AGENT_RUN_TIMEOUT_SECONDS"
_API_KEY_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def resolve_model_config(options: ModelOptions, environ: Mapping[str, str]) -> ModelConfig:
    """Resolve and validate one run without touching the actual environment."""
    provider = _resolve_provider(options.provider, environ)
    timeout_seconds = _resolve_duration(
        options.timeout_seconds,
        environ,
        ENV_TIMEOUT_SECONDS,
        "timeout_seconds",
        DEFAULT_TIMEOUT_SECONDS,
    )
    max_attempts = _resolve_attempts(options.max_attempts, environ)
    run_timeout_seconds = _resolve_duration(
        options.run_timeout_seconds,
        environ,
        ENV_RUN_TIMEOUT_SECONDS,
        "run_timeout_seconds",
        DEFAULT_RUN_TIMEOUT_SECONDS,
    )

    # fake 不读模型/端点/密钥, 但仍要求三个数值预算合法.
    if provider == "fake":
        return ModelConfig(
            provider="fake",
            model=None,
            base_url=None,
            api_key=None,
            timeout_seconds=timeout_seconds,
            max_attempts=max_attempts,
            run_timeout_seconds=run_timeout_seconds,
        )

    return ModelConfig(
        provider="compatible",
        model=_resolve_model(options.model, environ),
        base_url=_resolve_base_url(options.base_url, environ),
        api_key=_resolve_api_key(options.api_key_env, environ),
        timeout_seconds=timeout_seconds,
        max_attempts=max_attempts,
        run_timeout_seconds=run_timeout_seconds,
    )


def _selected(explicit: object, environ: Mapping[str, str], env_key: str) -> object | None:
    # 显式非 None 优先; 选中后非法不得回退到环境或默认值.
    if explicit is not None:
        return explicit
    if env_key in environ:
        return environ[env_key]
    return None


def _resolve_provider(explicit: str | None, environ: Mapping[str, str]) -> Provider:
    selected = _selected(explicit, environ, ENV_PROVIDER)
    if selected is None:
        return "fake"
    if selected not in ("fake", "compatible"):
        raise ModelConfigError("provider")
    return selected


def _resolve_duration(
    explicit: float | None,
    environ: Mapping[str, str],
    env_key: str,
    field_name: Literal["timeout_seconds", "run_timeout_seconds"],
    default: float,
) -> float:
    selected = _selected(explicit, environ, env_key)
    if selected is None:
        return default
    if isinstance(selected, str):
        try:
            parsed = float(selected)
        except ValueError:
            raise ModelConfigError(field_name) from None
        return _require_positive_finite(parsed, field_name)
    return _require_positive_finite(selected, field_name)


def _require_positive_finite(
    value: object, field_name: Literal["timeout_seconds", "run_timeout_seconds"]
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ModelConfigError(field_name)
    if not math.isfinite(value) or value <= 0:
        raise ModelConfigError(field_name)
    return float(value)


def _resolve_attempts(explicit: int | None, environ: Mapping[str, str]) -> int:
    selected = _selected(explicit, environ, ENV_MAX_ATTEMPTS)
    if selected is None:
        return DEFAULT_MAX_ATTEMPTS
    if isinstance(selected, str):
        try:
            parsed = int(selected)
        except ValueError:
            raise ModelConfigError("max_attempts") from None
        if parsed <= 0:
            raise ModelConfigError("max_attempts")
        return parsed
    if isinstance(selected, bool) or not isinstance(selected, int) or selected <= 0:
        raise ModelConfigError("max_attempts")
    return selected


def _resolve_model(explicit: str | None, environ: Mapping[str, str]) -> str:
    selected = _selected(explicit, environ, ENV_MODEL)
    if not isinstance(selected, str) or not selected.strip():
        raise ModelConfigError("model")
    return selected.strip()


def _resolve_base_url(explicit: str | None, environ: Mapping[str, str]) -> str:
    selected = _selected(explicit, environ, ENV_BASE_URL)
    if not isinstance(selected, str) or not selected:
        raise ModelConfigError("base_url")
    return _require_http_endpoint(selected)


def _require_http_endpoint(raw: str) -> str:
    # 保留调用方给出的路径和末尾斜线, 不拼接 /v1.
    if any(character.isspace() for character in raw):
        raise ModelConfigError("base_url")
    try:
        parts = urlsplit(raw)
        port = parts.port
    except ValueError:
        raise ModelConfigError("base_url") from None
    if parts.scheme not in {"http", "https"}:
        raise ModelConfigError("base_url")
    if not parts.hostname:
        raise ModelConfigError("base_url")
    if parts.username is not None or parts.password is not None:
        raise ModelConfigError("base_url")
    if parts.query or parts.fragment:
        raise ModelConfigError("base_url")
    if port is not None and not 1 <= port <= 65535:
        raise ModelConfigError("base_url")
    return raw


def _resolve_api_key(explicit_env_name: str | None, environ: Mapping[str, str]) -> SecretStr:
    name = _selected(explicit_env_name, environ, ENV_API_KEY_ENV)
    if name is None:
        name = DEFAULT_API_KEY_ENV
    if not isinstance(name, str) or _API_KEY_ENV_NAME.fullmatch(name) is None:
        raise ModelConfigError("api_key_env")
    # 只读选定变量, 缺失或全空白报 api_key, 不回退 PI_AGENT_API_KEY.
    if name not in environ:
        raise ModelConfigError("api_key")
    secret = environ[name]
    if not secret.strip():
        raise ModelConfigError("api_key")
    return SecretStr(secret)
