"""
AAR Orchestrator — the main entry point for Adaptive Agentic Retrieval.

Coordinates the full AAR loop:
  Intent Decomposer → Retrieval Router → Quality Assessor → Decision Gate → Synthesizer

Feature-flagged via ``ECOSEEK_AAR_ENABLED`` (default: false).
"""

import os
import uuid
import logging
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from ecoseek.aar.intent_decomposer import (
    DecompositionResult,
    SubQuestion,
    decompose_intent,
)
from ecoseek.aar.retrieval_router import RetrievalResult, retrieve_for_subquestion
from ecoseek.aar.quality_assessor import AssessmentResult, assess_quality
from ecoseek.aar.decision_gate import GateDecision, GateOutput, evaluate_gate
from ecoseek.aar.synthesizer import SynthesisResult, synthesize
from ecoseek.observability.phoenix_setup import get_tracer

logger = logging.getLogger("ecoseek.aar")


def is_aar_enabled() -> bool:
    """Check the feature flag."""
    return os.getenv("ECOSEEK_AAR_ENABLED", "false").lower() in ("true", "1", "yes")


@dataclass
class AARCycleLog:
    """Captures one retrieve → assess → gate cycle for audit."""
    sub_question: str
    cycle: int
    retrieval: Optional[RetrievalResult] = None
    assessment: Optional[AssessmentResult] = None
    gate: Optional[GateOutput] = None


@dataclass
class AARResult:
    """Full result of an AAR query, including audit trail."""
    query_id: str
    original_query: str
    decomposition: Optional[DecompositionResult] = None
    cycle_logs: List[AARCycleLog] = field(default_factory=list)
    synthesis: Optional[SynthesisResult] = None
    fallback_used: bool = False
    error: str = ""

    def jsonify(self) -> dict:
        return {
            "query_id": self.query_id,
            "original_query": self.original_query,
            "sub_questions": (
                [sq.dict() for sq in self.decomposition.sub_questions]
                if self.decomposition
                else []
            ),
            "total_cycles": len(self.cycle_logs),
            "synthesis": self.synthesis.jsonify() if self.synthesis else None,
            "fallback_used": self.fallback_used,
            "error": self.error,
        }


def run_aar(
    query: str,
    llm_call: Callable[[str], str],
    tool_call: Callable[[str, str], str],
    judge_call: Optional[Callable[[str], str]] = None,
    max_cycles: int = 3,
    phoenix_base_url: str = "",
) -> AARResult:
    """
    Execute the full AAR loop for a user query.

    Parameters
    ----------
    query : str
        User's raw research question.
    llm_call : callable(prompt: str) -> str
        Primary LLM (EcoCoder or DeepSeek BYOK) for decomposition and synthesis.
    tool_call : callable(tool_name: str, query: str) -> str
        Retrieval tool adapter.
    judge_call : callable(prompt: str) -> str, optional
        Separate LLM for the Quality Assessor (Nemotron / DeepSeek R1).
        Falls back to ``llm_call`` if not provided.
    max_cycles : int
        Maximum retrieval-assess-gate cycles per sub-question.
    phoenix_base_url : str
        Base URL for Phoenix trace links.

    Returns
    -------
    AARResult
    """
    query_id = str(uuid.uuid4())
    judge = judge_call or llm_call
    result = AARResult(query_id=query_id, original_query=query)

    tracer = get_tracer()
    root_span = tracer.start_span(
        name="aar.orchestrate",
        attributes={"ecoseek_query_id": query_id, "original_query": query[:500]},
    )

    try:
        # --- Step 1: Intent Decomposition ---
        decomp_span = tracer.start_span(
            name="aar.intent_decompose",
            attributes={"ecoseek_query_id": query_id},
        )
        try:
            decomposition = decompose_intent(query, llm_call)
            result.decomposition = decomposition
            logger.info(
                "Decomposed '%s' into %d sub-questions",
                query[:80],
                len(decomposition.sub_questions),
            )
        finally:
            decomp_span.end()

        # --- Step 2–4: Retrieve → Assess → Gate per sub-question ---
        all_retrievals: List[RetrievalResult] = []
        all_assessments: List[AssessmentResult] = []

        for sq in decomposition.sub_questions:
            current_query = sq.question
            original_query = sq.question

            for cycle in range(1, max_cycles + 1):
                cycle_sq = SubQuestion(
                    id=sq.id,
                    question=current_query,
                    search_strategy=sq.search_strategy,
                    priority=sq.priority,
                )

                # Retrieve
                rr = retrieve_for_subquestion(
                    cycle_sq, tool_call, query_id=query_id,
                )

                # Assess
                assessment = assess_quality(
                    current_query, rr.raw_result, judge, query_id=query_id,
                )

                # Gate
                gate_span = tracer.start_span(
                    name="aar.gate",
                    attributes={
                        "ecoseek_query_id": query_id,
                        "sub_question_id": sq.id,
                        "cycle": cycle,
                    },
                )
                gate_output = evaluate_gate(
                    assessment, original_query, cycle=cycle, max_cycles=max_cycles,
                )
                gate_span.set_attribute("gate.decision", gate_output.decision.value)
                gate_span.end()

                result.cycle_logs.append(AARCycleLog(
                    sub_question=current_query,
                    cycle=cycle,
                    retrieval=rr,
                    assessment=assessment,
                    gate=gate_output,
                ))

                logger.info(
                    "SQ%d cycle %d: verdict=%s, gate=%s",
                    sq.id, cycle, assessment.verdict, gate_output.decision.value,
                )

                if gate_output.decision in (GateDecision.PROCEED, GateDecision.FLAG):
                    all_retrievals.append(rr)
                    all_assessments.append(assessment)
                    break
                elif gate_output.decision == GateDecision.EXHAUSTED:
                    all_retrievals.append(rr)
                    all_assessments.append(assessment)
                    break
                else:
                    # RETRY — use reformulated query
                    current_query = gate_output.reformulated_query

        # --- Step 5: Synthesis ---
        if all_retrievals:
            synthesis = synthesize(
                query,
                all_retrievals,
                all_assessments,
                llm_call,
                query_id=query_id,
                phoenix_base_url=phoenix_base_url,
            )
            result.synthesis = synthesis
        else:
            result.fallback_used = True
            result.error = "No retrieval results obtained"

    except Exception as exc:
        logger.exception("AAR loop failed for query '%s'", query[:80])
        result.error = str(exc)
        result.fallback_used = True
    finally:
        root_span.end()

    return result
