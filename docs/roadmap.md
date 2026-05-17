# Implementation Roadmap

## Issue: [#1 — Design local AgenticSeek client for secure remote KU HPC control via agenticplug](https://github.com/alrobles/agenticSeek/issues/1)

## Acceptance Criteria

### Must Have (PoC)

- [x] AgenticSeek can run locally on a laptop.
- [ ] AgenticSeek can authenticate to agenticplug without embedding secrets in the repo.
- [ ] AgenticSeek can request safe remote operations (`job_status`, `list_jobs`) through the gateway.
- [ ] Every request is logged/auditable.
- [ ] No raw shell/file endpoint is exposed to the laptop.
- [ ] A GitHub issue/PR can be used as durable handoff for larger work.

## Phases

### Phase 0: Documentation & Scaffolding (CURRENT PR)

**Goal:** Establish architecture, security model, and project structure without unsafe code.

**Deliverables:**
- [x] `docs/local-agenticseek-to-cluster.md` — Architecture document
- [x] `docs/agenticplug-connector-design.md` — Connector design
- [x] `docs/ku-hpc-slurm-operations.md` — Slurm operations reference
- [x] `docs/security-model.md` — Security model + threat model
- [x] `docs/roadmap.md` — This file
- [x] `.env.example` — Connector configuration variables
- [x] `sources/tools/agenticplug_connector.py` — Minimal read-only connector skeleton
- [x] `sources/tools/__init__.py` — Updated with connector import

**PoC Verification:**
- Connector imports cleanly without secrets.
- Environment variable loading works.
- Operation allowlist validation works locally.
- No network calls made without explicit user configuration.

### Phase 1: Gateway Integration (Next)

**Goal:** End-to-end read-only cluster status.

**Tasks:**
1. Deploy agenticplug gateway with `/cluster/jobs/status` and `/cluster/jobs/list` endpoints.
2. Configure reumanlab SSH access for agenticplug.
3. Configure OAuth/OIDC on agenticplug (Cloudflare Access or similar).
4. Test: AgenticSeek → agenticplug → reumanlab → squeue/sacct → JSON response.
5. Verify audit logging works end-to-end.
6. Test: AgenticSeek → agenticplug → reumanlab → sacct → JSON for `job_status`.

### Phase 2: Write Operations

**Goal:** Submit and cancel Slurm jobs through the gateway.

**Tasks:**
1. Add `submit_job` and `cancel_job` to the operation allowlist.
2. Implement job script validation on the gateway (pre-approved templates).
3. Add `AGENTICPLUG_WRITE_ENABLED` feature flag (off by default).
4. Implement `sbatch` and `scancel` wrappers on reumanlab.
5. Add dual authorization requirement for write operations.

### Phase 3: GitHub Handoff

**Goal:** Durable task lifecycle via GitHub issues/PRs.

**Tasks:**
1. Implement `open_pr_for_result` operation.
2. Implement `sync_repo` operation.
3. Set up GitHub App for agenticplug with fine-grained permissions.
4. AgenticSeek can request work by creating/updating GitHub issues.
5. Cluster results auto-open PRs with output artifacts.

### Phase 4: Production Hardening

**Task:**
1. Mutual TLS between laptop and gateway.
2. Short-lived OAuth tokens with refresh flow.
3. Policy-as-code for operation allowlists (OPA/Rego).
4. Rate limiting per principal.
5. Request signing (HMAC).
6. Centralized audit log shipping.
7. Multi-platform support (Linux, macOS, Windows/WSL).

## Open Questions (from issue)

| Question | Current Thinking | Decision Needed By |
|----------|-----------------|-------------------|
| Tool vs Provider vs MCP adapter? | Tool (simplest, follows existing patterns) | Phase 1 |
| reumanlab direct vs agenticplug-owned service? | agenticplug proxies; reumanlab executes | Phase 0 (decided) |
| Auth path: Cloudflare Access, GitHub App, or Tailscale? | Cloudflare Access + service tokens initially | Phase 1 |
| Local OS priority? | Linux first (matches reumanlab/KU HPC environment) | Phase 0 (decided) |

## Success Metrics

- **PoC:** `list_jobs` round-trip < 5 seconds end-to-end.
- **Phase 1:** All read-only operations work with < 1% error rate.
- **Phase 2:** Write operations require explicit authorization, zero unauthorized writes.
- **Phase 3:** GitHub issue → cluster job → PR workflow completes without manual steps.
- **Phase 4:** Audit coverage 100% for all gateway requests.
