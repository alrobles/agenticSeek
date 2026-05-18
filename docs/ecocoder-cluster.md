# EcoCoder Cluster Provider

EcoCoder cluster routes inference to an EcoCoder model running on a remote
cluster (e.g. KU HPC with Ollama) through the
[AgenticPlug](https://github.com/alrobles/agenticplug) gateway.  It combines
EcoCoder-specific model resolution with the AgenticPlug session/auth layer.

> EcoSeek is built on a fork of AgenticSeek.  We gratefully acknowledge the
> AgenticSeek project and contributors as the foundation for this work.
> EcoSeek is an independent downstream adaptation focused on scientific and
> ecological computing.

## How It Works

```
EcoSeek client
  ecocoder_cluster provider
        |  OpenAI-compatible API
        v
AgenticPlug gateway
  auth, sessions, route header (X-AgenticPlug-Route: ecocoder)
        |
        v  SSH tunnel / relay
Cluster node (KU HPC)
  Ollama serving ecocoder model
```

The provider uses the OpenAI-compatible chat completions endpoint exposed by
the AgenticPlug gateway.  The `X-AgenticPlug-Route` header tells the gateway
to forward the request to the EcoCoder connector on the cluster.

## Prerequisites

| Requirement | Notes |
|---|---|
| AgenticPlug gateway | Running locally or remotely |
| AgenticPlug session | `agenticplug login` to authenticate |
| Cluster with Ollama | EcoCoder model registered (`ollama pull ecocoder`) |
| SSH tunnel (if HPC) | Forwards Ollama port from cluster to gateway |

## Quick Start

### 1. Authenticate with AgenticPlug

```bash
agenticplug login
agenticplug whoami
```

This creates `~/.config/agenticplug/session.json` with your bearer token.

### 2. Start the AgenticPlug Gateway

```bash
cd /path/to/agenticplug
node broker/server.js
# Listens on http://127.0.0.1:8080 by default
```

### 3. Ensure EcoCoder Is Running on the Cluster

For KU HPC:

```bash
# Submit Ollama job on the cluster
sbatch launch_ollama_deepseek.slurm

# Get connection info
cat ~/work/ollama/dpsk-output-<jobid>

# SSH tunnel from gateway host to cluster node
ssh -N -L 11434:<hpc-node>:<port> user@hpc.crc.ku.edu &
```

See `alrobles/knowledgebase` at `hpc-scripts/ollama/README.md` for full
SLURM scripts and setup.

### 4. Configure EcoSeek

Edit `config.ini`:

```ini
[MAIN]
is_local = False
provider_name = ecocoder_cluster
provider_model = ecocoder
provider_server_address = 127.0.0.1:8080
```

### 5. Run EcoSeek

```bash
python main.py
```

## Configuration Precedence

The provider resolves settings in this order (highest first):

| Setting | Env Var | Session Field | Fallback |
|---|---|---|---|
| Base URL | `ECOCODER_CLUSTER_BASE_URL` | `base_url` | `http://<provider_server_address>/v1` |
| API key | `ECOCODER_CLUSTER_API_KEY` | `token` | `not-required` |
| Model | `ECOCODER_CLUSTER_MODEL` | (resolved locally) | `ecocoder` |
| Route | `ECOCODER_CLUSTER_ROUTE` | `route_header` | `ecocoder` |

Environment variables let CI and dev loops override the session without
touching it.

## Model Name Resolution

The provider resolves generic model names to `ecocoder` at call time:

| Config Model | Resolved Model |
|---|---|
| `ecocoder` | `ecocoder` |
| `ecocoder:latest` | `ecocoder:latest` |
| `ecocoder:7b` | `ecocoder:7b` |
| `deepseek-r1:14b` | `ecocoder` |
| `deepseek-chat` | `ecocoder` |
| `deepseek-r1:7b` | `ecocoder` |
| `qwen2.5-coder` | `ecocoder` |
| `qwen2.5-coder:7b` | `ecocoder` |
| `my-custom-model` | `my-custom-model` (warning emitted) |

Unrecognized models proceed with a warning.  They may work if registered in
Ollama on the cluster.

## Security

- **Data leaves the machine**: `ecocoder_cluster` is in the `unsafe_providers`
  list.  A cloud-usage warning is displayed at initialization when
  `is_local = False`.
- **Auth via AgenticPlug**: Bearer token from `agenticplug login` (GitHub
  Device Flow).  Raw GitHub tokens are never sent as bearer.
- **Route header**: `X-AgenticPlug-Route: ecocoder` tells the gateway which
  connector to forward to.  The gateway validates the route against registered
  connectors.
- **Fail-closed**: Auth errors, missing model, and connection failures all
  raise with actionable instructions.

## Troubleshooting

### "EcoCoder cluster auth failed"

Your AgenticPlug session is missing or expired.  Re-authenticate:

```bash
agenticplug login
agenticplug whoami
```

### "EcoCoder model not found on cluster"

The model is not registered in Ollama on the cluster.  SSH to the cluster
and register it:

```bash
ollama pull ecocoder
ollama list  # verify
```

### "Gateway connection failed"

The AgenticPlug gateway is not running or the cluster Ollama instance is
not reachable.  Check:

1. Gateway is running: `curl http://127.0.0.1:8080/health`
2. SSH tunnel is active: `ss -tlnp | grep 11434`
3. Cluster Ollama responds: `curl http://localhost:11434/v1/models`

### "Warning: you are using an API provider"

This is expected.  `ecocoder_cluster` sends data through the AgenticPlug
gateway to the cluster.  If you want local-only inference, use
`ecocoder_local` instead.

## Comparison: Local vs Cluster

| Feature | `ecocoder_local` | `ecocoder_cluster` |
|---|---|---|
| Data stays local | Yes | No (goes to cluster) |
| Requires Ollama locally | Yes | No |
| Requires AgenticPlug | No | Yes |
| Requires cluster access | No | Yes (SSH tunnel) |
| GPU requirements | Local GPU (6+ GB) | Cluster GPU (A100, V100) |
| Unsafe provider | No | Yes |
| Product mode | DIY / Community | Lab / Managed |

## Product Mode

EcoCoder cluster is part of the **Lab / Managed** product mode:

- Institutional clusters, lab workstations, HPC nodes
- AgenticPlug gateway for auth, sessions, policy, audit
- SSH tunnel for secure cluster access
- Higher GPU capacity (A100, V100, MI210)

For local inference, see [EcoCoder Local](ecocoder-local.md).
For cloud reasoning, see [DeepSeek BYOK](deepseek-byok.md).
