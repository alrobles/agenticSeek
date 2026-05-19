"""
Unit tests for the AAR (Adaptive Agentic Retrieval) core modules.

Covers: AARTracker, Intent Decomposer, Quality Assessor, Decision Gate,
Retrieval Router, Synthesizer, Orchestrator, and Nemotron provider fallback.
"""

import json
import os
import sys
import threading
import unittest

# Ensure repo root is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sources.aar import AARTracker, AARStepType, AAREvent


# ── AARTracker ────────────────────────────────────────────────

class TestAARTracker(unittest.TestCase):

    def setUp(self):
        self.tracker = AARTracker()

    def test_empty_tracker(self):
        self.assertEqual(self.tracker.compute_aar(), 0.0)
        self.assertEqual(self.tracker.get_events(), [])
        s = self.tracker.summary()
        self.assertEqual(s["total_actions"], 0)
        self.assertEqual(s["aar"], 0.0)
        self.assertEqual(s["band"], "low")

    def test_log_event(self):
        ev = self.tracker.log("code_agent", "coder", AARStepType.EXECUTION, True)
        self.assertIsInstance(ev, AAREvent)
        self.assertEqual(len(self.tracker.get_events()), 1)

    def test_aar_computation(self):
        self.tracker.log("code_agent", "coder", AARStepType.EXECUTION, True)
        self.tracker.log("code_agent", "coder", AARStepType.HITL_TRIGGER, False)
        self.assertAlmostEqual(self.tracker.compute_aar(), 50.0)

    def test_aar_bands(self):
        # 100% autonomous → full
        for _ in range(10):
            self.tracker.log("a", "a", AARStepType.EXECUTION, True)
        self.assertEqual(self.tracker.get_autonomy_band(), "full")

        # Reset and test low
        self.tracker.reset()
        for _ in range(10):
            self.tracker.log("a", "a", AARStepType.HITL_TRIGGER, False)
        self.assertEqual(self.tracker.get_autonomy_band(), "low")

    def test_summary_consistency(self):
        """Summary should be a consistent snapshot (fix for Devin Review issue)."""
        for i in range(5):
            self.tracker.log("a", "a", "exec", True)
        for i in range(5):
            self.tracker.log("a", "a", "hitl", False)

        s = self.tracker.summary()
        self.assertEqual(s["total_actions"], 10)
        self.assertEqual(s["autonomous_actions"], 5)
        self.assertEqual(s["hitl_actions"], 5)
        self.assertAlmostEqual(s["aar"], 50.0)

    def test_thread_safety(self):
        """Concurrent logging should not corrupt the tracker."""
        errors = []

        def log_events():
            try:
                for _ in range(100):
                    self.tracker.log("a", "a", "exec", True)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=log_events) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0)
        self.assertEqual(len(self.tracker.get_events()), 400)

    def test_reset(self):
        self.tracker.log("a", "a", "exec", True)
        self.tracker.reset()
        self.assertEqual(len(self.tracker.get_events()), 0)

    def test_by_agent_breakdown(self):
        self.tracker.log("code_agent", "c", "exec", True)
        self.tracker.log("browser_agent", "b", "exec", True)
        self.tracker.log("code_agent", "c", "hitl", False)
        by_agent = self.tracker.compute_aar_by_agent()
        self.assertAlmostEqual(by_agent["code_agent"]["aar"], 50.0)
        self.assertAlmostEqual(by_agent["browser_agent"]["aar"], 100.0)


# ── Intent Decomposer ────────────────────────────────────────

class TestIntentDecomposer(unittest.TestCase):

    def test_valid_decomposition(self):
        from ecoseek.aar.intent_decomposer import decompose_intent

        mock_response = json.dumps({
            "original_query": "test query",
            "sub_questions": [
                {"id": 1, "question": "Sub Q1", "search_strategy": "literature", "priority": "high"},
                {"id": 2, "question": "Sub Q2", "search_strategy": "species_db", "priority": "medium"},
            ]
        })

        result = decompose_intent("test query", lambda _: mock_response)
        self.assertEqual(len(result.sub_questions), 2)
        self.assertEqual(result.original_query, "test query")
        self.assertEqual(result.sub_questions[0].search_strategy, "literature")

    def test_fallback_on_bad_json(self):
        from ecoseek.aar.intent_decomposer import decompose_intent

        result = decompose_intent("test query", lambda _: "not json at all", max_retries=0)
        self.assertEqual(len(result.sub_questions), 1)
        self.assertEqual(result.sub_questions[0].question, "test query")

    def test_json_in_code_fence(self):
        from ecoseek.aar.intent_decomposer import decompose_intent

        mock_response = '```json\n' + json.dumps({
            "original_query": "q",
            "sub_questions": [
                {"id": 1, "question": "SQ", "search_strategy": "sdm", "priority": "low"},
            ]
        }) + '\n```'

        result = decompose_intent("q", lambda _: mock_response)
        self.assertEqual(len(result.sub_questions), 1)
        self.assertEqual(result.sub_questions[0].search_strategy, "sdm")


