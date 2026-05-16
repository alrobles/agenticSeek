import os
import json
from typing import Optional

from dotenv import load_dotenv

from sources.tools.tools import Tools

load_dotenv()

# Allowlisted operations — only these can be sent to the gateway.
# This is the first security layer; the gateway enforces its own allowlist.
ALLOWED_OPERATIONS = frozenset({
    "job_status",
    "list_jobs",
})


class AgenticplugConnector(Tools):
    """
    Minimal safe connector to the agenticplug gateway API.

    Provides allowlisted, read-only cluster operations to the local
    AgenticSeek orchestrator. Never exposes raw shell access, file I/O,
    or arbitrary command execution.

    Configuration via environment variables (see .env.example):
      AGENTICPLUG_BASE_URL   — gateway base URL (required)
      AGENTICPLUG_TOKEN      — bearer token (required)
      AGENTICPLUG_VERIFY_SSL — SSL verification (default: true)
      AGENTICPLUG_TIMEOUT    — request timeout in seconds (default: 30)
      AGENTICPLUG_DEFAULT_USER — default HPC username (optional)
    """

    def __init__(self):
        super().__init__()
        self.tag = "agenticplug"
        self.name = "agenticplug_connector"
        self.description = "Secure gateway connector for allowlisted cluster operations"

        self.base_url = os.getenv("AGENTICPLUG_BASE_URL", "").rstrip("/")
        self.token = os.getenv("AGENTICPLUG_TOKEN", "")
        self.verify_ssl = os.getenv("AGENTICPLUG_VERIFY_SSL", "true").lower() != "false"
        self.timeout = int(os.getenv("AGENTICPLUG_TIMEOUT", "30"))
        self.default_user = os.getenv("AGENTICPLUG_DEFAULT_USER", "")
        self.write_enabled = os.getenv("AGENTICPLUG_WRITE_ENABLED", "false").lower() == "true"

    def execute(self, blocks: [str], safety: bool) -> str:
        """
        Route a block to the matching allowlisted operation.

        Block format:
            ```agenticplug
            operation: list_jobs
            user: reumanlab
            ```

        All operation names are validated against ALLOWED_OPERATIONS
        before any network call.
        """
        if not blocks or len(blocks) == 0:
            return json.dumps({
                "status": "error",
                "error": {"code": "NO_BLOCKS", "message": "No operation blocks provided"}
            })

        if not self.base_url or not self.token:
            return json.dumps({
                "status": "error",
                "error": {
                    "code": "NOT_CONFIGURED",
                    "message": "AGENTICPLUG_BASE_URL and AGENTICPLUG_TOKEN must be set in .env"
                }
            })

        results = []
        for block in blocks:
            operation = self.get_parameter_value(block, "operation")
            if not operation:
                operation = "list_jobs"  # default to list_jobs

            if not self._validate_operation(operation):
                results.append(json.dumps({
                    "status": "error",
                    "error": {
                        "code": "OPERATION_NOT_ALLOWED",
                        "message": f"Operation '{operation}' is not in the allowlist. "
                                   f"Allowed: {sorted(ALLOWED_OPERATIONS)}"
                    }
                }))
                continue

            params = self._parse_params(block)
            result = self._dispatch(operation, params)
            results.append(result)

        return "\n---\n".join(results)

    def execution_failure_check(self, output: str) -> bool:
        """Check if gateway response indicates failure."""
        if not output:
            return True
        try:
            parsed = json.loads(output)
            return parsed.get("status") != "success"
        except (json.JSONDecodeError, AttributeError):
            return True

    def interpreter_feedback(self, output: str) -> str:
        """Format gateway response for the LLM."""
        if not output:
            return "No response from agenticplug gateway."
        try:
            parsed = json.loads(output)
            if parsed.get("status") == "success":
                data = parsed.get("data", {})
                return json.dumps(data, indent=2)
            error = parsed.get("error", {})
            return f"Gateway error: {error.get('message', 'Unknown error')} (code: {error.get('code', 'UNKNOWN')})"
        except json.JSONDecodeError:
            return f"Raw gateway response: {output[:500]}"

    def _validate_operation(self, operation: str) -> bool:
        """Check operation against the local allowlist."""
        if operation not in ALLOWED_OPERATIONS:
            self.logger.warning(f"Operation '{operation}' rejected by local allowlist")
            return False
        if operation in ("submit_job", "cancel_job") and not self.write_enabled:
            self.logger.warning(f"Write operation '{operation}' rejected: AGENTICPLUG_WRITE_ENABLED is false")
            return False
        return True

    def _parse_params(self, block: str) -> dict:
        """Extract key=value parameters from a block."""
        params = {}
        for line in block.strip().split("\n"):
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip("'").strip('"')
                if key != "operation":
                    params[key] = value
        return params

    def _dispatch(self, operation: str, params: dict) -> str:
        """Dispatch to the appropriate operation handler.

        Returns a JSON string representing the gateway response.
        In PoC: returns a structured placeholder since the gateway
        is not yet deployed. Replace with actual httpx calls in Phase 1.
        """
        if operation == "list_jobs":
            return self._list_jobs(params)
        elif operation == "job_status":
            return self._job_status(params)
        else:
            return json.dumps({
                "status": "error",
                "error": {
                    "code": "NOT_IMPLEMENTED",
                    "message": f"Operation '{operation}' allowlisted but not yet implemented"
                }
            })

    def _list_jobs(self, params: dict) -> str:
        """Build a list_jobs request.

        PoC placeholder — returns the request shape that will be sent
        to the gateway once deployed. In Phase 1, replace with:
            import httpx
            async with httpx.AsyncClient(...) as client:
                resp = await client.get(f"{self.base_url}/cluster/jobs/list", ...)
                return resp.text
        """
        user = params.get("user", self.default_user)
        request = {
            "operation": "list_jobs",
            "parameters": {"user": user},
            "gateway_url": f"{self.base_url}/cluster/jobs/list" if self.base_url else None,
        }
        self.logger.info(f"list_jobs placeholder: user={user}")
        return json.dumps({
            "status": "placeholder",
            "message": "Gateway not yet deployed. This is the request shape that will be sent.",
            "request": request,
            "note": "Replace this placeholder with httpx call in Phase 1 (see docs/roadmap.md)"
        })

    def _job_status(self, params: dict) -> str:
        """Build a job_status request.

        PoC placeholder — returns the request shape that will be sent
        to the gateway once deployed.
        """
        job_id = params.get("job_id", "")
        if not job_id:
            return json.dumps({
                "status": "error",
                "error": {"code": "MISSING_PARAM", "message": "job_id is required for job_status"}
            })
        request = {
            "operation": "job_status",
            "parameters": {"job_id": job_id},
            "gateway_url": f"{self.base_url}/cluster/jobs/status" if self.base_url else None,
        }
        self.logger.info(f"job_status placeholder: job_id={job_id}")
        return json.dumps({
            "status": "placeholder",
            "message": "Gateway not yet deployed. This is the request shape that will be sent.",
            "request": request,
            "note": "Replace this placeholder with httpx call in Phase 1 (see docs/roadmap.md)"
        })
