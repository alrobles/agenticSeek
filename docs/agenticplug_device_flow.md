# AgenticPlug GitHub Device Flow — AgenticSeek Setup

AgenticPlug authenticates users via a **GitHub Device Flow**. The
`agenticplug` CLI handles the browser hand-off and writes a session file to
disk. AgenticSeek then **consumes** that session file — it does not implement
device-flow itself, and it does not duplicate or rewrite any secrets.

This document covers:

- Where the session lives and what AgenticSeek expects of it.
- WSL-specific setup quirks.
- The read-only smoke flow (`scripts/agenticplug_smoke.py`).
- Failure modes and how to recover.

See also: [agenticplug_provider.md](agenticplug_provider.md) for the
OpenAI-compatible chat path, and
[agenticplug_gpl_boundary.md](agenticplug_gpl_boundary.md) for the licensing
boundary between the two projects.

## 1. The session file

After `agenticplug login` succeeds, AgenticPlug writes:

```text
~/.config/agenticplug/session.json
```

AgenticSeek reads this file via `sources/agenticplug_session.py`. The
expected shape is:

```json
{
  "base_url":        "https://<your-gateway>/v1",
  "token":           "<bearer-token>",
  "token_type":      "Bearer",
  "expires_at":      "2026-05-17T20:00:00Z",
  "user":            {"login": "octocat", "id": 1, "name": "..."},
  "scopes":          ["read:user", "read:org"],
  "route_header":    "hermes",
  "model":           "hermes",
  "default_cluster": "ku-hpc"
}
```

Every field is optional from AgenticSeek's point of view *except* `base_url`
and `token` if you intend to talk to a remote gateway. The gateway is
authoritative for token validity; AgenticSeek only checks `expires_at`
locally as a courtesy.

To point AgenticSeek at a session in a non-default location:

```bash
export AGENTICPLUG_SESSION_FILE=/path/to/session.json
```

### Precedence

When `provider_name = agenticplug` is selected in `config.ini`, the
provider resolves its connection settings in this order (highest wins):

1. Environment variables: `AGENTICPLUG_BASE_URL`, `AGENTICPLUG_API_KEY`,
   `AGENTICPLUG_MODEL`, `AGENTICPLUG_ROUTE_HEADER`.
2. The session file (`base_url`, `token`, `model`, `route_header`).
3. `provider_server_address` from `config.ini` (default `127.0.0.1:8080`).

This lets you override individual fields for a single run without editing
the on-disk session.

## 2. WSL setup

WSL2 paths and DNS resolution catch most first-time setups. The key
points:

- **Install `agenticplug` inside WSL**, not on the Windows host. The
  session file must be reachable by AgenticSeek, which runs in WSL.
- **Run `agenticplug login` from the WSL shell.** The CLI will print a
  URL; open it in your Windows browser (the WSL terminal usually
  shells out via `wslview` / `cmd.exe`, but you can copy-paste).
- After login, confirm the session lives at the expected WSL path:
  ```bash
  ls -l ~/.config/agenticplug/session.json
  jq '.user.login, .base_url, .expires_at' ~/.config/agenticplug/session.json
  ```
- **Do not edit the session file by hand.** If it gets corrupted, run
  `agenticplug login` again — it will overwrite cleanly.
- **WSL clock drift** can make `expires_at` look in the past. If
  `whoami` succeeds against the gateway but the smoke script complains
  about expiry, run `sudo hwclock -s` (or restart WSL).
- **No port forwarding required** for the gateway side as long as you
  use a public AgenticPlug URL. If you point at a *local* gateway
  (e.g. `http://127.0.0.1:8080/v1`), make sure it is bound inside the
  same WSL distro.

> **Note on trycloudflare**: AgenticPlug deployments sometimes expose a
> temporary `https://<random>.trycloudflare.com/v1` URL for ad-hoc
> testing. These URLs **rotate** and must not be committed to this repo
> or to `.env`. The smoke script reads the URL from the session file at
> runtime, so a fresh `agenticplug login` is enough to pick up a new
> tunnel.

## 3. Read-only smoke flow

Once `agenticplug login` and `agenticplug whoami` succeed, run:

```bash
python scripts/agenticplug_smoke.py --path /home/<your-account>
```

The script performs three read-only checks:

| Step | Endpoint | Purpose |
|------|----------|---------|
| `whoami`        | `GET /whoami`                          | Confirms the gateway accepts the session and returns the GitHub identity. |
| `list_clusters` | `GET /clusters`                        | Lists clusters/connectors visible to the session. |
| `ls`            | `POST /clusters/{cluster}/ls`          | Read-only directory listing on the chosen cluster. |

`--path` is required so the script never lists a directory the operator
didn't explicitly name. Pass an account-scoped path you own. For the
KU-HPC connector that typically looks like:

```bash
python scripts/agenticplug_smoke.py \
    --cluster ku-hpc \
    --path /home/a474r867 \
    --head 50
```

Add `--json` to emit machine-readable output for CI pipelines. Token /
authorization fields are redacted from JSON output as `***redacted***`.

The script is **strictly read-only**. It does not submit, cancel, or
modify anything. Any write/submit/cancel operation must go through the
AgenticPlug approval UX (see `sources/agenticplug_ux.py`).

### Example: temporary trycloudflare gateway

```bash
# Example only — this URL rotates and MUST NOT be committed.
agenticplug login --gateway https://temporary-example.trycloudflare.com
python scripts/agenticplug_smoke.py
```

## 4. Exit codes and recovery

| Exit | Meaning | Fix |
|------|---------|-----|
| 0    | All three smoke steps passed. | — |
| 1    | Unclassified network error. | Check connectivity, retry. |
| 2    | No session file. | Run `agenticplug login`. |
| 3    | Gateway rejected the session (401/403) or session expired. | Re-run `agenticplug login`; verify VPN/SSO. |
| 4    | Gateway reachable but response was unexpected. | Check gateway logs; the API may have changed. |

If `whoami` works but `ls` fails with 404, the gateway likely does not
have the read-only `ls` endpoint enabled for that cluster. That is a
gateway-side configuration, not an AgenticSeek bug.

## 5. What still requires approval

The smoke flow above is read-only on purpose. The following operations
**must** route through the AgenticPlug approval UX defined in
`sources/agenticplug_ux.py`:

- `sbatch` / `srun` submissions.
- `scancel` and any state-changing job control.
- File writes, file deletes, archive extractions.
- Any command that runs as the user on the remote host with side effects.

`docs/agenticplug_gpl_boundary.md` is the source of truth for *why* the
secrets stay on the AgenticPlug side and never enter this repository.
