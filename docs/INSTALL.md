# EcoSeek Installation and Quick-Start Guide

This guide covers installing and running EcoSeek in all three product modes.
Pick the mode that fits your hardware and workflow, or try them in order.

> EcoSeek is built on a fork of AgenticSeek. We gratefully acknowledge the
> AgenticSeek project and contributors as the foundation for this work.
> EcoSeek is an independent downstream adaptation focused on scientific and
> ecological computing.

## Architecture Overview

```text
EcoSeek client  ──>  AgenticPlug gateway  ──>  Compute backends
(this repo)          (auth, sessions,          (EcoCoder, EcoAgent,
                      policy, audit)            DeepSeek BYOK, HPC)
```

| Mode | What You Need | Data Leaves Your Machine? |
|------|---------------|--------------------------|
| **DIY / Community** | Python 3.10, Ollama, Docker | No |
| **BYOK (DeepSeek)** | Python 3.10, Docker, DeepSeek API key | Yes (to DeepSeek API) |
| **Lab / Cluster** | Python 3.10, Docker, AgenticPlug gateway | Yes (to your gateway) |

---

## Prerequisites (All Modes)

### Required Software

| Software | Version | Purpose |
|----------|---------|---------|
| [Python](https://www.python.org/downloads/) | 3.10.x | Runtime (3.10 strongly recommended) |
| [Git](https://git-scm.com/downloads) | any | Clone the repository |
| [Docker](https://docs.docker.com/get-docker/) | 20+ | SearxNG search engine, optional full-stack |
| [Docker Compose](https://docs.docker.com/compose/install/) | V2 | Service orchestration |

### Clone and Configure

```bash
git clone https://github.com/alrobles/agenticSeek.git
cd agenticSeek
cp .env.example .env
pip install -r requirements.txt
```

Edit `.env` and set at minimum:

```ini
WORK_DIR="/path/to/your/workspace"
SEARXNG_BASE_URL="http://searxng:8080"
REDIS_BASE_URL="redis://redis:6379/0"
```

`WORK_DIR` is the directory EcoSeek can read and write files in. Choose a
directory you are comfortable giving the agent access to.

---

## Mode 1: DIY / Community (Local)

Run everything on your own hardware. No API keys, no cloud, fully private.

### Hardware Requirements

A GPU capable of running 7B-14B parameter models. See the
upstream AgenticSeek README (in this repo) for hardware recommendations.

### Step 1: Install and Start Ollama

```bash
# Install Ollama (macOS/Linux)
curl -fsSL https://ollama.ai/install.sh | sh

# Pull a model (pick one that fits your GPU)
ollama pull deepseek-r1:14b

# Start serving (bind to all interfaces for Docker access)
export OLLAMA_HOST=0.0.0.0:11434
ollama serve
```

### Step 2: Configure EcoSeek

Edit `config.ini`:

```ini
[MAIN]
is_local = True
provider_name = ollama
provider_model = deepseek-r1:14b
provider_server_address = 127.0.0.1:11434
agent_name = EcoSeek
recover_last_session = False
save_session = False
speak = False
listen = False
jarvis_personality = False
languages = en

[BROWSER]
headless_browser = True
stealth_mode = False
```

### Step 3: Start Services and Run

**Option A: Docker (recommended)**

```bash
./start_services.sh full    # macOS/Linux
start start_services.cmd full  # Windows
```

Then open `http://localhost:3000/` in your browser.

**Option B: CLI mode**

```bash
# Start search engine only
./start_services.sh         # macOS/Linux

# Run EcoSeek CLI
python cli.py
```

### EcoCoder Variant (Domain-Specialized)

If you have the EcoCoder model registered in Ollama:

```ini
[MAIN]
provider_name = ecocoder_local
provider_model = ecocoder
provider_server_address = 127.0.0.1:11434
```

See [docs/ecocoder-local.md](ecocoder-local.md) for full setup.

---

## Mode 2: BYOK — Bring Your Own DeepSeek Key

Use the DeepSeek API for stronger reasoning without local GPU hardware.
Your API key stays on your machine.

### Step 1: Get a DeepSeek API Key

Sign up at [platform.deepseek.com](https://platform.deepseek.com) and
create an API key.

### Step 2: Store Your Key Securely

```bash
# Recommended: use the secure keystore
python -m sources.keystore set deepseek
# You will be prompted for your key (not echoed)

# Verify it was stored
python -m sources.keystore list
```

The keystore tries OS keychain first (macOS Keychain, GNOME Keyring,
Windows Credential Locker), falling back to an encrypted file at
`~/.config/ecoseek/keys.json`.

**Alternative:** Set `DEEPSEEK_API_KEY` in `.env` (less secure):

```ini
DEEPSEEK_API_KEY='sk-your-key-here'
```

### Step 3: Configure EcoSeek

Edit `config.ini`:

```ini
[MAIN]
is_local = False
provider_name = deepseek_byok
provider_model = deepseek-chat
agent_name = EcoSeek
```

### Step 4: Start Services and Run

Same as Mode 1 — use Docker or CLI:

```bash
./start_services.sh full    # Docker + web UI
# or
python cli.py               # CLI mode (start searxng first)
```

### Key Safety

- Your API key never leaves your machine except in API calls to DeepSeek.
- The keystore never logs, commits, or displays your key.
- Error messages redact the key automatically.
- See [docs/deepseek-byok.md](deepseek-byok.md) for full details.

---

## Mode 3: Lab / Cluster (AgenticPlug)

Connect EcoSeek to remote compute backends (HPC clusters, lab workstations)
through the AgenticPlug secure gateway.

### Prerequisites

- An AgenticPlug gateway running and accessible (see
  [alrobles/agenticplug](https://github.com/alrobles/agenticplug))
- A GitHub account (used for Device Flow authentication)
- A registered connector on the gateway (e.g., `reumanlab`)

### Step 1: Authenticate with the Gateway

```bash
# Install the AgenticPlug CLI (if not already)
cd /path/to/agenticplug
npm install

# Login via GitHub Device Flow
npx agenticplug login

# Verify your identity
npx agenticplug whoami
```

This creates a session file at `~/.config/agenticplug/session.json`.

### Step 2: Discover Available Connectors

```bash
# From the agenticSeek directory
python -c "
from sources.connector_discovery import discover_connectors, print_connector_summary
connectors = discover_connectors()
print_connector_summary(connectors)
"
```

Expected output:

```
Discovered 1 connector(s):
  [OK] reumanlab (hpc) v0.2.0 — tools: github, hpc_read, hpc_submit*
```

Tools marked with `*` require explicit approval before execution.

### Step 3: Configure EcoSeek

**Option A: AgenticPlug provider (generic gateway routing)**

Edit `config.ini`:

```ini
[MAIN]
is_local = False
provider_name = agenticplug
provider_model = hermes
provider_server_address = 127.0.0.1:8080
```

**Option B: EcoCoder cluster (domain-specialized, routed through gateway)**

Edit `config.ini`:

```ini
[MAIN]
is_local = False
provider_name = ecocoder_cluster
provider_model = ecocoder
provider_server_address = 127.0.0.1:8080
```

See [docs/ecocoder-cluster.md](ecocoder-cluster.md) for SSH tunnel setup.

### Step 4: Start Services and Run

Same startup as other modes:

```bash
./start_services.sh full    # Docker + web UI
# or
python cli.py               # CLI mode
```

### Gateway URL Configuration

The client resolves the gateway URL in this order:

| Priority | Source |
|----------|--------|
| 1 | Explicit `gateway_url` argument in code |
| 2 | `AGENTICPLUG_BASE_URL` environment variable |
| 3 | `base_url` from `~/.config/agenticplug/session.json` |
| 4 | Default: `http://127.0.0.1:8080` |

### Security Model

```
GitHub proves who the user is.
AgenticPlug decides what the user can do.
```

- Sessions are scoped to specific connectors and capabilities.
- Write operations (e.g., HPC job submission) require explicit approval.
- All operations are audited.
- See [docs/connector-discovery.md](connector-discovery.md) for the full
  discovery API reference.

---

## Environment Variables Reference

| Variable | Mode | Description |
|----------|------|-------------|
| `WORK_DIR` | All | Directory EcoSeek can read/write files in |
| `SEARXNG_BASE_URL` | All | SearxNG search engine URL |
| `REDIS_BASE_URL` | All | Redis URL (for SearxNG) |
| `OLLAMA_PORT` | DIY | Ollama server port (default: 11434) |
| `DEEPSEEK_API_KEY` | BYOK | DeepSeek API key (prefer keystore instead) |
| `AGENTICPLUG_BASE_URL` | Cluster | AgenticPlug gateway URL |
| `AGENTICPLUG_SESSION_FILE` | Cluster | Override session file path |
| `ECOCODER_CLUSTER_BASE_URL` | Cluster | EcoCoder cluster endpoint |
| `ECOCODER_CLUSTER_MODEL` | Cluster | Override model name |

---

## Provider Summary

| `provider_name` | Mode | Local? | Description |
|------------------|------|--------|-------------|
| `ollama` | DIY | Yes | Local LLM via Ollama |
| `lm-studio` | DIY | Yes | Local LLM via LM Studio |
| `ecocoder_local` | DIY | Yes | EcoCoder ecological model (local Ollama) |
| `deepseek_byok` | BYOK | No | DeepSeek API with secure key storage |
| `deepseek` | BYOK | No | DeepSeek API (env var key) |
| `agenticplug` | Cluster | No | Generic AgenticPlug gateway |
| `ecocoder_cluster` | Cluster | No | EcoCoder via AgenticPlug gateway |
| `openai` | API | No | OpenAI ChatGPT models |
| `google` | API | No | Google Gemini models |
| `anthropic` | API | No | Anthropic Claude models |
| `togetherAI` | API | No | TogetherAI open-source models |
| `openrouter` | API | No | OpenRouter multi-model access |
| `minimax` | API | No | MiniMax models |

---

## Troubleshooting

### Common Issues

**"No work dir specified"**

Set `WORK_DIR` in your `.env` file:

```ini
WORK_DIR="/path/to/your/workspace"
```

**"ModuleNotFoundError: No module named 'X'"**

```bash
pip install -r requirements.txt
```

**Docker services won't start**

```bash
# Verify Docker is running
docker info

# Check compose version (must be V2)
docker compose version

# View logs
docker compose logs
```

**AgenticPlug gateway unreachable**

```bash
# Check if the gateway is running
curl http://127.0.0.1:8080/v1/connectors

# If using SSH tunnel, verify it is active
ssh -N -L 8080:localhost:8080 user@gateway-host
```

**DeepSeek BYOK key not found**

```bash
# Check keystore
python -m sources.keystore list

# Re-store key
python -m sources.keystore set deepseek

# Or set env var
export DEEPSEEK_API_KEY="sk-your-key"
```

**Connector discovery returns empty list**

```bash
# Verify gateway has registered connectors
curl http://127.0.0.1:8080/v1/connectors | python3 -m json.tool

# Check connector health
python -c "
from sources.connector_discovery import check_connector_health
h = check_connector_health('your-connector-id')
print(h.status, h.age_ms)
"
```

### Getting Help

- [GitHub Issues](https://github.com/alrobles/agenticSeek/issues)
- [Upstream AgenticSeek](https://github.com/Fosowl/agenticSeek)
- [AgenticPlug docs](https://github.com/alrobles/agenticplug)

---

## Cross-References

| Document | Description |
|----------|-------------|
| [deepseek-byok.md](deepseek-byok.md) | DeepSeek BYOK provider setup |
| [ecocoder-local.md](ecocoder-local.md) | EcoCoder local provider setup |
| [ecocoder-cluster.md](ecocoder-cluster.md) | EcoCoder cluster provider setup |
| [connector-discovery.md](connector-discovery.md) | Connector discovery client API |
| [security-model.md](security-model.md) | Security architecture |
| [UPSTREAM_CREDITS.md](../UPSTREAM_CREDITS.md) | Attribution and licensing |
| [NOTICE.md](../NOTICE.md) | License posture |
