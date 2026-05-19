"""
AAR-08: Nemotron backend provider

OpenAI-compatible wrapper for Nemotron-70B (or any vLLM-served model) on
KU HPC.  Falls back to DeepSeek BYOK, then EcoCoder local.

Selection via ``ECOSEEK_JUDGE_MODEL`` env var:
  - ``nemotron``   → Nemotron-70B on KU HPC vLLM
  - ``deepseek-r1``→ DeepSeek R1 via BYOK API
  - ``deepseek``   → DeepSeek default via BYOK API
  - ``ecocoder``   → EcoCoder local endpoint
  - ``auto``       → try nemotron → deepseek-r1 → deepseek → ecocoder
"""

import json
import logging
import os
from typing import Optional

import requests

logger = logging.getLogger("ecoseek.providers")

# ---------- Config ----------

_TIMEOUT = int(os.getenv("ECOSEEK_JUDGE_TIMEOUT", "30"))


def _nemotron_config() -> dict:
    return {
        "base_url": os.getenv("NEMOTRON_BASE_URL", ""),
        "api_key": os.getenv("NEMOTRON_API_KEY", ""),
        "model": os.getenv("NEMOTRON_MODEL", "nvidia/nemotron-70b"),
    }


def _deepseek_config() -> dict:
    return {
        "base_url": os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        "api_key": os.getenv("DEEPSEEK_API_KEY", ""),
    }


def _ecocoder_config() -> dict:
    return {
        "base_url": os.getenv("ECOCODER_BASE_URL", "http://localhost:8100"),
        "model": os.getenv("ECOCODER_MODEL", "ecocoder"),
    }


# ---------- Generic OpenAI-compatible call ----------

def _openai_chat(
    base_url: str,
    api_key: str,
    model: str,
    prompt: str,
    temperature: float = 0.3,
    max_tokens: int = 1024,
) -> str:
    """Call an OpenAI-compatible chat completions endpoint."""
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    resp = requests.post(
        f"{base_url.rstrip('/')}/v1/chat/completions",
        headers=headers,
        json=payload,
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]


# ---------- Provider functions ----------

def call_nemotron(prompt: str) -> str:
    cfg = _nemotron_config()
    if not cfg["base_url"]:
        raise ConnectionError("NEMOTRON_BASE_URL not set")
    return _openai_chat(cfg["base_url"], cfg["api_key"], cfg["model"], prompt)


def call_deepseek_r1(prompt: str) -> str:
    cfg = _deepseek_config()
    if not cfg["api_key"]:
        raise ConnectionError("DEEPSEEK_API_KEY not set")
    return _openai_chat(
        cfg["base_url"], cfg["api_key"], "deepseek-reasoner", prompt,
    )


def call_deepseek(prompt: str) -> str:
    cfg = _deepseek_config()
    if not cfg["api_key"]:
        raise ConnectionError("DEEPSEEK_API_KEY not set")
    return _openai_chat(
        cfg["base_url"], cfg["api_key"], "deepseek-chat", prompt,
    )


def call_ecocoder(prompt: str) -> str:
    cfg = _ecocoder_config()
    return _openai_chat(cfg["base_url"], "", cfg["model"], prompt)


# ---------- Auto-fallback ----------

_PROVIDERS = {
    "nemotron": call_nemotron,
    "deepseek-r1": call_deepseek_r1,
    "deepseek": call_deepseek,
    "ecocoder": call_ecocoder,
}

_AUTO_ORDER = ["nemotron", "deepseek-r1", "deepseek", "ecocoder"]


def get_judge_call():
    """
    Return the judge LLM callable based on ``ECOSEEK_JUDGE_MODEL``.

    Returns a ``callable(prompt: str) -> str``.
    """
    model = os.getenv("ECOSEEK_JUDGE_MODEL", "auto").lower()

    if model in _PROVIDERS:
        return _PROVIDERS[model]

    # auto mode: try each in order
    def _auto_call(prompt: str) -> str:
        last_exc: Optional[Exception] = None
        for name in _AUTO_ORDER:
            try:
                return _PROVIDERS[name](prompt)
            except Exception as exc:
                logger.debug("Judge provider '%s' failed: %s", name, exc)
                last_exc = exc
        raise ConnectionError(
            f"All judge providers failed. Last error: {last_exc}"
        )

    return _auto_call
