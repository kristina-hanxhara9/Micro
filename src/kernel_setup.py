from __future__ import annotations

from semantic_kernel import Kernel
from semantic_kernel.connectors.ai.open_ai import AzureChatCompletion

from .config import Settings

CHAT_SERVICE_ID = "azure_chat"


def build_kernel(settings: Settings) -> Kernel:
    kernel = Kernel()
    kernel.add_service(
        AzureChatCompletion(
            service_id=CHAT_SERVICE_ID,
            deployment_name=settings.azure_openai_deployment,
            endpoint=settings.azure_openai_endpoint,
            api_key=settings.azure_openai_api_key,
            api_version=settings.azure_openai_api_version,
        )
    )
    return kernel
