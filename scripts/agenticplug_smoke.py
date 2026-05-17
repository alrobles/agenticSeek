#!/usr/bin/env python3
"""Read-only AgenticPlug smoke test.

Confirms that AgenticSeek can use an existing AgenticPlug session (created by
``agenticplug login``) to:

1. Resolve the local session file and print the authenticated identity.
2. List the clusters/connectors exposed by the gateway.
3. Issue ONE read-only directory listing against the configured cluster.

The script never writes, submits, or cancels anything. Any write operation
must go through the AgenticPlug approval UX, which lives outside this script.

The ``--path`` argument is required so we never list a directory the
operator didn't explicitly ask for. See ``docs/agenticplug_device_flow.md``
for example invocations (including the KU-HPC home-directory smoke).

Exit codes:
    0 — all three steps succeeded.
    2 — no session file (user needs to run `agenticplug login`).
    3 — session present but gateway rejected it (re-login or check VPN).
    4 — gateway reachable but a smoke step returned an unexpected response.
    1 — anything else (network, JSON, etc.).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Allow running as `python scripts/agenticplug_smoke.py` from the repo root.
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import requests

from sources.agenticplug_session import (
    AgenticPlugSession,
    AgenticPlugSessionError,
    LOGIN_HINT,
    load_session,
)


DEFAULT_HEAD_LINES = 50

# Header names we never want to print back to the user, in any output mode.
_REDACTED_HEADERS = {"authorization", "x-amz-security-token"}
# JSON-output keys whose values are tokens/credentials and must be redacted.
_REDACTED_FIELDS = {"token", "access_token", "refresh_token", "id_token", "authorization"}
_REDACTED_PLACEHOLDER = "***redacted***"


def _redact(value):
    """Recursively replace credential-shaped fields with a placeholder.

    Defense in depth — the smoke script's JSON mode is meant to land in CI logs
    and the user's clipboard. The session token never needs to appear there,
    and gateway-side ``user`` records sometimes include extras like
    ``access_token`` we'd rather not echo either.
    """
    if isinstance(value, dict):
        return {
            k: _REDACTED_PLACEHOLDER if k.lower() in _REDACTED_FIELDS else _redact(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _headers(session: AgenticPlugSession) -> Dict[str, str]:
    headers = {"Accept": "application/json"}
    auth = session.authorization_header()
    if auth:
        headers["Authorization"] = auth
    if session.route_header:
        headers["X-AgenticPlug-Route"] = session.route_header
    return headers


def _gateway_root(session: AgenticPlugSession) -> str:
    """Strip a trailing ``/v1`` so we can hit gateway-level endpoints."""
    base = (session.base_url or "").rstrip("/")
    if base.endswith("/v1"):
        base = base[: -len("/v1")]
    return base


def whoami(session: AgenticPlugSession, timeout: float = 10.0) -> Dict[str, Any]:
    """Confirm authenticated identity.

    Prefers the gateway's own ``/whoami`` (so we exercise auth end-to-end),
    falls back to the locally-cached ``user`` block in the session file.
    """
    root = _gateway_root(session)
    if root:
        url = f"{root}/whoami"
        try:
            resp = requests.get(url, headers=_headers(session), timeout=timeout)
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code in (401, 403):
                raise SystemExit(
                    f"whoami: gateway rejected the session ({resp.status_code}). {LOGIN_HINT}"
                )
        except requests.RequestException as exc:
            print(f"whoami: gateway unreachable ({exc}); using cached session identity.", file=sys.stderr)
    if not session.user:
        raise SystemExit(
            "whoami: session file has no user record and gateway is unreachable. "
            f"{LOGIN_HINT}"
        )
    return session.user


def list_clusters(session: AgenticPlugSession, timeout: float = 10.0) -> List[Dict[str, Any]]:
    """List clusters/connectors visible to the authenticated session."""
    root = _gateway_root(session)
    if not root:
        raise SystemExit("list_clusters: session has no base_url; cannot reach gateway.")
    resp = requests.get(f"{root}/clusters", headers=_headers(session), timeout=timeout)
    if resp.status_code in (401, 403):
        raise SystemExit(
            f"list_clusters: gateway rejected the session ({resp.status_code}). {LOGIN_HINT}"
        )
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, dict) and "clusters" in data:
        return data["clusters"]
    if isinstance(data, list):
        return data
    raise SystemExit(f"list_clusters: unexpected response shape: {data!r}")


def read_only_ls(
    session: AgenticPlugSession,
    cluster: str,
    path: str,
    head_lines: int,
    timeout: float = 30.0,
) -> Dict[str, Any]:
    """Issue ONE read-only directory listing.

    Uses a dedicated ``/clusters/{cluster}/ls`` endpoint on the gateway. The
    gateway is responsible for enforcing that this is read-only; the client
    never sends an exec-arbitrary-command payload from this script.
    """
    root = _gateway_root(session)
    url = f"{root}/clusters/{cluster}/ls"
    body = {"path": path, "limit": head_lines}
    resp = requests.post(url, headers=_headers(session), json=body, timeout=timeout)
    if resp.status_code in (401, 403):
        raise SystemExit(
            f"ls: gateway rejected the session ({resp.status_code}). {LOGIN_HINT}"
        )
    if resp.status_code == 404:
        raise SystemExit(
            f"ls: cluster {cluster!r} or read-only ls endpoint not found at {url}."
        )
    resp.raise_for_status()
    return resp.json()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only AgenticPlug smoke test (identity, clusters, ls).",
    )
    parser.add_argument(
        "--session",
        help="Path to AgenticPlug session.json. Defaults to "
             "$AGENTICPLUG_SESSION_FILE or ~/.config/agenticplug/session.json.",
    )
    parser.add_argument(
        "--cluster",
        help="Cluster name to list against. Defaults to the session's "
             "default_cluster, then falls back to 'ku-hpc'.",
    )
    parser.add_argument(
        "--path",
        required=True,
        help="Absolute directory path to list on the cluster (read-only). "
             "Pass an account-scoped path you own — examples in "
             "docs/agenticplug_device_flow.md.",
    )
    parser.add_argument(
        "--head",
        type=int,
        default=DEFAULT_HEAD_LINES,
        help=f"Max lines to request (default: {DEFAULT_HEAD_LINES}).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of human text.",
    )
    args = parser.parse_args(argv)

    try:
        session = load_session(Path(args.session)) if args.session else load_session()
    except AgenticPlugSessionError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if session.is_expired():
        print(
            f"Session at {session.path} expired at {session.expires_at}. {LOGIN_HINT}",
            file=sys.stderr,
        )
        return 3

    cluster = args.cluster or session.default_cluster or "ku-hpc"

    try:
        identity = whoami(session)
        clusters = list_clusters(session)
        listing = read_only_ls(session, cluster, args.path, args.head)
    except SystemExit:
        raise
    except requests.HTTPError as exc:
        print(f"smoke: HTTP error: {exc}", file=sys.stderr)
        return 4
    except requests.RequestException as exc:
        print(f"smoke: network error: {exc}", file=sys.stderr)
        return 1

    result = {
        "session_path": str(session.path),
        "base_url": session.base_url,
        "identity": identity,
        "clusters": clusters,
        "ls": {"cluster": cluster, "path": args.path, "result": listing},
    }

    if args.json:
        print(json.dumps(_redact(result), indent=2, default=str))
        return 0

    login = identity.get("login") if isinstance(identity, dict) else identity
    print(f"identity: {login}")
    print(f"session:  {session.path}")
    print(f"gateway:  {session.base_url}")
    print(f"clusters: {[c.get('name', c) if isinstance(c, dict) else c for c in clusters]}")
    print(f"ls {args.path} on {cluster}:")
    entries = listing.get("entries") if isinstance(listing, dict) else None
    if isinstance(entries, list):
        for entry in entries[: args.head]:
            print(f"  {entry}")
    else:
        print(f"  {listing}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
