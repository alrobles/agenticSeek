---
name: testing-agenticplug-integration
description: Test AgenticPlug + AgenticSeek integration end-to-end using mock gateway. Use when verifying security architecture, session handling, provider wiring, or UX store changes.
---

# Testing AgenticPlug Integration

## Prerequisites

1. Clone both repos side-by-side:
   - `alrobles/agenticplug` (Node.js broker)
   - `alrobles/agenticSeek` (Python client)

2. agenticplug setup:
   ```bash
   cd agenticplug && npm install
   ```

3. agenticSeek setup:
   ```bash
   cd agenticSeek
   python -m venv .venv
   source .venv/bin/activate
   pip install pytest requests pydantic openai httpx ollama colorama termcolor python-dotenv
   ```
   Note: The full `requirements.txt` has heavy deps (torch, transformers). For testing only the AgenticPlug integration, the minimal deps above suffice.

## Test Commands

### agenticplug — Mock Gateway Security (86 assertions)
```bash
cd agenticplug && node --test test/mock-gateway-security.test.js
```
Expect: `86 passed, 0 failed`

### agenticplug — Baseline Regression (9 files)
```bash
for f in test/broker.test.js test/cli-handshake.test.js test/device-flow.test.js test/cli.test.js test/relay.test.js test/native-contract.test.js test/e2e-demo.test.js test/connector.test.js test/registry.test.js; do
  node --test "$f"
done
```
Expect: All files `# fail 0`. Note: `npm test` may hang on rate-limiting tests — run files individually.

### agenticSeek — Gateway Smoke (21 tests)
```bash
cd agenticSeek && source .venv/bin/activate
python -m pytest tests/test_agenticplug_gateway_smoke.py -v
```
Expect: `21 passed`

### agenticSeek — Existing Provider + Session (24 tests)
```bash
python -m pytest tests/test_agenticplug_provider.py tests/test_agenticplug_session.py -v
```
Expect: `24 passed`

## Key Security Properties to Verify

- GitHub identity produces opaque AgenticPlug session (never raw `gho_`/`ghp_` tokens as bearer)
- Session lifecycle: creation, expiry, revocation, malformed rejection
- Role-based auth: lower roles cannot escalate
- Approval gates: write ops require explicit approval
- Backend isolation: safe commands only, arbitrary shell denied
- Connector fail-closed: offline/missing/misconfigured connectors rejected
- Command injection & path traversal rejected
- Audit logs redact secrets
- Discovery doc exposes no secrets

## Known Gotchas

- `npm test` in agenticplug may hang on the rate-limiting test after ~120s. Workaround: run individual test files.
- The approval endpoint is a 501 placeholder — approve→execute→verify flow cannot be tested yet.
- Path traversal in `hpc.logs.read` only checks `startsWith('/')` — `..` normalization is not implemented.
- `TestProviderWithMockGateway` patches OpenAI at the boundary (unit test isolation), does not make real HTTP calls to mock gateway.

## No Devin Secrets Needed

All tests use mock backends and fake tokens. No real credentials required.
