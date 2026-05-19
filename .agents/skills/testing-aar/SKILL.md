---
name: testing-aar
description: Test the AAR (Adaptive Agentic Retrieval) pipeline end-to-end. Use when verifying AAR modules, orchestrator flow, or judge integration changes.
---

# Testing the AAR Pipeline

## Prerequisites

- Python 3.10+ with venv
- Minimal deps: `pydantic`, `pytest`, `requests` (full `requirements.txt` not needed for AAR-only tests)
- Branch: `main` (AAR merged via PR #37)

## Environment Setup

```bash
cd /home/ubuntu/repos/agenticSeek
python3 -m venv .venv
source .venv/bin/activate
pip install pydantic pytest requests
```

Note: The full `requirements.txt` includes many native extensions (pyaudio, etc.) that take 5+ minutes to build. For AAR-only testing, the three packages above are sufficient.

## Running Unit Tests

```bash
source .venv/bin/activate
python -m pytest tests/test_aar_core.py -v
```

Expected: 25 tests, all passing. Covers AARTracker (8), IntentDecomposer (3), QualityAssessor (2), DecisionGate (4), RetrievalRouter (2), Synthesizer (1), Orchestrator (3), NemotronProvider (2).

## Adversarial Test Scenarios

When testing AAR changes, cover these adversarial scenarios beyond the unit tests:

### Feature Flag
- `ECOSEEK_AAR_ENABLED` defaults to disabled (unset or "false")
- Case-insensitive: `true`, `True`, `TRUE`, `1`, `yes` all enable
- Values like `false`, `0`, `no`, empty string, random text all disable

### Decision Gate (pure Python, no LLM)
- SUFFICIENT verdict → PROCEED with empty reformulated_query
- INSUFFICIENT at cycle < max → RETRY with reformulation suffix
- INSUFFICIENT at cycle == max → EXHAUSTED
- CONTRADICTORY → FLAG
- Reformulation suffixes differ per cycle (peer-reviewed → post-2018 → quantitative)

### Quality Assessor
- Valid JSON parsed correctly (verdict, scores, source_type)
- Garbage LLM output → fallback INSUFFICIENT with 0.0 score (no exception raised)
- Scores outside [0,1] → clamped (e.g., 1.5→1.0, -0.3→0.0)
- Invalid verdict (e.g., "MAYBE") → rejected by Pydantic → retries → fallback

### Intent Decomposer
- Valid JSON with 2-5 sub-questions parsed correctly
- Invalid search_strategy (e.g., "magic") → rejected → fallback single sub-question
- Garbage LLM → fallback single sub-question (original query, strategy=literature, priority=high)

### Orchestrator Integration (use separate `judge_call` from `llm_call`)
- **Happy path:** mock judge returns SUFFICIENT → 1 cycle per SQ → synthesis with citations
- **Retry path:** mock judge returns INSUFFICIENT then SUFFICIENT → 2 cycles for that SQ
- **Exhaustion:** mock judge always INSUFFICIENT → cycles == max_cycles, last gate=EXHAUSTED, synthesis still produced
- **Exception:** mock LLM raises RuntimeError → fallback_used=True, error captured, no synthesis

**Important:** When testing the orchestrator, pass a separate `judge_call` parameter. If you only pass `llm_call`, the orchestrator uses it for BOTH decomposition AND assessment, making mocks hard to distinguish.

### Synthesis
- `_parse_synthesis` extracts JSON from code fences (```json ... ```)
- `_parse_synthesis` with plain text returns fallback dict (answer=text, confidence=0.5)

## Real Integration Testing (requires API key)

To test with a real LLM provider, you need a DeepSeek API key.

### Devin Secrets Needed
- `DEEPSEEK_API_KEY` — for real LLM integration testing
- `PHOENIX_ENDPOINT` (optional) — for verifying Phoenix trace creation

### Steps
1. Start the FastAPI backend with `ECOSEEK_AAR_ENABLED=true`
2. Send a regular `/query` first to initialize `current_agent` (the `/aar/query` endpoint requires an initialized agent)
3. `POST /aar/query` with a real ecological question
4. Verify response contains `sub_questions`, `synthesis.answer` with `[n]` citations, `synthesis.citations` array

## Known Issues / Warnings

- **Pydantic V1 deprecation warnings (18):** Uses `parse_raw` and `@validator` deprecated in Pydantic V2. Not blocking. Migration to `model_validate_json` / `@field_validator` is recommended.
- **`/aar/query` requires prior `/query` call:** `interaction.current_agent` is None until a regular query initializes the agent. Calling `/aar/query` first returns 500.
- **Blocking sync in async endpoint:** The `/aar/query` handler runs synchronous LLM calls inside an async def. Acceptable for single-user local use, but will block the event loop for concurrent requests.
- **Tool call adapter is a stub:** The `tool_call` closure in `api.py` tries `agent.browser.search(query)` which may not match BrowserAgent's actual API. On failure it silently returns placeholder text.
