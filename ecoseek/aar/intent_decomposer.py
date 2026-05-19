"""
AAR-01: Intent Decomposer

Breaks a user research query into 2–5 focused sub-questions using an
LLM (EcoCoder or DeepSeek BYOK).  Each sub-question carries a search
strategy hint and a priority so the retrieval router knows where to look.
"""

import json
import os
import time
from dataclasses import dataclass, field
from typing import List, Optional

from pydantic import BaseModel, validator


# ---------- Pydantic schema for validated output ----------

class SubQuestion(BaseModel):
    id: int
    question: str
    search_strategy: str  # literature | species_db | sdm | general_web
    priority: str  # high | medium | low

    @validator("search_strategy")
    def _valid_strategy(cls, v: str) -> str:
        allowed = {"literature", "species_db", "sdm", "general_web"}
        if v not in allowed:
            raise ValueError(f"search_strategy must be one of {allowed}")
        return v

    @validator("priority")
    def _valid_priority(cls, v: str) -> str:
        allowed = {"high", "medium", "low"}
        if v not in allowed:
            raise ValueError(f"priority must be one of {allowed}")
        return v


class DecompositionResult(BaseModel):
    original_query: str
    sub_questions: List[SubQuestion]


# ---------- Prompt loading ----------

_PROMPT_DIR = os.path.join(os.path.dirname(__file__), "..", "prompts")


def _load_prompt() -> str:
    path = os.path.join(_PROMPT_DIR, "intent_decompose.md")
    with open(path, "r") as f:
        return f.read()


# ---------- Decomposer ----------

def decompose_intent(
    query: str,
    llm_call,
    max_retries: int = 2,
) -> DecompositionResult:
    """
    Decompose *query* into sub-questions.

    Parameters
    ----------
    query : str
        The user's raw research question.
    llm_call : callable(prompt: str) -> str
        A function that sends a prompt to the configured LLM and returns the
        raw text response.  This keeps the decomposer model-agnostic.
    max_retries : int
        How many times to retry on schema-validation failure.

    Returns
    -------
    DecompositionResult
        Validated Pydantic model with the original query and sub-questions.
    """
    system_prompt = _load_prompt()
    full_prompt = f"{system_prompt}\n\n**User query:** \"{query}\""

    last_error: Optional[str] = None
    for attempt in range(1, max_retries + 2):
        if last_error:
            full_prompt += (
                f"\n\nYour previous response failed JSON validation: {last_error}. "
                "Please respond with ONLY the JSON object, no markdown fences."
            )

        raw = llm_call(full_prompt)
        json_str = _extract_json(raw)

        try:
            result = DecompositionResult.parse_raw(json_str)
            if not result.sub_questions:
                last_error = "sub_questions list was empty"
                continue
            return result
        except Exception as exc:
            last_error = str(exc)

    # Fallback: return the original query as a single sub-question
    return DecompositionResult(
        original_query=query,
        sub_questions=[
            SubQuestion(
                id=1,
                question=query,
                search_strategy="literature",
                priority="high",
            )
        ],
    )


def _extract_json(text: str) -> str:
    """Best-effort extraction of a JSON object from LLM output."""
    # Try to find JSON between code fences
    import re

    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if fence_match:
        return fence_match.group(1).strip()

    # Try to find raw JSON object
    brace_start = text.find("{")
    if brace_start == -1:
        return text.strip()
    brace_end = text.rfind("}")
    if brace_end == -1:
        return text.strip()
    return text[brace_start : brace_end + 1]
