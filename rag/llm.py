"""LLM client for the cockpit copilot.

xAI Grok via the OpenAI-compatible LangChain client. The copilot degrades
gracefully without a key — the orchestrator falls back to deterministic data
lookups.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

GROK_MODEL = os.environ.get("GROK_MODEL", "grok-4-1-fast-reasoning")
_XAI_KEY = os.environ.get("XAI_API_KEY", "")
_XAI_BASE = os.environ.get("XAI_BASE_URL", "https://api.x.ai/v1")

_llm = None


def get_llm():
    """Lazily build a Grok chat client (OpenAI-compatible)."""
    global _llm
    if _llm is None:
        from langchain_openai import ChatOpenAI
        _llm = ChatOpenAI(
            model=GROK_MODEL, api_key=_XAI_KEY, base_url=_XAI_BASE,
            temperature=0.1, timeout=120,
        )
    return _llm


def ai_available() -> bool:
    return bool(_XAI_KEY)
