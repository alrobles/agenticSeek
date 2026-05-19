"""
AAR-03: Quality Assessor (judge prompt)

Evaluates retrieved evidence against domain-specific scientific criteria.
Output is JSON-validated via Pydantic — no free-text parsing.

The verdict (SUFFICIENT / INSUFFICIENT / CONTRADICTORY) feeds the
deterministic Decision Gate (AAR-04).
"""

import json
import os
import re
from typing import Callable, Optional

from pydantic import BaseModel, validator

from ecoseek.observability.phoenix_setup import get_tracer


# ---------- Pydantic schema ----------

class AssessmentScores(BaseModel):
    relevance: float
    authority: float
    completeness: float

    @validator("relevance", "authority", "completeness")
    def _clamp(cls, v: float) -> float:
        return max(0.0, min(1.0, v))


class AssessmentResult(BaseModel):
    sub_question: str
    verdict: str  # SUFFICIENT | INSUFFICIENT | CONTRADICTORY
    scores: AssessmentScores
    overall_score: float
    reason: str
    source_type: str  # peer_reviewed | database | preprint | institutional | unverified | mixed

    @validator("verdict")
    def _valid_verdict(cls, v: str) -> str:
        allowed = {"SUFFICIENT", "INSUFFICIENT", "CONTRADICTORY"}
        if v not in allowed:
            raise ValueError(f"verdict must be one of {allowed}")
        return v

    def jsonify(self) -> dict:
        return {
            "sub_question": self.sub_question,
            "verdict": self.verdict,
            "scores": {
                "relevance": self.scores.relevance,
                "authority": self.scores.authority,
                "completeness": self.scores.completeness,
            },
            "overall_score": round(self.overall_score, 3),
            "reason": self.reason,
            "source_type": self.source_type,
        }


# ---------- Prompt loading ----------

_PROMPT_DIR = os.path.join(os.path.dirname(__file__), "..", "prompts")


def _load_prompt() -> str:
    path = os.path.join(_PROMPT_DIR, "quality_assess.md")
    with open(path, "r") as f:
        return f.read()


# ---------- Assessor ----------

def assess_quality(
    sub_question: str,
    evidence: str,
    llm_call: Callable[[str], str],
    query_id: str = "",
    max_retries: int = 2,
) -> AssessmentResult:
    """
    Evaluate *evidence* for *sub_question* using a judge LLM call.

    Parameters
    ----------
    sub_question : str
        The sub-question the evidence is supposed to answer.
    evidence : str
        Raw text retrieved for this sub-question.
    llm_call : callable(prompt: str) -> str
        Model-agnostic LLM function.
    query_id : str
        Root query UUID for Phoenix tracing.
    max_retries : int
        Schema validation retries.

    Returns
    -------
    AssessmentResult
        Validated Pydantic model.
    """
    tracer = get_tracer()
    span = tracer.start_span(
        name="aar.assess",
        attributes={"ecoseek_query_id": query_id, "sub_question": sub_question[:200]},
    )

    system_prompt = _load_prompt()
    full_prompt = (
        f"{system_prompt}\n\n"
        f"**Sub-question:** \"{sub_question}\"\n\n"
        f"**Retrieved evidence:**\n{evidence[:3000]}"
    )

    last_error: Optional[str] = None
    result: Optional[AssessmentResult] = None

    try:
        for attempt in range(1, max_retries + 2):
            if last_error:
                full_prompt += (
                    f"\n\nPrevious response failed validation: {last_error}. "
                    "Respond with ONLY the JSON object."
                )

            raw = llm_call(full_prompt)
            json_str = _extract_json(raw)

            try:
                result = AssessmentResult.parse_raw(json_str)
                return result
            except Exception as exc:
                last_error = str(exc)

        # Fallback: return INSUFFICIENT with zero scores
        result = AssessmentResult(
            sub_question=sub_question,
            verdict="INSUFFICIENT",
            scores=AssessmentScores(relevance=0.0, authority=0.0, completeness=0.0),
            overall_score=0.0,
            reason=f"Failed to parse judge output after {max_retries + 1} attempts: {last_error}",
            source_type="unverified",
        )
        return result
    finally:
        if span is not None:
            try:
                span.set_attribute("assessment.verdict", result.verdict if result else "error")
                span.set_attribute(
                    "assessment.overall_score",
                    result.overall_score if result else 0.0,
                )
                span.end()
            except Exception:
                pass


def _extract_json(text: str) -> str:
    """Best-effort extraction of a JSON object from LLM output."""
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if fence_match:
        return fence_match.group(1).strip()
    brace_start = text.find("{")
    if brace_start == -1:
        return text.strip()
    brace_end = text.rfind("}")
    if brace_end == -1:
        return text.strip()
    return text[brace_start : brace_end + 1]
