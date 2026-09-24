"""Offline acceptance cases for the learner-owned M8.1 resolver."""

import json
import traceback
from dataclasses import replace
from types import MappingProxyType

import pytest
from pydantic import SecretStr

from pi_agent.models.config import ModelConfig, ModelConfigError, ModelOptions, resolve_model_config

SENTINEL = "synthetic-m81-secret-not-a-real-key"


@pytest.fixture
def compatible_env() -> dict[str, str]:
    return {
        "PI_AGENT_PROVIDER": "compatible",
        "PI_AGENT_MODEL": "test-model",
        "PI_AGENT_BASE_URL": "https://provider.example/api/v1/",
        "PI_AGENT_API_KEY": SENTINEL,
    }


def test_default_fake_needs_no_credentials() -> None:
    config = resolve_model_config(ModelOptions(), {})
    assert config.provider == "fake"
    assert config.model is None
    assert config.base_url is None
    assert config.api_key is None
    assert (config.timeout_seconds, config.max_attempts, config.run_timeout_seconds) == (30, 3, 120)


def test_environment_config_preserves_endpoint_and_wraps_key(
    compatible_env: dict[str, str],
) -> None:
    config = resolve_model_config(ModelOptions(), compatible_env)
    assert config.provider == "compatible"
    assert config.model == "test-model"
    assert config.base_url == "https://provider.example/api/v1/"
    assert isinstance(config.api_key, SecretStr)
    assert config.api_key.get_secret_value() == SENTINEL


def test_explicit_values_override_even_invalid_environment_values() -> None:
    env = {
        "PI_AGENT_PROVIDER": "invalid",
        "PI_AGENT_MODEL": "",
        "PI_AGENT_BASE_URL": "bad-url",
        "PI_AGENT_API_KEY_ENV": "",
        "PI_AGENT_TIMEOUT_SECONDS": "bad",
        "PI_AGENT_MAX_ATTEMPTS": "bad",
        "PI_AGENT_RUN_TIMEOUT_SECONDS": "bad",
        "TEST_SERVICE_KEY": SENTINEL,
    }
    config = resolve_model_config(
        ModelOptions(
            provider="compatible",
            model="explicit-model",
            base_url="http://localhost:8080/v1",
            api_key_env="TEST_SERVICE_KEY",
            timeout_seconds=4.5,
            max_attempts=2,
            run_timeout_seconds=20,
        ),
        env,
    )
    assert config.public_dict() == {
        "provider": "compatible",
        "model": "explicit-model",
        "base_url": "http://localhost:8080/v1",
        "timeout_seconds": 4.5,
        "max_attempts": 2,
        "run_timeout_seconds": 20,
    }
    assert config.api_key is not None
    assert config.api_key.get_secret_value() == SENTINEL


def test_environment_budgets_are_parsed(compatible_env: dict[str, str]) -> None:
    compatible_env.update(
        PI_AGENT_TIMEOUT_SECONDS="2.5",
        PI_AGENT_MAX_ATTEMPTS="4",
        PI_AGENT_RUN_TIMEOUT_SECONDS="18",
    )
    config = resolve_model_config(ModelOptions(), compatible_env)
    assert (config.timeout_seconds, config.max_attempts, config.run_timeout_seconds) == (2.5, 4, 18)


def test_fake_ignores_provider_specific_settings(compatible_env: dict[str, str]) -> None:
    config = resolve_model_config(
        ModelOptions(provider="fake", model="", base_url="invalid", api_key_env=""),
        compatible_env,
    )
    assert config.provider == "fake"
    assert config.model is None
    assert config.base_url is None
    assert config.api_key is None


@pytest.mark.parametrize("provider", ["", "  ", "unsupported"])
def test_invalid_explicit_provider_does_not_fall_back(provider: str) -> None:
    with pytest.raises(ModelConfigError) as caught:
        resolve_model_config(ModelOptions(provider=provider), {"PI_AGENT_PROVIDER": "fake"})
    assert caught.value.field == "provider"


@pytest.mark.parametrize(
    ("variable", "field_name"),
    [
        ("PI_AGENT_MODEL", "model"),
        ("PI_AGENT_BASE_URL", "base_url"),
        ("PI_AGENT_API_KEY", "api_key"),
    ],
)
@pytest.mark.parametrize("value", [None, "", "   "])
def test_compatible_requires_nonblank_fields(
    compatible_env: dict[str, str], variable: str, field_name: str, value: str | None
) -> None:
    if value is None:
        compatible_env.pop(variable)
    else:
        compatible_env[variable] = value
    with pytest.raises(ModelConfigError) as caught:
        resolve_model_config(ModelOptions(), compatible_env)
    assert caught.value.field == field_name


def test_explicit_blank_model_does_not_use_environment(compatible_env: dict[str, str]) -> None:
    with pytest.raises(ModelConfigError) as caught:
        resolve_model_config(ModelOptions(model=""), compatible_env)
    assert caught.value.field == "model"


@pytest.mark.parametrize(
    "url",
    [
        "ftp://provider.example/v1",
        "provider.example/v1",
        "https:///v1",
        f"https://user:{SENTINEL}@provider.example/v1",
        f"https://provider.example/v1?key={SENTINEL}",
        f"https://provider.example/v1#{SENTINEL}",
        "https://provider.example:99999/v1",
        "https://provider.example:invalid/v1",
        "https://[broken/v1",
        "https://bad host/v1",
        "https://provider.example/\nv1",
    ],
)
def test_invalid_endpoint_is_rejected_without_echoing_input(
    compatible_env: dict[str, str], url: str
) -> None:
    with pytest.raises(ModelConfigError) as caught:
        resolve_model_config(ModelOptions(base_url=url), compatible_env)
    assert caught.value.field == "base_url"
    assert url not in str(caught.value)
    assert SENTINEL not in "".join(traceback.format_exception(caught.value))


