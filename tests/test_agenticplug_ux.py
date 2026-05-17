import os
import sys
import unittest
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sources.schemas import (
    AgenticPlugTaskState,
    AgenticPlugRiskLevel,
    AgenticPlugTask,
    AgenticPlugTaskEvent,
    AgenticPlugApprovalRequest,
)
from sources.agenticplug_ux import AgenticPlugUXStore


class TestAgenticPlugUXStore(unittest.TestCase):
    def setUp(self):
        self.store = AgenticPlugUXStore()
        self.store._tasks.clear()
        self.store._task_logs.clear()

    def test_create_mock_task_creates_task_in_store(self):
        task = self.store.create_mock_task(title="test task", scenario="default")
        self.assertIsNotNone(task)
        self.assertIsNotNone(task.task_id)
        self.assertEqual(task.state, AgenticPlugTaskState.TASK_CREATED)
        self.assertEqual(task.title, "test task")
        tasks = self.store.list_tasks()
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].task_id, task.task_id)

    def test_create_mock_task_emits_creation_event(self):
        task = self.store.create_mock_task(title="test task")
        self.assertEqual(len(task.events), 1)
        self.assertEqual(task.events[0].state, AgenticPlugTaskState.TASK_CREATED)

    def test_run_mock_scenario_default_reaches_completed(self):
        task = self.store.create_mock_task(title="success task", scenario="default")
        task_id = task.task_id
        thread = self.store.run_mock_scenario(task, scenario="default")
        thread.join(timeout=30)
        stored = self.store.get_task(task_id)
        self.assertIsNotNone(stored)
        self.assertIn(
            stored.state,
            [AgenticPlugTaskState.GITHUB_HANDOFF, AgenticPlugTaskState.JOB_COMPLETED],
        )

    def test_run_mock_scenario_approval_required_stops_at_approval(self):
        task = self.store.create_mock_task(title="approval task", scenario="approval_required")
        task_id = task.task_id
        thread = self.store.run_mock_scenario(task, scenario="approval_required")
        thread.join(timeout=30)
        stored = self.store.get_task(task_id)
        self.assertEqual(stored.state, AgenticPlugTaskState.APPROVAL_REQUIRED)
        self.assertIsNotNone(stored.approval_request)
        self.assertEqual(stored.approval_request.risk_level, AgenticPlugRiskLevel.HIGH)

    def test_approval_denied_changes_state(self):
        task = self.store.create_mock_task(title="deny task", scenario="approval_required")
        task_id = task.task_id
        thread = self.store.run_mock_scenario(task, scenario="approval_required")
        thread.join(timeout=30)
        result = self.store.deny_task(task_id)
        self.assertEqual(result.state, AgenticPlugTaskState.APPROVAL_DENIED)

    def test_approve_resumes_workflow_to_completion(self):
        task = self.store.create_mock_task(title="approve me", scenario="approval_required")
        task_id = task.task_id
        thread = self.store.run_mock_scenario(task, scenario="approval_required")
        thread.join(timeout=30)
        self.store.approve_task(task_id)
        time.sleep(12)
        stored = self.store.get_task(task_id)
        self.assertIsNotNone(stored)
        self.assertNotEqual(stored.state, AgenticPlugTaskState.APPROVAL_REQUIRED)
        self.assertNotEqual(stored.state, AgenticPlugTaskState.APPROVAL_DENIED)

    def test_high_risk_is_never_auto_approved(self):
        risk_levels = [
            (AgenticPlugRiskLevel.LOW, False),
            (AgenticPlugRiskLevel.MEDIUM, False),
            (AgenticPlugRiskLevel.HIGH, True),
            (AgenticPlugRiskLevel.CRITICAL, True),
        ]
        for risk, expected in risk_levels:
            self.assertEqual(
                self.store.is_high_risk_operation(risk),
                expected,
                "{} should be high_risk={}".format(risk, expected),
            )

    def test_task_logs_bounded_to_max_lines(self):
        task = self.store.create_mock_task(title="log task")
        for i in range(300):
            self.store._append_log(task.task_id, "log line {}".format(i))
        logs = self.store.get_task_logs(task.task_id)
        self.assertLessEqual(len(logs), 200)

    def test_get_nonexistent_task_returns_none(self):
        task = self.store.get_task("nonexistent-id")
        self.assertIsNone(task)

    def test_get_task_logs_empty_for_nonexistent(self):
        logs = self.store.get_task_logs("nonexistent-id")
        self.assertEqual(logs, [])

    def test_deny_nonexistent_task_returns_none(self):
        result = self.store.deny_task("nonexistent-id")
        self.assertIsNone(result)

    def test_approve_nonexistent_task_returns_none(self):
        result = self.store.approve_task("nonexistent-id")
        self.assertIsNone(result)

    def test_approval_request_contains_all_fields(self):
        task = self.store.create_mock_task(title="fields test", scenario="approval_required")
        thread = self.store.run_mock_scenario(task, scenario="approval_required")
        thread.join(timeout=30)
        stored = self.store.get_task(task.task_id)
        req = stored.approval_request
        self.assertIsNotNone(req)
        self.assertEqual(req.operation, "submit_sbatch_job")
        self.assertEqual(req.target_connector, "slurm-connector-prod")
        self.assertEqual(req.target_cluster, "hpc-cluster-01")
        self.assertIn("sbatch", req.command_summary)
        self.assertTrue(len(req.affected_paths) > 0)
        self.assertEqual(req.risk_level, AgenticPlugRiskLevel.HIGH)

    def test_mock_scenario_failure_reaches_failed_state(self):
        task = self.store.create_mock_task(title="fail task", scenario="simulated_failure")
        task_id = task.task_id
        self.store.approve_task(task_id) if False else None
        task.state = AgenticPlugTaskState.APPROVAL_GRANTED
        thread = self.store._continue_after_approval(task, "simulated_failure")
        time.sleep(12)
        stored = self.store.get_task(task_id)
        self.assertEqual(stored.state, AgenticPlugTaskState.JOB_FAILED)
        self.assertEqual(stored.exit_code, 137)

    def test_event_stream_yields_events(self):
        task = self.store.create_mock_task(title="stream test", scenario="default")
        task_id = task.task_id
        thread = self.store.run_mock_scenario(task, scenario="default")
        thread.join(timeout=30)

        import asyncio
        async def _collect():
            events = []
            async for data in self.store.event_stream(task_id, poll_interval=0.1):
                events.append(data)
                if len(events) > 20:
                    break
            return events
        collected = asyncio.run(_collect())
        self.assertTrue(len(collected) > 0)

    def test_list_tasks_defaults_empty(self):
        tasks = self.store.list_tasks()
        self.assertEqual(tasks, [])


