
from typing import Tuple, Callable, Optional, List
from enum import Enum
from pydantic import BaseModel
from sources.utility import pretty_print

class QueryRequest(BaseModel):
    query: str
    tts_enabled: bool = True

    def __str__(self):
        return f"Query: {self.query}, Language: {self.lang}, TTS: {self.tts_enabled}, STT: {self.stt_enabled}"

    def jsonify(self):
        return {
            "query": self.query,
            "tts_enabled": self.tts_enabled,
        }

class QueryResponse(BaseModel):
    done: str
    answer: str
    reasoning: str
    agent_name: str
    success: str
    blocks: dict
    status: str
    uid: str

    def __str__(self):
        return f"Done: {self.done}, Answer: {self.answer}, Agent Name: {self.agent_name}, Success: {self.success}, Blocks: {self.blocks}, Status: {self.status}, UID: {self.uid}"

    def jsonify(self):
        return {
            "done": self.done,
            "answer": self.answer,
            "reasoning": self.reasoning,
            "agent_name": self.agent_name,
            "success": self.success,
            "blocks": self.blocks,
            "status": self.status,
            "uid": self.uid
        }

class executorResult:
    """
    A class to store the result of a tool execution.
    """
    def __init__(self, block: str, feedback: str, success: bool, tool_type: str):
        """
        Initialize an agent with execution results.

        Args:
            block: The content or code block processed by the agent.
            feedback: Feedback or response information from the execution.
            success: Boolean indicating whether the agent's execution was successful.
            tool_type: The type of tool used by the agent for execution.
        """
        self.block = block
        self.feedback = feedback
        self.success = success
        self.tool_type = tool_type
    
    def __str__(self):
        return f"Tool: {self.tool_type}\nBlock: {self.block}\nFeedback: {self.feedback}\nSuccess: {self.success}"
    
    def jsonify(self):
        return {
            "block": self.block,
            "feedback": self.feedback,
            "success": self.success,
            "tool_type": self.tool_type
        }

    def show(self):
        pretty_print('▂'*64, color="status")
        pretty_print(self.feedback, color="success" if self.success else "failure")
        pretty_print('▂'*64, color="status")


class AgenticPlugTaskState(str, Enum):
    TASK_CREATED = "task_created"
    TASK_RUNNING = "task_running"
    APPROVAL_REQUIRED = "approval_required"
    APPROVAL_DENIED = "approval_denied"
    APPROVAL_GRANTED = "approval_granted"
    JOB_SUBMITTED = "job_submitted"
    JOB_QUEUED = "job_queued"
    JOB_RUNNING = "job_running"
    JOB_COMPLETED = "job_completed"
    JOB_FAILED = "job_failed"
    ARTIFACT_AVAILABLE = "artifact_available"
    GITHUB_HANDOFF = "github_handoff"


class AgenticPlugRiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AgenticPlugApprovalRequest(BaseModel):
    task_id: str
    operation: str
    target_connector: str
    target_cluster: str
    command_summary: str
    template_summary: str = ""
    affected_paths: List[str] = []
    risk_level: AgenticPlugRiskLevel = AgenticPlugRiskLevel.MEDIUM
    estimated_duration: str = ""
    requester_identity: str = ""

    def jsonify(self):
        return {
            "task_id": self.task_id,
            "operation": self.operation,
            "target_connector": self.target_connector,
            "target_cluster": self.target_cluster,
            "command_summary": self.command_summary,
            "template_summary": self.template_summary,
            "affected_paths": self.affected_paths,
            "risk_level": self.risk_level.value,
            "estimated_duration": self.estimated_duration,
            "requester_identity": self.requester_identity,
        }


class AgenticPlugTaskEvent(BaseModel):
    task_id: str
    state: AgenticPlugTaskState
    timestamp: str = ""
    message: str = ""
    approval_request: Optional[AgenticPlugApprovalRequest] = None
    artifact_url: Optional[str] = None
    github_handoff_url: Optional[str] = None
    log_lines: Optional[List[str]] = None
    exit_code: Optional[int] = None

    def jsonify(self):
        result = {
            "task_id": self.task_id,
            "state": self.state.value,
            "timestamp": self.timestamp,
            "message": self.message,
            "exit_code": self.exit_code,
        }
        if self.approval_request:
            result["approval_request"] = self.approval_request.jsonify()
        if self.artifact_url:
            result["artifact_url"] = self.artifact_url
        if self.github_handoff_url:
            result["github_handoff_url"] = self.github_handoff_url
        if self.log_lines:
            result["log_lines"] = self.log_lines
        return result


class AgenticPlugTask(BaseModel):
    task_id: str
    state: AgenticPlugTaskState = AgenticPlugTaskState.TASK_CREATED
    title: str = ""
    created_at: str = ""
    events: List[AgenticPlugTaskEvent] = []
    approval_request: Optional[AgenticPlugApprovalRequest] = None
    artifact_url: Optional[str] = None
    github_handoff_url: Optional[str] = None
    exit_code: Optional[int] = None

    def jsonify(self):
        result = {
            "task_id": self.task_id,
            "state": self.state.value,
            "title": self.title,
            "created_at": self.created_at,
            "events": [e.jsonify() for e in self.events],
            "exit_code": self.exit_code,
        }
        if self.approval_request:
            result["approval_request"] = self.approval_request.jsonify()
        if self.artifact_url:
            result["artifact_url"] = self.artifact_url
        if self.github_handoff_url:
            result["github_handoff_url"] = self.github_handoff_url
        return result