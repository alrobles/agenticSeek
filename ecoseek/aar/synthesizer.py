"""
AAR-05: Synthesis + Citation Anchoring

Takes a list of ``RetrievalResult`` objects (all SUFFICIENT or max cycles
reached) and produces a structured answer with inline citations linked to
Phoenix span IDs.
"""

import json
import os
import re
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from pydantic import BaseModel

from ecoseek.aar.retrieval_router import RetrievalResult
from ecoseek.aar.quality_assessor import AssessmentResult
from ecoseek.observability.phoenix_setup import get_tracer


# ---------- Pydantic output schema ----------

class Citation(BaseModel):
    index: int
    source_text: str
    source_type: str  # peer_reviewed | database | preprint | institutional | unverified
    span_id: str

    def jsonify(self) -> dict:
        return {
            "index": self.index,
            "source_text": self.source_text[:300],
            "source_type": self.source_type,
            "span_id": self.span_id,
        }


class SynthesisResult(BaseModel):
    answer: str
    citations: List[Citation]
    confidence: float
    trace_url: str
    query_id: str

    def jsonify(self) -> dict:
        return {
            "answer": self.answer,
            "citations": [c.jsonify() for c in self.citations],
            "confidence": round(self.confidence, 3),
            "trace_url": self.trace_url,
            "query_id": self.query_id,
        }


# ---------- Prompt ----------

_SYNTHESIS_PROMPT = """You are a scientific synthesis assistant for EcoSeek.

Given a set of retrieved evidence blocks (each with a citation index), write a clear,
well-structured answer to the original research query. Use inline citations in the
format [1], [2], etc. to reference each evidence block.

Rules:
1. Every factual claim MUST have at least one citation.
2. If evidence is contradictory, present both views and note the disagreement.
3. End with a confidence assessment: HIGH (strong evidence, peer-reviewed), MEDIUM (partial evidence), LOW (weak/incomplete evidence).
4. Be concise but thorough. Target 200-400 words.

Respond with a JSON object:
```json
{
  "answer": "<your synthesized answer with [1], [2] citations>",
  "confidence_label": "HIGH|MEDIUM|LOW",
  "confidence_score": 0.0
}
```
"""


# ---------- Synthesiser ----------

def synthesize(
    original_query: str,
    retrieval_results: List[RetrievalResult],
    assessments: List[AssessmentResult],
    llm_call: Callable[[str], str],
    query_id: str = "",
    phoenix_base_url: str = "",
) -> SynthesisResult:
    """
    Produce a cited synthesis from retrieval results.

    Parameters
    ----------
    original_query : str
        The user's original research query.
    retrieval_results : list[RetrievalResult]
        All evidence blocks collected during the AAR loop.
    assessments : list[AssessmentResult]
        Quality assessments paired with retrieval results.
    llm_call : callable(prompt: str) -> str
        Model-agnostic LLM function.
    query_id : str
        Root query UUID.
    phoenix_base_url : str
        Base URL for Phoenix trace links.
    """
    tracer = get_tracer()
    span = tracer.start_span(
        name="aar.synthesize",
        attributes={"ecoseek_query_id": query_id},
    )

    try:
        # Build evidence block text
        evidence_blocks: List[str] = []
        citations: List[Citation] = []
        for i, (rr, ar) in enumerate(zip(retrieval_results, assessments), start=1):
            evidence_blocks.append(
                f"[{i}] (source_type: {ar.source_type}, verdict: {ar.verdict}, "
                f"score: {ar.overall_score:.2f})\n{rr.raw_result[:1000]}"
            )
            citations.append(Citation(
                index=i,
                source_text=rr.raw_result[:300],
                source_type=ar.source_type,
                span_id=rr.span_id,
            ))

        evidence_text = "\n\n---\n\n".join(evidence_blocks)
        full_prompt = (
            f"{_SYNTHESIS_PROMPT}\n\n"
            f"**Original query:** \"{original_query}\"\n\n"
            f"**Evidence blocks:**\n\n{evidence_text}"
        )

        raw = llm_call(full_prompt)
        parsed = _parse_synthesis(raw)

        trace_url = ""
        if phoenix_base_url and query_id:
            trace_url = f"{phoenix_base_url}/traces?query_id={query_id}"

        confidence = parsed.get("confidence_score", 0.0)
        if isinstance(confidence, str):
            try:
                confidence = float(confidence)
            except ValueError:
                confidence = 0.5

        result = SynthesisResult(
            answer=parsed.get("answer", raw),
            citations=citations,
            confidence=confidence,
            trace_url=trace_url,
            query_id=query_id,
        )
        return result
    finally:
        if span is not None:
            try:
                span.end()
            except Exception:
                pass


def _parse_synthesis(text: str) -> dict:
    """Extract JSON from synthesis LLM output."""
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()
    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start != -1 and brace_end != -1:
        try:
            return json.loads(text[brace_start : brace_end + 1])
        except json.JSONDecodeError:
            pass
    return {"answer": text, "confidence_score": 0.5, "confidence_label": "MEDIUM"}
