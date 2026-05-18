# Connector Discovery

EcoSeek can discover available compute backends by querying the AgenticPlug
gateway's connector discovery API.  This lets the runtime enumerate
connectors, inspect their capabilities and risk metadata, and poll health
status — all **before** the user has authenticated.

> EcoSeek is built on a fork of AgenticSeek.  We gratefully acknowledge the
> AgenticSeek project and contributors as the foundation for this work.
> EcoSeek is an independent downstream adaptation focused on scientific and
> ecological computing.

## How It Works

```
EcoSeek client
  connector_discovery.py
        |  GET /v1/connectors (unauthenticated)
        v
AgenticPlug gateway
  connector registry
        |
        v
Registered connectors (reumanlab, ecocoder-hpc, ...)
```

The discovery endpoints are **unauthenticated by design** so clients can
enumerate what is available before initiating the GitHub Device Flow login.

## Quick Start

### 1. Start the AgenticPlug Gateway

```bash
cd /path/to/agenticplug
node broker/server.js
```

### 2. Discover Connectors from Python

```python
from sources.connector_discovery import discover_connectors, print_connector_summary

connectors = discover_connectors("http://127.0.0.1:8080")
print_connector_summary(connectors)
```

Output:

```
Discovered 2 connector(s):
  [OK] reumanlab (hpc) v0.2.0 — tools: github, hpc_read, hpc_submit*
  [--] dev-local (local) v0.1.0 — tools: (none)
```

Tools marked with `*` require explicit approval before execution.

### 3. Query a Single Connector

```python
from sources.connector_discovery import discover_one

c = discover_one("reumanlab", "http://127.0.0.1:8080")
print(c.connector_id, c.health, c.connector_type)
print("Enabled tools:", [t.name for t in c.enabled_tools()])
print("Approval-gated:", [t.name for t in c.approval_gated_tools()])
```

### 4. Health Check

```python
from sources.connector_discovery import check_connector_health

health = check_connector_health("reumanlab", "http://127.0.0.1:8080")
print(health.status, health.age_ms, "ms since last heartbeat")
```

## Gateway URL Resolution

The discovery client resolves the gateway URL in this order:

| Priority | Source | Example |
|---|---|---|
| 1 | Explicit argument | `discover_connectors("http://gw:8080")` |
| 2 | `AGENTICPLUG_BASE_URL` env var | `export AGENTICPLUG_BASE_URL=http://gw:8080` |
| 3 | AgenticPlug session file | `~/.config/agenticplug/session.json` → `base_url` |
| 4 | Default | `http://127.0.0.1:8080` |

## Connector Fields

| Field | Type | Description |
|---|---|---|
| `connector_id` | string | Stable identifier |
| `display_name` | string | Human-readable label |
| `owner` | string | User or org that owns the connector |
| `version` | string | Connector software version |
| `connector_type` | string | `hpc`, `workstation`, `api`, or `local` |
| `capabilities` | dict | Boolean map of enabled capabilities |
| `tools` | list | Per-capability metadata with risk levels |
| `health` | string | `online`, `degraded`, or `stale` |
| `health_detail` | object | Detailed timing info |

## Tool Risk Levels

| Level | Description |
|---|---|
| `read` | Read-only operations (listing jobs, reading logs) |
| `compute` | Operations that consume resources or modify state |

Tools with `approval_required: true` must go through the approval workflow
(`POST /v1/approvals/{id}`) before execution.

## Connector Types

| Type | Description |
|---|---|
| `hpc` | HPC cluster (e.g., KU-HPC, Slurm-managed) |
| `workstation` | Lab workstation or personal machine |
| `api` | External API service |
| `local` | Local/development connector (default) |

## Health States

| State | Description |
|---|---|
| `online` | Healthy, heartbeats within threshold |
| `degraded` | Self-reported degraded status |
| `stale` | No heartbeat within `stale_threshold_ms` (default 90s) |

## Error Handling

The discovery client raises `ConnectorDiscoveryError` with actionable
messages for all failure modes:

| Scenario | Error Message |
|---|---|
| Gateway down | "Cannot reach AgenticPlug gateway at ..." |
| Gateway timeout | "... timed out after Ns" |
| Registry not configured | "... returned 503 — registry not configured" |
| Connector not found | "Connector 'X' not found ..." |
| Malformed response | "... missing 'connectors' array" |

## Security

- **No secrets in discovery output**: tokens, hashes, and enrollment
  secrets are stripped by the gateway before serialization.
- **Unauthenticated by design**: discovery is read-only and safe to
  call before login.
- **Fail-closed**: unreachable gateways and misconfigured registries
  raise errors rather than returning empty data.

## Integration with EcoSeek

The connector discovery module is used by the EcoSeek runtime to:

1. **Show available backends** on startup or in the UI.
2. **Route tasks** to the correct connector based on capabilities.
3. **Enforce approval gates** for high-risk operations (e.g., `hpc_submit`).
4. **Monitor health** to avoid routing to stale connectors.

## Cross-References

- [AgenticPlug connector discovery API docs](https://github.com/alrobles/agenticplug/blob/main/docs/connector-discovery-api.md)
- [EcoCoder cluster provider](ecocoder-cluster.md) — uses connectors for routing
- [DeepSeek BYOK provider](deepseek-byok.md) — alternative intelligence path
- [EcoCoder local provider](ecocoder-local.md) — local inference (no gateway needed)