class TestAgenticPlugSchemas(unittest.TestCase):
    def test_task_state_enum_values(self):
        expected = {
            "task_created", "task_running", "approval_required",
            "approval_denied", "approval_granted", "job_submitted",
            "job_queued", "job_running", "job_completed", "job_failed",
            "artifact_available", "github_handoff",
        }
        actual = {s.value for s in AgenticPlugTaskState}
        self.assertEqual(expected, actual)

    def test_risk_level_enum_values(self):
        expected = {"low", "medium", "high", "critical"}
        actual = {r.value for r in AgenticPlugRiskLevel}
        self.assertEqual(expected, actual)

    def test_task_event_jsonify(self):
        event = AgenticPlugTaskEvent(
            task_id="123",
            state=AgenticPlugTaskState.TASK_CREATED,
            timestamp="2024-01-01T00:00:00Z",
            message="hello",
        )
        j = event.jsonify()
        self.assertEqual(j["task_id"], "123")
        self.assertEqual(j["state"], "task_created")
        self.assertEqual(j["message"], "hello")

    def test_task_jsonify_includes_optional_fields(self):
        task = AgenticPlugTask(
            task_id="123",
            state=AgenticPlugTaskState.ARTIFACT_AVAILABLE,
            artifact_url="http://example.com/art.tgz",
            github_handoff_url="http://github.com/pr/1",
        )
        j = task.jsonify()
        self.assertEqual(j["artifact_url"], "http://example.com/art.tgz")
        self.assertEqual(j["github_handoff_url"], "http://github.com/pr/1")

    def test_approval_request_jsonify(self):
        req = AgenticPlugApprovalRequest(
            task_id="t1",
            operation="submit_job",
            target_connector="slurm",
            target_cluster="hpc1",
            command_summary="sbatch run.sh",
            affected_paths=["/scratch/a", "/data/b"],
            risk_level=AgenticPlugRiskLevel.CRITICAL,
        )
        j = req.jsonify()
        self.assertEqual(j["risk_level"], "critical")
        self.assertEqual(j["affected_paths"], ["/scratch/a", "/data/b"])


if __name__ == "__main__":
    unittest.main()
