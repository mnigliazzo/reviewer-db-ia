from __future__ import annotations

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

SUPPORTED_PROVIDERS = ("ollama", "openai", "openrouter", "groq")
CLOUD_PROVIDERS = ("openai", "openrouter", "groq")

PROVIDER_DEFAULT_URLS = {
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "groq": "https://api.groq.com/openai/v1",
}


def build_model(
    provider: str,
    base_url: str,
    model: str,
    api_key: str | None = None,
    *,
    temperature: float = 0.0,
    timeout: float = 120.0,
    retries: int = 2,
) -> BaseChatModel:
    """Chat model vía ``init_chat_model`` (forma recomendada en LangChain v1).

    El retry con backoff lo hace el propio modelo (``max_retries``), sin envolver
    nada por fuera. ``ChatOllama`` no tiene retry nativo — para ollama local, que
    apunta a un endpoint en la misma máquina, no hace falta.
    """
    kwargs: dict = {"temperature": temperature, "max_retries": retries}
    if provider == "ollama":
        # 32k: la fase 2 (with_structured_output) recibe toda la conversación de la
        # fase 1 (prompt + skills cargadas + review en prosa); con 16k el JSON se
        # truncaba y fallaba la validación.
        kwargs.update(model_provider="ollama", base_url=base_url, num_ctx=32768,
                      client_kwargs={"timeout": timeout})
    else:  # openai / openrouter / groq -> misma ruta ChatOpenAI
        kwargs.update(
            model_provider="openai",
            base_url=base_url or PROVIDER_DEFAULT_URLS[provider],
            # ChatOpenAI exige api_key; los endpoints locales OpenAI-compatibles no
            # la piden pero igual hay que pasar algo.
            api_key=api_key or "sk-no-key",
            timeout=timeout,
        )
    return init_chat_model(model, **kwargs)
