# Security Model

## Scope

This document covers the security model for the local AgenticSeek → agenticplug → reumanlab → KU HPC chain. It establishes trust boundaries, authentication flows, and the threat model.

## Trust Boundaries

```
┌────────────────────────────────────────────────────────────────┐
│ Zone 0: Local Laptop (Untrusted for cluster operations)        │
│ - AgenticSeek UI/CLI                                           │
│ - agenticplug_connector tool                                   │
│ - No SSH keys to KU HPC                                        │
│ - No Kubernetes/Slurm credentials                              │
│ - User-authenticated session (OAuth/OIDC)                      │
└──────────────────────────────┬─────────────────────────────────┘
                               │ HTTPS + Bearer Token
                               │ (mutual TLS optional)
┌──────────────────────────────▼─────────────────────────────────┐
│ Zone 1: agenticplug Gateway (Trusted edge)                     │
│ - Authentication enforcement                                   │
│ - Operation allowlist validation                               │
│ - Request audit logging                                        │
│ - Rate limiting                                                │
│ - No cluster credentials exposed to Zone 0                     │
└──────────────────────────────┬─────────────────────────────────┘
                               │ SSH (key-based, no agent forwarding)
                               │ or internal gRPC
┌──────────────────────────────▼─────────────────────────────────┐
│ Zone 2: reumanlab Bastion (Trusted execution)                  │
│ - OpenClaw + opencode.ai                                       │
│ - DeepSeek LLM                                                 │
│ - GitHub CLI (App-based auth)                                  │
│ - SSH client to KU HPC                                         │
└──────────────────────────────┬─────────────────────────────────┘
                               │ SSH (key-based)
┌──────────────────────────────▼─────────────────────────────────┐
│ Zone 3: KU HPC (Trusted compute)                              │
│ - Slurm workload manager                                       │
│ - Work/scratch storage                                         │
│ - GPU nodes                                                    │
└────────────────────────────────────────────────────────────────┘
```

## Authentication Flow

### Human User (Browser)

1. User opens AgenticSeek UI locally.
2. AgenticSeek redirects to agenticplug OAuth/OIDC endpoint.
3. User authenticates via Cloudflare Access or OIDC provider.
4. Agenticplug issues a short-lived session token.
5. AgenticSeek uses this token for subsequent API calls.

### Machine/Service

1. Service obtains a short-lived token from agenticplug token endpoint.
2. Token is passed as `Authorization: Bearer <token>` header.
3. agenticplug validates the token on every request.
4. No long-lived PATs stored in AgenticSeek config.

### GitHub App Model (for durable handoff)

- GitHub App installed on the target repo.
- agenticplug holds the App private key (never exposed to laptop).
- AgenticSeek requests issue/PR creation through the gateway.
- Gateway uses GitHub App to create issues/PRs with fine-grained permissions.

## Authorization Model

### Operation Allowlist (Two-Layer)

**Layer 1 — Local (AgenticSeek connector):**
```python
ALLOWED_OPERATIONS = frozenset({"job_status", "list_jobs"})
```
Any operation not in this set is rejected before any network call.

**Layer 2 — Gateway (agenticplug):**
Each operation requires:
- Valid authentication
- Operation in gateway-side allowlist
- User/principal authorized for the specific cluster resource

### Principle of Least Privilege

- Read-only operations only in PoC (no write, no shell, no file access).
- Future write operations will require explicit per-operation authorization.
- No `run_command`, `read_file`, or `write_file` endpoints exposed to Zone 0.

## Audit Model

Every gateway request produces an audit record:

```json
{
  "audit_id": "audit-<uuid>",
  "timestamp": "2026-05-15T12:00:00Z",
  "principal": "user@example.com",
  "source_ip": "192.168.1.100",
  "operation": "list_jobs",
  "parameters": {"user": "reumanlab"},
  "status": "success",
  "latency_ms": 234
}
```

Audit logs are stored in the gateway and can be shipped to a centralized log system.

## Threat Model

### Assets to Protect

| Asset | Location | Sensitivity |
|-------|----------|-------------|
| HPC credentials (SSH keys, Slurm tokens) | reumanlab, agenticplug | Critical |
| Cluster job data | KU HPC, in transit | Medium |
| User authentication tokens | agenticplug | Critical |
| GitHub App private key | agenticplug | Critical |
| AgenticSeek .env file | Local laptop | Medium |

### Threat Scenarios

| # | Threat | Impact | Mitigation |
|---|--------|--------|------------|
| T1 | Local laptop compromise → attacker gets .env | Attacker can call gateway API | Short-lived tokens, MFA, audit logging, IP restriction |
| T2 | Malicious AgenticSeek plugin sends arbitrary commands | Cluster compromise | Operation allowlist enforced locally AND at gateway |
| T3 | Man-in-the-middle on laptop→gateway | Token theft | HTTPS with cert validation; mutual TLS (future) |
| T4 | Gateway bypass — direct SSH to reumanlab | Full cluster access | reumanlab only accepts SSH from gateway IP; key-based auth only |
| T5 | Token replay attack | Unauthorized API access | Short token TTL (5-15 min), audit IDs are unique and logged |
| T6 | Insider threat — compromised gateway operator | Cluster compromise | Audit trail, dual control for write operations, alerting |
| T7 | GitHub App private key leak | Unauthorized issue/PR creation | Rotate keys, limit App permissions to specific repos |
| T8 | Slurm command injection via job parameters | Arbitrary cluster execution | Input validation, parameter allowlisting, no shell interpolation |

### Risk Acceptance

- **Local laptop considered untrusted** for cluster operations. No HPC credentials stored there.
- **No public unauthenticated endpoints.** The gateway is not exposed to the public internet without auth.
- **Admin plane** (Tailscale/WireGuard/SSH) is separate from the public web API plane.
- **Write operations are future scope** and will require additional authorization gates.

## Security Decisions (for this PR)

1. **No raw shell execution.** The connector calls the gateway API only.
2. **No file read/write endpoints.** Out of scope for PoC.
3. **No embedded secrets.** All configuration via environment variables.
4. **Local allowlist validation.** First line of defense before any network call.
5. **httpx with SSL verification.** Default to `verify=True`.
6. **No tunnel URLs or PATs.** Only gateway base URL + bearer token.
7. **Aggressive .gitignore** — `.env` is already git-ignored; no changes needed.

## Future Security Improvements

1. Mutual TLS between laptop and gateway.
2. Short-lived OAuth tokens instead of static bearer tokens.
3. Per-operation rate limiting.
4. Request signing (HMAC) for integrity.
5. Webhook-based audit notifications.
6. Cluster credential rotation automation.
7. Policy-as-code for operation allowlists (e.g., OPA/Rego).
