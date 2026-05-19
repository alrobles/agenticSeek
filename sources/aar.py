"""
Agentic Autonomy Ratio (AAR) instrumentation for EcoSeek.

Tracks each perception-goal-action-evaluation loop across all agents and
computes the ratio of autonomous steps vs. human-in-the-loop (HITL) steps.

AAR = (Autonomous Actions / Total Actions) x 100%

Reference: matrixlabx.com/agentic-autonomy-ratio-metric-human-ai-workflow-efficiency
"""

import time
import threading
from enum import Enum
from typing import List, Optional
from dataclasses import dataclass, field, asdict


class AARStepType(str, Enum):
    PERCEPTION = "perception"
    DECOMPOSITION = "decomposition"
    EXECUTION = "execution"
    SELF_EVAL = "self_eval"
    HITL_TRIGGER = "hitl_trigger"
    SELF_HEALING = "self_healing"
    ALTERNATIVE_PATH = "alternative_path"


@dataclass
class AAREvent:
    timestamp: float
    agent_type: str
    agent_name: str
    step_type: str
    autonomous: bool
    confidence: Optional[float] = None
    notes: str = ""
    session_id: str = ""

    def jsonify(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "agent_type": self.agent_type,
            "agent_name": self.agent_name,
            "step_type": self.step_type,
            "autonomous": self.autonomous,
            "confidence": self.confidence,
            "notes": self.notes,
            "session_id": self.session_id,
        }


class AARTracker:
    """Thread-safe tracker that collects AAR events and computes metrics."""

    def __init__(self):
        self._events: List[AAREvent] = []
        self._lock = threading.Lock()
        self._session_id: str = ""

    def set_session(self, session_id: str) -> None:
        with self._lock:
            self._session_id = session_id

    def reset(self) -> None:
        with self._lock:
            self._events.clear()

    def log(
        self,
        agent_type: str,
        agent_name: str,
        step_type: str,
        autonomous: bool,
        confidence: Optional[float] = None,
        notes: str = "",
    ) -> AAREvent:
        event = AAREvent(
            timestamp=time.time(),
            agent_type=agent_type,
            agent_name=agent_name,
            step_type=step_type,
            autonomous=autonomous,
            confidence=confidence,
            notes=notes,
            session_id=self._session_id,
        )
        with self._lock:
            self._events.append(event)
        return event

    def get_events(self) -> List[AAREvent]:
        with self._lock:
            return list(self._events)

    def compute_aar(self) -> float:
        with self._lock:
            if not self._events:
                return 0.0
            autonomous = sum(1 for e in self._events if e.autonomous)
            return (autonomous / len(self._events)) * 100.0

    def compute_aar_by_agent(self) -> dict:
        with self._lock:
            agents: dict = {}
            for e in self._events:
                key = e.agent_type
                if key not in agents:
                    agents[key] = {"autonomous": 0, "total": 0}
                agents[key]["total"] += 1
                if e.autonomous:
                    agents[key]["autonomous"] += 1
            return {
                k: {
                    "aar": (v["autonomous"] / v["total"] * 100.0) if v["total"] else 0.0,
                    "autonomous": v["autonomous"],
                    "total": v["total"],
                }
                for k, v in agents.items()
            }

    def compute_aar_by_step(self) -> dict:
        with self._lock:
            steps: dict = {}
            for e in self._events:
                key = e.step_type
                if key not in steps:
                    steps[key] = {"autonomous": 0, "total": 0}
                steps[key]["total"] += 1
                if e.autonomous:
                    steps[key]["autonomous"] += 1
            return {
                k: {
                    "aar": (v["autonomous"] / v["total"] * 100.0) if v["total"] else 0.0,
                    "autonomous": v["autonomous"],
                    "total": v["total"],
                }
                for k, v in steps.items()
            }

    def get_autonomy_band(self) -> str:
        aar = self.compute_aar()
        if aar <= 30:
            return "low"
        elif aar <= 70:
            return "conditional"
        elif aar <= 90:
            return "high"
        else:
            return "full"

    def summary(self) -> dict:
        events = self.get_events()
        return {
            "aar": round(self.compute_aar(), 1),
            "band": self.get_autonomy_band(),
            "total_actions": len(events),
            "autonomous_actions": sum(1 for e in events if e.autonomous),
            "hitl_actions": sum(1 for e in events if not e.autonomous),
            "by_agent": self.compute_aar_by_agent(),
            "by_step": self.compute_aar_by_step(),
        }


# Singleton tracker shared across the application
aar_tracker = AARTracker()
