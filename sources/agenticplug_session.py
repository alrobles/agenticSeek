"""AgenticPlug session-file loader.

Reads the session JSON produced by ``agenticplug login`` (GitHub Device Flow).
The session lives outside this repository — by default at
``~/.config/agenticplug/session.json`` — and is owned and rotated by the
AgenticPlug CLI. AgenticSeek only consumes it as a client.

The loader is intentionally small and dependency-free. It does not perform
auth, refresh tokens, or talk to the gateway; higher layers do that. It only
resolves the file path and parses the JSON into a typed view that the
provider/smoke flow can use.

Schema (fields treated as optional unless noted):

    {
      "base_url":       "https://<host>/v1",   # required for use
      "token":          "<bearer>",            # required for authenticated calls
      "token_type":     "Bearer",
      "expires_at":     "2026-05-17T20:00:00Z",
      "user": {"login": "octocat", "id": 1, "name": "..."},
      "scopes":         ["read:user", "read:org"],
      "route_header":   "hermes",
      "model":          "hermes",
      "default_cluster":"ku-hpc"
    }

Unknown fields are preserved on the returned object so future server-side
additions don't break older clients.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


DEFAULT_SESSION_ENV = "AGENTICPLUG_SESSION_FILE"
DEFAULT_SESSION_RELATIVE = Path(".config") / "agenticplug" / "session.json"

LOGIN_HINT = (
    "Run `agenticplug login` to create a session, then `agenticplug whoami` "
    "to confirm it. See docs/agenticplug_device_flow.md for setup."
)


class AgenticPlugSessionError(Exception):
    """Raised when a session file is missing, unreadable, or invalid."""


@dataclass
class AgenticPlugSession:
    """Parsed view of ``~/.config/agenticplug/session.json``."""

    path: Path
    base_url: Optional[str] = None
    token: Optional[str] = None
    token_type: str = "Bearer"
    expires_at: Optional[str] = None
    user: Dict[str, Any] = field(default_factory=dict)
    scopes: List[str] = field(default_factory=list)
    route_header: Optional[str] = None
    model: Optional[str] = None
    default_cluster: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def identity(self) -> Optional[str]:
        """Best-effort human-readable identity (GitHub login)."""
        if not isinstance(self.user, dict):
            return None
        return self.user.get("login") or self.user.get("name") or self.user.get("id")

    def is_expired(self, now: Optional[datetime] = None) -> bool:
        """True if ``expires_at`` is set and in the past.

        Sessions without an ``expires_at`` are treated as non-expiring from
        AgenticSeek's point of view — the gateway is still authoritative.
        """
        if not self.expires_at:
            return False
        try:
            ts = self.expires_at
            if ts.endswith("Z"):
                ts = ts[:-1] + "+00:00"
            exp = datetime.fromisoformat(ts)
        except ValueError:
            return False
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        current = now or datetime.now(timezone.utc)
        return exp <= current

    def authorization_header(self) -> Optional[str]:
        if not self.token:
            return None
        return f"{self.token_type or 'Bearer'} {self.token}"


def default_session_path() -> Path:
    """Resolve the session path, honoring ``AGENTICPLUG_SESSION_FILE``."""
    override = os.environ.get(DEFAULT_SESSION_ENV)
    if override:
        return Path(override).expanduser()
    return Path.home() / DEFAULT_SESSION_RELATIVE


def load_session(path: Optional[Path] = None) -> AgenticPlugSession:
    """Load and parse the AgenticPlug session file.

    Raises ``AgenticPlugSessionError`` with an actionable hint on any failure
    (missing file, bad JSON, wrong shape). Callers can catch and surface the
    message verbatim — it already tells the user what to run.
    """
    resolved = Path(path).expanduser() if path else default_session_path()
    if not resolved.exists():
        raise AgenticPlugSessionError(
            f"AgenticPlug session not found at {resolved}. {LOGIN_HINT}"
        )
    try:
        data = json.loads(resolved.read_text())
    except json.JSONDecodeError as exc:
        raise AgenticPlugSessionError(
            f"AgenticPlug session at {resolved} is not valid JSON: {exc}. {LOGIN_HINT}"
        ) from exc
    except OSError as exc:
        raise AgenticPlugSessionError(
            f"Cannot read AgenticPlug session at {resolved}: {exc}. {LOGIN_HINT}"
        ) from exc

    if not isinstance(data, dict):
        raise AgenticPlugSessionError(
            f"AgenticPlug session at {resolved} must be a JSON object. {LOGIN_HINT}"
        )

    scopes = data.get("scopes") or []
    if not isinstance(scopes, list):
        scopes = []

    user = data.get("user") or {}
    if not isinstance(user, dict):
        user = {}

    return AgenticPlugSession(
        path=resolved,
        base_url=data.get("base_url"),
        token=data.get("token"),
        token_type=data.get("token_type") or "Bearer",
        expires_at=data.get("expires_at"),
        user=user,
        scopes=scopes,
        route_header=data.get("route_header"),
        model=data.get("model"),
        default_cluster=data.get("default_cluster"),
        raw=data,
    )


def load_session_or_none(path: Optional[Path] = None) -> Optional[AgenticPlugSession]:
    """Same as ``load_session`` but returns ``None`` when the file is absent.

    Other ``AgenticPlugSessionError`` cases (malformed JSON, unreadable file)
    are still raised — those should not be silently ignored.
    """
    try:
        return load_session(path)
    except AgenticPlugSessionError as exc:
        if "not found" in str(exc):
            return None
        raise
