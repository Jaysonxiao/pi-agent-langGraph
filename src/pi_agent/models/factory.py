"""M8.2 model factory scaffold."""

from collections.abc import Callable

from pi_agent.models.adapter import CompatibleChatModel, ProviderClient
from pi_agent.models.base import ChatModel
from pi_agent.models.config import ModelConfig
from pi_agent.models.errors import ModelFactoryError
from pi_agent.models.fake import FakeChatModel

ClientFactory = Callable[[ModelConfig], ProviderClient]


def build_model(
    config: ModelConfig,
    *,
    client_factory: ClientFactory | None = None,
) -> ChatModel:
    """Construct a project ChatModel without reading env or creating network clients implicitly."""
    # fake 不触网、不调 factory; 即使传入 factory 也必须忽略.
    if config.provider == "fake":
        return FakeChatModel()

    if client_factory is None:
        raise ModelFactoryError()

    try:
        # 把已解析的 ModelConfig 原样交给注入工厂, 本层不读环境、不改字段.
        client = client_factory(config)
    except Exception:
        # 客户端构造异常可能含密钥或 URL, 切断异常链并换成固定正文.
        raise ModelFactoryError() from None

    return CompatibleChatModel(client, config)