# ── Quality Assessor ──────────────────────────────────────────

class TestQualityAssessor(unittest.TestCase):

    def test_valid_assessment(self):
        from ecoseek.aar.quality_assessor import assess_quality

        mock_response = json.dumps({
            "sub_question": "test",
            "verdict": "SUFFICIENT",
            "scores": {"relevance": 0.9, "authority": 0.8, "completeness": 0.7},
            "overall_score": 0.82,
            "reason": "Good evidence",
            "source_type": "peer_reviewed",
        })

        result = assess_quality("test", "evidence text", lambda _: mock_response)
        self.assertEqual(result.verdict, "SUFFICIENT")
        self.assertAlmostEqual(result.scores.relevance, 0.9)

    def test_fallback_on_bad_json(self):
        from ecoseek.aar.quality_assessor import assess_quality

        result = assess_quality("test", "evidence", lambda _: "garbage", max_retries=0)
        self.assertEqual(result.verdict, "INSUFFICIENT")
        self.assertEqual(result.overall_score, 0.0)


# ── Decision Gate ─────────────────────────────────────────────

class TestDecisionGate(unittest.TestCase):

    def _make_assessment(self, verdict, score=0.8):
        from ecoseek.aar.quality_assessor import AssessmentResult, AssessmentScores
        return AssessmentResult(
            sub_question="test",
            verdict=verdict,
            scores=AssessmentScores(relevance=score, authority=score, completeness=score),
            overall_score=score,
            reason="test",
            source_type="peer_reviewed",
        )

    def test_sufficient_proceeds(self):
        from ecoseek.aar.decision_gate import evaluate_gate, GateDecision
        a = self._make_assessment("SUFFICIENT")
        g = evaluate_gate(a, "original q")
        self.assertEqual(g.decision, GateDecision.PROCEED)

    def test_contradictory_flags(self):
        from ecoseek.aar.decision_gate import evaluate_gate, GateDecision
        a = self._make_assessment("CONTRADICTORY")
        g = evaluate_gate(a, "original q")
        self.assertEqual(g.decision, GateDecision.FLAG)

    def test_insufficient_retries(self):
        from ecoseek.aar.decision_gate import evaluate_gate, GateDecision
        a = self._make_assessment("INSUFFICIENT")
        g = evaluate_gate(a, "original q", cycle=1, max_cycles=3)
        self.assertEqual(g.decision, GateDecision.RETRY)
        self.assertIn("peer-reviewed", g.reformulated_query)

    def test_insufficient_exhausted(self):
        from ecoseek.aar.decision_gate import evaluate_gate, GateDecision
        a = self._make_assessment("INSUFFICIENT")
        g = evaluate_gate(a, "original q", cycle=3, max_cycles=3)
        self.assertEqual(g.decision, GateDecision.EXHAUSTED)


# ── Retrieval Router ──────────────────────────────────────────

class TestRetrievalRouter(unittest.TestCase):

    def test_retrieve_success(self):
        from ecoseek.aar.retrieval_router import retrieve_for_subquestion
        from ecoseek.aar.intent_decomposer import SubQuestion

        sq = SubQuestion(id=1, question="test", search_strategy="literature", priority="high")
        rr = retrieve_for_subquestion(sq, lambda tool, q: f"results for {q}")
        self.assertTrue(rr.success)
        self.assertIn("results for test", rr.raw_result)

    def test_retrieve_failure(self):
        from ecoseek.aar.retrieval_router import retrieve_for_subquestion
        from ecoseek.aar.intent_decomposer import SubQuestion

        sq = SubQuestion(id=1, question="test", search_strategy="literature", priority="high")

        def failing_tool(tool, q):
            raise RuntimeError("connection failed")

        rr = retrieve_for_subquestion(sq, failing_tool)
        self.assertFalse(rr.success)
        self.assertIn("connection failed", rr.error)


