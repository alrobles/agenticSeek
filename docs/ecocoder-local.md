# EcoCoder Local Provider

EcoCoder is a domain-adapted code LLM fine-tuned on ~80K lines of ecological
computing code (R, Python, C++) from the Reuman Lab ecosystem.  It is served
locally through [Ollama](https://ollama.com/) and integrated into EcoSeek as
the `ecocoder_local` provider.

> EcoSeek is built on a fork of AgenticSeek.  We gratefully acknowledge the
> AgenticSeek project and contributors as the foundation for this work.
> EcoSeek is an independent downstream adaptation focused on scientific and
> ecological computing.

## Prerequisites

| Requirement | Minimum | Notes |
|---|---|---|
| Ollama | v0.3+ | `ollama --version` to check |
| RAM | 8 GB | 16 GB recommended for 7B model |
| GPU (optional) | 6 GB VRAM | NVIDIA or Apple Silicon; CPU-only works but slower |
| Disk | ~5 GB | For model weights |

## Quick Start

### 1. Install Ollama

```bash
# Linux / WSL
curl -fsSL https://ollama.com/install.sh | sh

# macOS
brew install ollama

# Or download from https://ollama.com/download
```

### 2. Start the Ollama Server

```bash
ollama serve
# Listens on http://127.0.0.1:11434 by default
```

### 3. Register the EcoCoder Model

**Option A — Pull from Ollama registry** (when published):

```bash
ollama pull ecocoder
```

**Option B — Register from a local GGUF export**:

Create a `Modelfile`:

```
FROM ./ecocoder-7b-q4_K_M.gguf

PARAMETER temperature 0.2
PARAMETER top_p 0.9
PARAMETER num_predict 1024

SYSTEM "You are EcoCoder, a domain-adapted code assistant specialized in ecological and computational biology. You generate R, Python, and C++ code for species distribution modeling, biodiversity metrics, population dynamics, and related scientific computing tasks."
```

Then register:

```bash
ollama create ecocoder -f Modelfile
```

**Option C — Use the ecocoder Python helper** (from the `alrobles/ecocoder` repo):

```python
from ecocoder.serve import register_model
register_model("path/to/Modelfile", model_name="ecocoder")
```

### 4. Verify the Model

```bash
ollama list
# Should show: ecocoder    ...

ollama run ecocoder "Write an R function for Shannon diversity index"
```

### 5. Configure EcoSeek

Edit `config.ini`:

```ini
[MAIN]
is_local = True
provider_name = ecocoder_local
provider_model = ecocoder
provider_server_address = 127.0.0.1:11434
```

### 6. Run EcoSeek

```bash
python main.py
```

## Using EcoCoder on KU HPC

If you have access to KU HPC GPU nodes, EcoCoder can run on cluster hardware
via Ollama inside an Apptainer container, with SSH tunnel back to your
workstation.  See the `alrobles/knowledgebase` repo at
`hpc-scripts/ollama/README.md` for SLURM scripts and setup instructions.

Typical workflow:

```bash
# On HPC: submit Ollama job
sbatch launch_ollama_deepseek.slurm

# On workstation: tunnel to the Ollama port
ssh -N -L 11434:<hpc-node>:<port> user@hpc.crc.ku.edu &

# Then configure EcoSeek to point at localhost:11434
```

## Model Details

| Property | Value |
|---|---|
| Base model | Qwen2.5-Coder-7B-Instruct |
| Fine-tuning | QLoRA (rank 32, alpha 64) |
| Training data | ~80K lines ecological computing code |
| Languages | R, Python, C++ |
| Domains | SDM, biodiversity metrics, population dynamics, Rcpp bridges |
| Ollama model name | `ecocoder` |

## Supported Model Names

The `ecocoder_local` provider accepts these model names in `config.ini`:

- `ecocoder` (recommended)
- `ecocoder:latest`
- `ecocoder:7b`

If `provider_model` is set to a generic name like `deepseek-r1:14b` or
`deepseek-chat`, the provider automatically resolves it to `ecocoder`.

## API Compatibility

EcoCoder through Ollama exposes two APIs:

- **Native Ollama**: `http://localhost:11434/api/generate`
- **OpenAI-compatible**: `http://localhost:11434/v1/chat/completions`

The `ecocoder_local` provider uses the native Ollama client library.

## Troubleshooting

### "Ollama connection failed"

Ollama is not running.  Start it:

```bash
ollama serve
```

### "EcoCoder model not found in Ollama"

The model is not registered.  Pull or create it:

```bash
ollama pull ecocoder
# or
ollama create ecocoder -f Modelfile
```

### "Ollama connection refused"

The server address in `config.ini` does not match where Ollama is listening.
Check `provider_server_address` matches `ollama serve` output.

### Slow inference without GPU

EcoCoder 7B runs on CPU but is significantly slower (~10-30x).  For
acceptable latency, use a GPU with at least 6 GB VRAM, or use a quantized
variant (`q4_K_M`).

## Product Mode

EcoCoder local is part of the **DIY / Community** product mode:

- Free, reproducible, open scientific path
- No API keys required
- No data sent to external services
- Full control over model and inference

For stronger reasoning without local hardware, see the
[DeepSeek BYOK](deepseek-byok.md) provider.  For cluster-hosted inference,
see EcoCoder cluster provider (Phase 3C).
