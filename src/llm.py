from __future__ import annotations

from langchain_core.runnables import Runnable

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
):
    """Construye el chat model base (sin retry). El retry se aplica arriba con
    ``resilient()`` porque debe envolver el runnable ya final (con tools o con
    structured output)."""
    if provider == "ollama":
        from langchain_ollama import ChatOllama
        return ChatOllama(
            base_url=base_url,
            model=model,
            temperature=temperature,
            num_ctx=16384,
            client_kwargs={"timeout": timeout},
        )
    if provider in CLOUD_PROVIDERS:
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            base_url=base_url or PROVIDER_DEFAULT_URLS[provider],
            model=model,
            api_key=api_key or "sk-no-key",
            temperature=temperature,
            timeout=timeout,
            max_retries=0,          # el retry lo maneja resilient()
        )
    raise ValueError(f"Provider no soportado: '{provider}'. Opciones: {SUPPORTED_PROVIDERS}")


def resilient(runnable: Runnable, retries: int) -> Runnable:
    """Envuelve un runnable con reintentos + backoff exponencial con jitter.

    ``retries`` es el número de reintentos (0 = sin reintentos). Se aplica al
    final, sobre el runnable ya construido (``bind_tools`` / ``with_structured_output``
    no existen en el objeto que devuelve ``with_retry``)."""
    if retries <= 0:
        return runnable
    return runnable.with_retry(
        stop_after_attempt=retries + 1,
        wait_exponential_jitter=True,
    )
