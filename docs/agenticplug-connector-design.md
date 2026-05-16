# Agenticplug Connector Design

## Purpose

The `agenticplug_connector` is a minimal AgenticSeek tool that speaks to the agenticplug gateway API. It provides allowlisted, read-only cluster operations to the local AgenticSeek orchestrator without exposing raw shell access.

## Design Decisions

### Tool vs Provider vs MCP Adapter

**Decision: AgenticSeek Tool (sources/tools/)**

- Tools are the existing extension mechanism in this codebase (see `sources/tools/`).
- A tool can be invoked by the LLM using ` ```agenticplug ...``` ` blocks.
- Simpler than a full provider integration; sufficient for PoC.
- Future: could evolve into an MCP adapter or dedicated provider.

### HTTP Client Choice

Uses `httpx` (already a dependency in `pyproject.toml`) for async HTTP calls to the agenticplug gateway.

### Operation Allowlist

The connector has a hardcoded set of allowed operation names. Any operation not in this set is rejected **locally** before any network call.

```python
ALLOWED_OPERATIONS = frozenset({
    "job_status",
    "list_jobs",
})
```

This is the first security layer — the gateway enforces its own allowlist as a second layer.

## API Contract

All requests follow this shape:

```
POST <AGENTICPLUG_BASE_URL>/cluster/<operation>
Authorization: Bearer <AGENTICPLUG_TOKEN>
Content-Type: application/json

{
  "operation": "<operation>",
  "parameters": { ... }
}
```

Response:

```json
{
  "status": "success",
  "operation": "job_status",
  "data": { ... },
  "audit_id": "audit-<uuid>",
  "timestamp": "2026-05-15T12:00:00Z"
}
```

### Supported Operations

| Operation    | Method | Parameters            | Description                        |
|-------------|--------|-----------------------|------------------------------------|
| `job_status` | GET    | `job_id: str`         | Get status of a specific Slurm job |
| `list_jobs`  | GET    | `user: str (optional)`| List queued/running jobs for user  |

## Connector Class Structure

```
sources/tools/agenticplug_connector.py
  class AgenticplugConnector(Tools):
    - __init__(): load .env, validate config
    - execute(blocks, safety): route to allowlisted operation
    - _validate_operation(): check against ALLOWED_OPERATIONS
    - _call_gateway(): httpx POST/GET to agenticplug
    - _job_status(): format job_status call
    - _list_jobs(): format list_jobs call
    - execution_failure_check(): parse response for errors
    - interpreter_feedback(): format response for LLM
```

## Configuration

All values from environment variables, never hardcoded:

| Variable | Required | Default | Description |
|---------|----------|---------|-------------|
| `AGENTICPLUG_BASE_URL` | Yes | — | Base URL of agenticplug gateway |
| `AGENTICPLUG_TOKEN` | Yes | — | Bearer token for gateway auth |
| `AGENTICPLUG_VERIFY_SSL` | No | `true` | Enable/disable SSL verification |
| `AGENTICPLUG_TIMEOUT` | No | `30` | Request timeout in seconds |
| `AGENTICPLUG_DEFAULT_USER` | No | — | Default HPC username for queries |

## Safety Properties

1. **No arbitrary commands**: The connector only sends allowlisted operation names.
2. **No file access**: No file read/write operations are exposed through this connector.
3. **No raw shell**: The connector talks HTTP to the gateway, never execs shell commands.
4. **No secrets in code**: All credentials come from environment variables.
5. **Local validation first**: Operation names are checked against `ALLOWED_OPERATIONS` before any network call.
6. **No tunnel URLs or PATs**: Configuration uses only the gateway base URL and bearer token.
