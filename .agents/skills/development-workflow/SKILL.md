---
name: ecoseek-development-workflow
description: General development workflow for EcoSeek/agenticSeek — project structure, config.ini, startup, provider options, and test organization. Use when working on any agenticSeek task.
---

# EcoSeek Development Workflow

## Project Identity

This is **EcoSeek** — an independent downstream adaptation of AgenticSeek for scientific/ecological computing. Attribution is required in all user-facing surfaces.

## Setup

```bash
cd /home/ubuntu/repos/agenticSeek
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**Minimal deps** (for testing without heavy ML libs):
```bash
pip install pytest requests pydantic openai httpx ollama colorama termcolor python-dotenv
```

## Pre-commit Hooks

TruffleHog secret scanning is configured in `.pre-commit-config.yaml`:
```bash
pip install pre-commit
pre-commit install
```
Requires `trufflehog` binary installed at `/usr/local/bin/trufflehog`.

## Project Structure

```
sources/
  agents/        # Coder, Browser, Planner, CasualAgent
  tools/         # Bash, Python execution environments
  llm_router/    # Intent classification and task routing
ecoseek/
  aar/           # Adaptive Agentic Retrieval pipeline
  keystore/      # Secure credential management
frontend/        # React web interface
llm_server/      # Remote LLM offloading server
tests/           # 23 test files
config.ini       # Primary configuration
```

## config.ini — Provider Options

| provider_name | provider_model | What it does |
|---------------|---------------|--------------|
| `ollama` | `deepseek-r1:14b` | Local Ollama (default) |
| `agenticplug` | `hermes` | Route through AgenticPlug gateway |
| `deepseek_byok` | `deepseek-chat` | DeepSeek API with user's own key |
| `ecocoder_local` | `ecocoder` | Local EcoCoder model via Ollama |
| `ecocoder_cluster` | `ecocoder` | Remote EcoCoder via AgenticPlug |

## Starting the App

### Backend (FastAPI)
```bash
source .venv/bin/activate
python api.py
# Runs on http://localhost:8000
```

### CLI mode
```bash
source .venv/bin/activate
python cli.py
```

### Frontend (React)
```bash
cd frontend && npm install && npm start
# Runs on http://localhost:3000
```

### Full stack via Docker
```bash
docker compose up --build
```

## Testing

### P0 Security tests (critical — always run)
```bash
python -m pytest tests/test_safety.py tests/test_keystore.py tests/test_tool_save_block_jail.py tests/test_ecoseek_entrypoint.py -v
```

### AgenticPlug integration (21 + 24 tests)
```bash
python -m pytest tests/test_agenticplug_gateway_smoke.py -v
python -m pytest tests/test_agenticplug_provider.py tests/test_agenticplug_session.py tests/test_provider.py -v
```

### AAR pipeline (25 tests)
```bash
python -m pytest tests/test_aar_core.py -v
```

### Full suite
```bash
python -m pytest tests/ -v
```
**Note:** Some tests require heavy deps (torch, transformers). Use minimal deps for targeted testing.

## Key Environment Variables

- `ECOSEEK_AAR_ENABLED` — Enable Adaptive Agentic Retrieval (default: disabled)
- `DEEPSEEK_API_KEY` — For BYOK mode
- `AGENTICPLUG_BROKER_URL` — Gateway broker endpoint
- `PHOENIX_COLLECTOR_ENDPOINT` — Arize Phoenix observability (optional)

## Known Gotchas

- Full `requirements.txt` takes 5+ minutes (pyaudio, torch, transformers native builds)
- `/aar/query` endpoint requires a prior `/query` call to initialize `current_agent`
- `npm test` in companion agenticplug repo may hang on rate-limit tests
- TruffleHog pre-commit hook uses deprecated stage names (warning is non-blocking)
- Docker builds cannot clone private repos — use COPY from local checkout
- The repo is currently PRIVATE (pre-alpha)

## No Lint Command

No dedicated linter is configured. Tests + TruffleHog pre-commit serve as validation.
