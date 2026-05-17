import asyncio
import uuid
import time
import threading
from datetime import datetime, timezone
from typing import Dict, List, Optional

from sources.schemas import (
    AgenticPlugTask,
    AgenticPlugTaskEvent,
    AgenticPlugTaskState,
    AgenticPlugApprovalRequest,
    AgenticPlugRiskLevel,
)
from sources.logger import Logger

logger = Logger("agenticplug_ux.log")

MAX_LOG_LINES = 200
MAX_ARTIFACT_LENGTH = 50000


class AgenticPlugUXStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._tasks: Dict[str, AgenticPlugTask] = {}
        self._task_logs: Dict[str, List[str]] = {}

    def create_mock_task(self, title: str = "", scenario: str = "default") -> AgenticPlugTask:
        task_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        task = AgenticPlugTask(
            task_id=task_id,
            state=AgenticPlugTaskState.TASK_CREATED,
            title=title or "AgenticPlug task {:.8}".format(task_id),
            created_at=now,
        )
        with self._lock:
            self._tasks[task_id] = task
            self._task_logs[task_id] = []
        self._emit_event(task, AgenticPlugTaskState.TASK_CREATED, "Task created")
        logger.info("Mock task created: {} ({})".format(task_id, scenario))
        return task

    def _emit_event(
        self,
        task: AgenticPlugTask,
        state: AgenticPlugTaskState,
        message: str = "",
        approval_request: Optional[AgenticPlugApprovalRequest] = None,
        artifact_url: Optional[str] = None,
        github_handoff_url: Optional[str] = None,
        exit_code: Optional[int] = None,
    ):
        event = AgenticPlugTaskEvent(
            task_id=task.task_id,
            state=state,
            timestamp=datetime.now(timezone.utc).isoformat(),
            message=message,
            approval_request=approval_request,
            artifact_url=artifact_url,
            github_handoff_url=github_handoff_url,
            exit_code=exit_code,
        )
        with self._lock:
            task.state = state
            if approval_request:
                task.approval_request = approval_request
            if artifact_url:
                task.artifact_url = artifact_url
            if github_handoff_url:
                task.github_handoff_url = github_handoff_url
            if exit_code is not None:
                task.exit_code = exit_code
            task.events.append(event)
        self._append_log(task.task_id, "[{}] {}".format(state.value, message) if message else "[{}]".format(state.value))

    def _append_log(self, task_id: str, line: str):
        with self._lock:
            logs = self._task_logs.get(task_id, [])
            logs.append(line)
            if len(logs) > MAX_LOG_LINES:
                self._task_logs[task_id] = logs[-MAX_LOG_LINES:]

    def run_mock_scenario(self, task: AgenticPlugTask, scenario: str = "default"):
        def _run():
            _id = task.task_id
            sleep = lambda s: time.sleep(s)
            try:
                sleep(1.0)
                self._emit_event(task, AgenticPlugTaskState.TASK_RUNNING, "Task is initializing")
                if scenario == "approval_required":
                    sleep(1.5)
                    approval = AgenticPlugApprovalRequest(
                        task_id=_id,
                        operation="submit_sbatch_job",
                        target_connector="slurm-connector-prod",
                        target_cluster="hpc-cluster-01",
                        command_summary="sbatch --nodes=4 --ntasks-per-node=16 --time=08:00:00 run_simulation.sh",
                        template_summary="Molecular dynamics simulation template v3.2.1",
                        affected_paths=["/scratch/projects/sim_2025/", "/data/shared/model_checkpoints/"],
                        risk_level=AgenticPlugRiskLevel.HIGH,
                        estimated_duration="8 hours",
                        requester_identity="planner-agent@agenticseek",
                    )
                    self._emit_event(
                        task, AgenticPlugTaskState.APPROVAL_REQUIRED,
                        "Approval required for high-risk operation",
                        approval_request=approval,
                    )
                    logger.info("Task {} waiting for approval".format(_id))
                    return
                self._continue_after_approval(task, scenario)
            except Exception as e:
                logger.error("Mock scenario error for {}: {}".format(_id, str(e)))
                self._emit_event(task, AgenticPlugTaskState.JOB_FAILED, "Unexpected error: {}".format(str(e)), exit_code=1)

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        return thread

    def approve_task(self, task_id: str) -> AgenticPlugTask:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return None
            if task.state != AgenticPlugTaskState.APPROVAL_REQUIRED:
                return task
        self._emit_event(task, AgenticPlugTaskState.APPROVAL_GRANTED, "Approval granted by user")
        self._continue_after_approval(task, "default")
        return task

    def deny_task(self, task_id: str) -> AgenticPlugTask:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return None
            if task.state != AgenticPlugTaskState.APPROVAL_REQUIRED:
                return task
        self._emit_event(task, AgenticPlugTaskState.APPROVAL_DENIED, "Approval denied by user")
        return task

    def _continue_after_approval(self, task: AgenticPlugTask, scenario: str):
        _id = task.task_id
        sleep = lambda s: time.sleep(s)
        try:
            sleep(1.0)
            self._emit_event(task, AgenticPlugTaskState.JOB_SUBMITTED, "Slurm job submitted")
            sleep(1.5)
            self._emit_event(task, AgenticPlugTaskState.JOB_QUEUED, "Job queued (priority: normal)")
            self._append_log(_id, "Submitted batch job 428391")
            sleep(1.5)
            self._emit_event(task, AgenticPlugTaskState.JOB_RUNNING, "Job running on node[027-030]")
            for i in range(1, 6):
                sleep(1.0)
                self._append_log(_id, "[node027] Iteration {} / 10000 complete".format(i * 2000))
            if scenario == "simulated_failure":
                self._emit_event(task, AgenticPlugTaskState.JOB_FAILED, "Job failed: OOM at iteration 8000", exit_code=137)
                self._append_log(_id, "slurmstepd: error: Detected 1 oom-kill event")
                return
            sleep(1.0)
            self._emit_event(task, AgenticPlugTaskState.JOB_COMPLETED, "Job completed successfully", exit_code=0)
            sleep(1.0)
            artifact_url = "https://storage.example.com/artifacts/{}/results.tar.gz".format(_id)
            self._emit_event(task, AgenticPlugTaskState.ARTIFACT_AVAILABLE, "Artifact available for download", artifact_url=artifact_url)
            sleep(1.0)
            handoff_url = "https://github.com/org/repo/pull/{}".format(abs(hash(_id)) % 9000 + 1000)
            self._emit_event(task, AgenticPlugTaskState.GITHUB_HANDOFF, "GitHub handoff link available", github_handoff_url=handoff_url)
        except Exception as e:
            logger.error("Mock scenario continuation error for {}: {}".format(_id, str(e)))
            self._emit_event(task, AgenticPlugTaskState.JOB_FAILED, "Unexpected error: {}".format(str(e)), exit_code=1)

    def get_task(self, task_id: str) -> Optional[AgenticPlugTask]:
        with self._lock:
            return self._tasks.get(task_id)

    def list_tasks(self) -> List[AgenticPlugTask]:
        with self._lock:
            return list(self._tasks.values())

    def get_task_logs(self, task_id: str) -> List[str]:
        with self._lock:
            return list(self._task_logs.get(task_id, []))

    async def event_stream(self, task_id: str, poll_interval: float = 2.0):
        last_event_count = 0
        while True:
            await asyncio.sleep(poll_interval)
            task = self.get_task(task_id)
            if task is None:
                yield "data: {{\"error\": \"task not found\"}}\n\n"
                break
            with self._lock:
                current_events = len(task.events)
            while last_event_count < current_events:
                with self._lock:
                    event = task.events[last_event_count]
                yield "data: {}\n\n".format(__import__("json").dumps(event.jsonify()))
                last_event_count += 1
            if task.state in (
                AgenticPlugTaskState.JOB_COMPLETED,
                AgenticPlugTaskState.JOB_FAILED,
                AgenticPlugTaskState.APPROVAL_DENIED,
                AgenticPlugTaskState.GITHUB_HANDOFF,
            ):
                yield "data: {{\"task_id\": \"{}\", \"state\": \"closed\"}}\n\n".format(task_id)
                break

    def is_high_risk_operation(self, risk_level):
        return risk_level in (AgenticPlugRiskLevel.HIGH, AgenticPlugRiskLevel.CRITICAL)


ux_store = AgenticPlugUXStore()
