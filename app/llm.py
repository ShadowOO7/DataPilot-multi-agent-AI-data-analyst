import os
from dotenv import load_dotenv

load_dotenv()

PROVIDER = os.getenv("LLM_PROVIDER", "ollama")
MODEL_NAME = os.getenv("LLM_MODEL", "llama3.2:3b")


def get_llm(temperature: float = 0.1):
    if PROVIDER == "ollama":
        from langchain_ollama import ChatOllama
        llm = ChatOllama(model=MODEL_NAME, temperature=temperature)
    elif PROVIDER == "openai":
        from langchain_openai import ChatOpenAI
        llm = ChatOpenAI(model=MODEL_NAME, temperature=temperature)
    else:
        raise ValueError(f"Unknown LLM_PROVIDER: {PROVIDER}")

    # Single wiring point for observability — every agent calls get_llm(),
    # so attaching the Langfuse callback here (if configured) covers every
    # LLM call project-wide without touching each agent file. No-op if
    # Langfuse isn't configured (see app/observability.py).
    from app.observability import get_langfuse_handler
    handler = get_langfuse_handler()
    if handler:
        llm = llm.with_config(callbacks=[handler])

    return llm
