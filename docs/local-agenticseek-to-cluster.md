# Local AgenticSeek to Cluster Architecture

## Overview

This document describes how a modified AgenticSeek running on a local laptop acts as the user-facing orchestrator and securely reaches KU HPC through the `agenticplug` gateway and `reumanlab` bastion.

```
Local Laptop                        Cloud/Gateway                  reumanlab                    KU HPC
┌──────────────────┐     HTTPS     ┌─────────────────┐   SSH     ┌──────────────┐   SSH      ┌──────────────┐
│ AgenticSeek UI   │ ────────────> │ agenticplug      │ ────────> │ OpenClaw      │ ────────> │ Slurm        │
│ (orchestrator)   │               │                 │           │ + opencode    │           │ + compute    │
│                  │               │ Auth / Audit /   │           │ + DeepSeek    │           │ + storage    │
│ Connector tool   │               │ Policy / Proxy   │           │ + GitHub CLI  │           │              │
└──────────────────┘               └─────────────────┘           │ + SSH bastion │           └──────────────┘
                                                                 └──────────────┘
```

## Component Roles

### Local Laptop: AgenticSeek (Orchestrator)

- Runs the AgenticSeek UI (web or CLI) locally.
- Hosts a **safe connector tool** (`agenticplug_connector.py`) that calls the agenticplug gateway API.
- Does NOT hold Kubernetes configs, Slurm credentials, or raw SSH keys.
- All secrets are sourced from environment variables; `.env` is git-ignored.
- Only allowlisted operations are available (initially `job_status`, `list_jobs`).

### agenticplug (Secure Gateway)

- Authenticates every request (OAuth/OIDC or service token).
- Maintains an audit log per request.
- Enforces an allowlist of operation names.
- Forwards approved requests to `reumanlab` via SSH or an internal agent.
- Never exposes raw shell or file write endpoints to the laptop.

### reumanlab (Bastion / Implementation Agent)

- Runs OpenClaw + opencode.ai + DeepSeek for code review and implementation.
- Has GitHub CLI for issue/PR management.
- Acts as SSH bastion to KU HPC.
- Receives structured requests from agenticplug and translates them to Slurm commands.

### KU HPC (Compute Backend)

- Runs Slurm workload manager.
- Provides `squeue`, `sacct`, `sbatch`, `scancel` for job management.
- Provides work/scratch storage accessible from login nodes.

## Data Flow: PoC read-only job status

```
1. User asks AgenticSeek: "Show me my queued jobs"
2. AgenticSeek resolves to connector tool: /cluster/jobs/status
3. Connector sends GET to AGENTICPLUG_BASE_URL/cluster/jobs/status
   Headers: Authorization: Bearer <token>, Content-Type: application/json
4. agenticplug validates token, logs request, checks allowlist
5. agenticplug forwards via SSH to reumanlab
6. reumanlab runs: squeue -u <user> --json ; sacct -u <user> --json
7. Response flows back: reumanlab -> agenticplug -> AgenticSeek
8. AgenticSeek displays formatted job list
```

## Security Invariants

- The laptop never touches raw Slurm commands directly.
- The laptop never holds KU HPC SSH keys.
- Every gateway request is authenticated and logged.
- Only read-only operations are available in PoC.
- All secrets are in environment variables, never in code or config files.

## Local Prerequisites

- Python 3.10+
- AgenticSeek installed per README
- `.env` configured with connector variables (see `.env.example`)
- Network access to the agenticplug gateway

## Configuration

```env
AGENTICPLUG_BASE_URL=https://agenticplug.example.com/api/v1
AGENTICPLUG_TOKEN=your-service-token-here
AGENTICPLUG_VERIFY_SSL=true
AGENTICPLUG_TIMEOUT=30
AGENTICPLUG_DEFAULT_USER=your-hpc-username
```

## Next Steps (see roadmap.md)

1. Implement connector skeleton (this PR)
2. Integrate with agenticplug gateway (alrobles/agenticplug)
3. Add write operations (submit, cancel)
4. Add GitHub issue/PR handoff
5. Full end-to-end integration test