# ── Synthesizer ───────────────────────────────────────────────

class TestSynthesizer(unittest.TestCase):

    def test_synthesis(self):
        from ecoseek.aar.synthesizer import synthesize
        from ecoseek.aar.retrieval_router import RetrievalResult
        from ecoseek.aar.quality_assessor import AssessmentResult, AssessmentScores

        rr = RetrievalResult(
            sub_query="q1", tool_used="web_search",
            raw_result="Evidence about climate", span_id="span1",
        )
        ar = AssessmentResult(
            sub_question="q1", verdict="SUFFICIENT",
            scores=AssessmentScores(relevance=0.9, authority=0.8, completeness=0.7),
            overall_score=0.82, reason="Good", source_type="peer_reviewed",
        )

        mock_response = json.dumps({
            "answer": "Climate drives expansion [1].",
            "confidence_label": "HIGH",
            "confidence_score": 0.85,
        })

        result = synthesize("big question", [rr], [ar], lambda _: mock_response, query_id="q123")
        self.assertIn("[1]", result.answer)
        self.assertEqual(len(result.citations), 1)
        self.assertAlmostEqual(result.confidence, 0.85)


# ── Orchestrator ──────────────────────────────────────────────

class TestOrchestrator(unittest.TestCase):

    def test_feature_flag_default_off(self):
        from ecoseek.aar.orchestrator import is_aar_enabled
        os.environ.pop("ECOSEEK_AAR_ENABLED", None)
        self.assertFalse(is_aar_enabled())

    def test_feature_flag_on(self):
        from ecoseek.aar.orchestrator import is_aar_enabled
        os.environ["ECOSEEK_AAR_ENABLED"] = "true"
        self.assertTrue(is_aar_enabled())
        os.environ.pop("ECOSEEK_AAR_ENABLED", None)

    def test_full_aar_loop(self):
        from ecoseek.aar.orchestrator import run_aar

        decompose_response = json.dumps({
            "original_query": "test",
            "sub_questions": [
                {"id": 1, "question": "SQ1", "search_strategy": "literature", "priority": "high"},
            ]
        })

        assess_response = json.dumps({
            "sub_question": "SQ1",
            "verdict": "SUFFICIENT",
            "scores": {"relevance": 0.9, "authority": 0.8, "completeness": 0.7},
            "overall_score": 0.82,
            "reason": "Good",
            "source_type": "peer_reviewed",
        })

        synth_response = json.dumps({
            "answer": "Synthesized answer [1].",
            "confidence_label": "HIGH",
            "confidence_score": 0.85,
        })

        call_count = {"n": 0}

        def mock_llm(prompt: str) -> str:
            call_count["n"] += 1
            if call_count["n"] == 1:
                return decompose_response
            elif "assess" in prompt.lower() or "quality" in prompt.lower():
                return assess_response
            else:
                return synth_response

        def mock_tool(tool: str, query: str) -> str:
            return "Evidence: species X found in region Y."

        result = run_aar("test ecological query", mock_llm, mock_tool)
        self.assertIsNotNone(result.synthesis)
        self.assertEqual(len(result.decomposition.sub_questions), 1)
        self.assertFalse(result.fallback_used)


# ── Nemotron Provider ─────────────────────────────────────────

class TestNemotronProvider(unittest.TestCase):

    def test_get_judge_call_auto(self):
        from ecoseek.providers.nemotron import get_judge_call
        os.environ.pop("ECOSEEK_JUDGE_MODEL", None)
        os.environ.pop("NEMOTRON_BASE_URL", None)
        os.environ.pop("DEEPSEEK_API_KEY", None)
        judge = get_judge_call()
        self.assertTrue(callable(judge))

    def test_get_judge_call_specific(self):
        from ecoseek.providers.nemotron import get_judge_call
        os.environ["ECOSEEK_JUDGE_MODEL"] = "ecocoder"
        judge = get_judge_call()
        self.assertTrue(callable(judge))
        os.environ.pop("ECOSEEK_JUDGE_MODEL", None)


if __name__ == "__main__":
    unittest.main()
