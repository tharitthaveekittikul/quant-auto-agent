import os

from langchain_core.language_models import BaseChatModel


def get_llm(env_var: str, default: str = "claude-opus-4-6") -> BaseChatModel:
    """
    Resolve a model name from an environment variable and return a ChatModel.

    Provider is detected from the model name prefix:
      claude-*          → ChatAnthropic
      gpt-* / o1-* / o3-* / o4-*  → ChatOpenAI
      gemini-*          → ChatGoogleGenerativeAI
    """
    model_name = os.getenv(env_var, default)

    if model_name.startswith("claude-"):
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(model=model_name, temperature=0.0)  # type: ignore[call-arg]

    if model_name.startswith(("gpt-", "o1-", "o3-", "o4-")):
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model=model_name, temperature=0.0)

    if model_name.startswith("gemini-"):
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(model=model_name, temperature=0.0)

    raise ValueError(
        f"Unknown model provider for '{model_name}'. "
        "Expected prefix: claude-, gpt-, o1-, o3-, o4-, or gemini-."
    )
