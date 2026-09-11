import os
from dotenv import load_dotenv

load_dotenv()

PROVIDER = os.getenv("LLM_PROVIDER", "ollama")
MODEL_NAME = os.getenv("LLM_MODEL", "llama3.2:3b")


def get_llm(temperature: float = 0.1):
    if PROVIDER == "ollama":
        from langchain_ollama import ChatOllama
        return ChatOllama(model=MODEL_NAME, temperature=temperature)
    elif PROVIDER == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=MODEL_NAME, temperature=temperature)
    else:
        raise ValueError(f"Unknown LLM_PROVIDER: {PROVIDER}")