@pytest.mark.parametrize(
    ("variable", "field_name", "value"),
    [
        ("PI_AGENT_TIMEOUT_SECONDS", "timeout_seconds", "0"),
        ("PI_AGENT_TIMEOUT_SECONDS", "timeout_seconds", "-1"),
        ("PI_AGENT_TIMEOUT_SECONDS", "timeout_seconds", "nan"),
        ("PI_AGENT_TIMEOUT_SECONDS", "timeout_seconds", "inf"),
        ("PI_AGENT_TIMEOUT_SECONDS", "timeout_seconds", SENTINEL),
        ("PI_AGENT_MAX_ATTEMPTS", "max_attempts", "0"),
        ("PI_AGENT_MAX_ATTEMPTS", "max_attempts", "-2"),
        ("PI_AGENT_MAX_ATTEMPTS", "max_attempts", "1.5"),
        ("PI_AGENT_MAX_ATTEMPTS", "max_attempts", ""),
        ("PI_AGENT_RUN_TIMEOUT_SECONDS", "run_timeout_seconds", "0"),
        ("PI_AGENT_RUN_TIMEOUT_SECONDS", "run_timeout_seconds", "-2"),
        ("PI_AGENT_RUN_TIMEOUT_SECONDS", "run_timeout_seconds", "nan"),
        ("PI_AGENT_RUN_TIMEOUT_SECONDS", "run_timeout_seconds", "inf"),
    ],
)
def test_invalid_environment_budgets_fail_even_for_fake(
    variable: str, field_name: str, value: str
) -> None:
    with pytest.raises(ModelConfigError) as caught:
        resolve_model_config(ModelOptions(), {variable: value})
    assert caught.value.field == field_name
    assert SENTINEL not in "".join(traceback.format_exception(caught.value))


@pytest.mark.parametrize(
    ("options", "field_name"),
    [
        (ModelOptions(timeout_seconds=0), "timeout_seconds"),
        (ModelOptions(timeout_seconds=float("nan")), "timeout_seconds"),
        (ModelOptions(timeout_seconds=True), "timeout_seconds"),
        (ModelOptions(max_attempts=0), "max_attempts"),
        (ModelOptions(max_attempts=True), "max_attempts"),
        (ModelOptions(run_timeout_seconds=float("inf")), "run_timeout_seconds"),
        (ModelOptions(run_timeout_seconds=True), "run_timeout_seconds"),
    ],
)
def test_invalid_explicit_budgets_do_not_fall_back(options: ModelOptions, field_name: str) -> None:
    with pytest.raises(ModelConfigError) as caught:
        resolve_model_config(
            options,
            {
                "PI_AGENT_TIMEOUT_SECONDS": "30",
                "PI_AGENT_MAX_ATTEMPTS": "3",
                "PI_AGENT_RUN_TIMEOUT_SECONDS": "120",
            },
        )
    assert caught.value.field == field_name


def test_selected_key_name_does_not_fall_back(compatible_env: dict[str, str]) -> None:
    compatible_env["PI_AGENT_API_KEY_ENV"] = "OTHER_KEY"
    with pytest.raises(ModelConfigError) as caught:
        resolve_model_config(ModelOptions(), compatible_env)
    assert caught.value.field == "api_key"
    compatible_env["OTHER_KEY"] = "other-synthetic-key"
    config = resolve_model_config(ModelOptions(), compatible_env)
    assert config.api_key is not None
    assert config.api_key.get_secret_value() == "other-synthetic-key"


@pytest.mark.parametrize("name", ["", " ", "BAD-NAME", "1BAD"])
def test_key_variable_name_is_validated(compatible_env: dict[str, str], name: str) -> None:
    with pytest.raises(ModelConfigError) as caught:
        resolve_model_config(ModelOptions(api_key_env=name), compatible_env)
    assert caught.value.field == "api_key_env"


def test_resolver_uses_only_injected_environment_and_does_not_mutate_inputs(
    compatible_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PI_AGENT_PROVIDER", "unsupported-global-provider")
    monkeypatch.setenv("PI_AGENT_API_KEY", "different-global-key")
    before = compatible_env.copy()
    options = ModelOptions(model="explicit-model")
    before_options = replace(options)
    config = resolve_model_config(options, MappingProxyType(compatible_env))
    assert compatible_env == before
    assert options == before_options
    assert config.api_key is not None
    assert config.api_key.get_secret_value() == SENTINEL
    assert resolve_model_config(ModelOptions(), {}).provider == "fake"


def test_resolved_configuration_has_safe_public_output(compatible_env: dict[str, str]) -> None:
    config = resolve_model_config(ModelOptions(), compatible_env)
    assert SENTINEL not in repr(config)
    assert SENTINEL not in str(config.api_key)
    public = config.public_dict()
    assert "api_key" not in public
    assert SENTINEL not in json.dumps(public)


def test_scaffold_public_projection_excludes_credentials() -> None:
    config = ModelConfig(
        provider="compatible",
        model="test-model",
        base_url="https://provider.example/v1",
        api_key=SecretStr(SENTINEL),
    )
    assert "api_key" not in config.public_dict()
    assert SENTINEL not in repr(config)
    assert SENTINEL not in json.dumps(config.public_dict())
