"""
AAR-02: Sub-Query Retrieval Router

Wraps existing EcoAgent tool calls and adds Phoenix span context to every
invocation.  Returns a structured ``RetrievalResult`` per sub-question.
"""

import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from ecoseek.aar.intent_decomposer import SubQuestion
from ecoseek.observability.phoenix_setup import get_tracer


@dataclass
class RetrievalResult:
    """Structured output for one retrieval attempt."""

    sub_query: str
    tool_used: str
    raw_result: str
    span_id: str = ""
    timestamp: float = 0.0
    success: bool = True
    error: str = ""

    def jsonify(self) -> dict:
        return {
            "sub_query": self.sub_query,
            "tool_used": self.tool_used,
            "raw_result": self.raw_result[:500],
            "span_id": self.span_id,
            "timestamp": self.timestamp,
            "success": self.success,
            "error": self.error,
        }


# ---------- Strategy → tool mapping ----------

# Default tool registry.  Each key is a search_strategy value from the
# intent decomposer; the value is the name of the tool function to call.
_DEFAULT_TOOL_MAP: Dict[str, str] = {
    "literature": "web_search",
    "species_db": "web_search",
    "sdm": "web_search",
    "general_web": "web_search",
}


def retrieve_for_subquestion(
    sub_q: SubQuestion,
    tool_call: Callable[[str, str], str],
    tool_map: Optional[Dict[str, str]] = None,
    query_id: str = "",
) -> RetrievalResult:
    """
    Execute a retrieval for a single sub-question.

    Parameters
    ----------
    sub_q : SubQuestion
        The decomposed sub-question.
    tool_call : callable(tool_name: str, query: str) -> str
        Adapter that invokes the actual tool (EcoAgent endpoint, searxng,
        etc.) and returns raw text output.
    tool_map : dict, optional
        Override default strategy → tool mapping.
    query_id : str
        Root query UUID for Phoenix tracing.

    Returns
    -------
    RetrievalResult
    """
    mapping = tool_map or _DEFAULT_TOOL_MAP
    tool_name = mapping.get(sub_q.search_strategy, "web_search")
    span_id = str(uuid.uuid4())

    tracer = get_tracer()
    span = None
    if tracer:
        span = tracer.start_span(
            name=f"aar.retrieve.{tool_name}",
            attributes={
                "ecoseek_query_id": query_id,
                "sub_question_id": sub_q.id,
                "search_strategy": sub_q.search_strategy,
                "tool_name": tool_name,
            },
        )

    try:
        raw = tool_call(tool_name, sub_q.question)
        result = RetrievalResult(
            sub_query=sub_q.question,
            tool_used=tool_name,
            raw_result=raw,
            span_id=span_id,
            timestamp=time.time(),
            success=True,
        )
    except Exception as exc:
        result = RetrievalResult(
            sub_query=sub_q.question,
            tool_used=tool_name,
            raw_result="",
            span_id=span_id,
            timestamp=time.time(),
            success=False,
            error=str(exc),
        )
    finally:
        if span is not None:
            try:
                span.set_attribute("retrieval.success", result.success)
                span.end()
            except Exception:
                pass

    return result


def retrieve_batch(
    sub_questions: List[SubQuestion],
    tool_call: Callable[[str, str], str],
    tool_map: Optional[Dict[str, str]] = None,
    query_id: str = "",
) -> List[RetrievalResult]:
    """Retrieve results for all sub-questions sequentially."""
    return [
        retrieve_for_subquestion(sq, tool_call, tool_map, query_id)
        for sq in sub_questions
    ]
