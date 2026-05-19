"""
AAR-04: Adaptive Decision Gate

Pure Python logic — NO LLM calls.  Takes an ``AssessmentResult`` and
decides whether to proceed to synthesis, reformulate the sub-query and
retry, or flag a contradiction for the synthesiser.

Design invariant (Claude Code paper): the model reasons, the harness
enforces.  This module is deterministic infrastructure.
"""

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

from ecoseek.aar.quality_assessor import AssessmentResult


class GateDecision(str, Enum):
    PROCEED = "proceed"       # evidence is SUFFICIENT → go to synthesis
    RETRY = "retry"           # evidence is INSUFFICIENT → reformulate and re-retrieve
    FLAG = "flag"             # evidence is CONTRADICTORY → include both views in synthesis
    EXHAUSTED = "exhausted"   # max retries reached → proceed with whatever we have


@dataclass
class GateOutput:
    decision: GateDecision
    reformulated_query: str  # non-empty only when decision == RETRY
    cycle: int               # current cycle count (1-indexed)
    max_cycles: int
    assessment: AssessmentResult
    notes: str = ""

    def jsonify(self) -> dict:
        return {
            "decision": self.decision.value,
            "reformulated_query": self.reformulated_query,
            "cycle": self.cycle,
            "max_cycles": self.max_cycles,
            "verdict": self.assessment.verdict,
            "overall_score": self.assessment.overall_score,
            "notes": self.notes,
        }


# ---------- Reformulation strategies ----------

_REFORMULATION_SUFFIXES: List[str] = [
    " (peer-reviewed sources only)",
    " (published after 2018, peer-reviewed)",
    " (include specific quantitative data or measurements)",
]


def _reformulate(original_query: str, cycle: int) -> str:
    """Append a refinement suffix based on the current cycle number."""
    idx = min(cycle - 1, len(_REFORMULATION_SUFFIXES) - 1)
    return original_query + _REFORMULATION_SUFFIXES[idx]


# ---------- Gate logic ----------

def evaluate_gate(
    assessment: AssessmentResult,
    original_sub_query: str,
    cycle: int = 1,
    max_cycles: int = 3,
) -> GateOutput:
    """
    Deterministic decision gate.

    Parameters
    ----------
    assessment : AssessmentResult
        Output from the Quality Assessor.
    original_sub_query : str
        The original sub-question (before any reformulation).
    cycle : int
        Current retrieval cycle (1-indexed).
    max_cycles : int
        Maximum allowed retrieval cycles before exhaustion.

    Returns
    -------
    GateOutput
    """
    verdict = assessment.verdict

    if verdict == "SUFFICIENT":
        return GateOutput(
            decision=GateDecision.PROCEED,
            reformulated_query="",
            cycle=cycle,
            max_cycles=max_cycles,
            assessment=assessment,
            notes="Evidence meets all quality thresholds.",
        )

    if verdict == "CONTRADICTORY":
        return GateOutput(
            decision=GateDecision.FLAG,
            reformulated_query="",
            cycle=cycle,
            max_cycles=max_cycles,
            assessment=assessment,
            notes="Contradictory evidence detected — both views forwarded to synthesis.",
        )

    # INSUFFICIENT
    if cycle >= max_cycles:
        return GateOutput(
            decision=GateDecision.EXHAUSTED,
            reformulated_query="",
            cycle=cycle,
            max_cycles=max_cycles,
            assessment=assessment,
            notes=f"Max cycles ({max_cycles}) reached with INSUFFICIENT evidence.",
        )

    reformulated = _reformulate(original_sub_query, cycle)
    return GateOutput(
        decision=GateDecision.RETRY,
        reformulated_query=reformulated,
        cycle=cycle,
        max_cycles=max_cycles,
        assessment=assessment,
        notes=f"Reformulated query for cycle {cycle + 1}.",
    )
