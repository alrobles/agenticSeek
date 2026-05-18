"""AgenticPlug connector discovery client.

Queries the AgenticPlug gateway's ``GET /v1/connectors`` endpoint to
enumerate registered connectors, their capabilities, tool metadata, risk
levels, and health status.  This lets the EcoSeek runtime discover what
compute backends are available before initiating authenticated task
workflows.

The discovery endpoints are **unauthenticated by design** — clients can
enumerate connectors before the user has completed GitHub Device Flow
authentication.

Usage::

    from sources.connector_discovery import discover_connectors, discover_one

    connectors = discover_connectors("http://127.0.0.1:8080")
    for c in connectors:
        print(c.connector_id, c.health, [t.name for t in c.tools])

    single = discover_one("http://127.0.0.1:8080", "reumanlab")
    print(single.health_detail)

See ``docs/connector-discovery.md`` for setup instructions.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import requests

from sources.agenticplug_session import load_session_or_none
from sources.utility import pretty_print


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ConnectorTool:
    """A single capability/tool advertised by a connector."""

    name: str
    enabled: bool = False
    risk_level: str = "read"
    approval_required: bool = False

    def is_write(self) -> bool:
        return self.risk_level in ("compute", "write")


@dataclass
class HealthDetail:
    """Detailed health information for a connector."""

    status: str = "unknown"
    last_heartbeat_at: Optional[str] = None
    age_ms: Optional[int] = None
    stale_threshold_ms: Optional[int] = None


@dataclass
class Connector:
    """Parsed connector record from the discovery API."""

    connector_id: str
    display_name: str = ""
    owner: str = ""
    version: str = ""
    connector_type: str = "local"
    capabilities: Dict[str, bool] = field(default_factory=dict)
    tools: List[ConnectorTool] = field(default_factory=list)
    health: str = "unknown"
    health_detail: Optional[HealthDetail] = None
    last_heartbeat_at: Optional[str] = None
    registered_at: Optional[str] = None
    age_ms: Optional[int] = None
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_online(self) -> bool:
        return self.health == "online"

    @property
    def is_stale(self) -> bool:
        return self.health == "stale"

    def enabled_tools(self) -> List[ConnectorTool]:
        return [t for t in self.tools if t.enabled]

    def approval_gated_tools(self) -> List[ConnectorTool]:
        return [t for t in self.tools if t.approval_required]

    def has_capability(self, name: str) -> bool:
        return self.capabilities.get(name, False)


class ConnectorDiscoveryError(Exception):
    """Raised when the discovery API is unreachable or returns an error."""


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _parse_tool(data: Dict[str, Any]) -> ConnectorTool:
    return ConnectorTool(
        name=data.get("name", ""),
        enabled=bool(data.get("enabled", False)),
        risk_level=data.get("risk_level", "read"),
        approval_required=bool(data.get("approval_required", False)),
    )


def _parse_health_detail(data: Optional[Dict[str, Any]]) -> Optional[HealthDetail]:
    if not data or not isinstance(data, dict):
        return None
    return HealthDetail(
        status=data.get("status", "unknown"),
        last_heartbeat_at=data.get("last_heartbeat_at"),
        age_ms=data.get("age_ms"),
        stale_threshold_ms=data.get("stale_threshold_ms"),
    )


def _parse_connector(data: Dict[str, Any]) -> Connector:
    tools_raw = data.get("tools") or []
    tools = [_parse_tool(t) for t in tools_raw if isinstance(t, dict)]
    return Connector(
        connector_id=data.get("connector_id", ""),
        display_name=data.get("display_name", ""),
        owner=data.get("owner", ""),
        version=data.get("version", ""),
        connector_type=data.get("connector_type", "local"),
        capabilities=data.get("capabilities") or {},
        tools=tools,
        health=data.get("health", "unknown"),
        health_detail=_parse_health_detail(data.get("health_detail")),
        last_heartbeat_at=data.get("last_heartbeat_at"),
        registered_at=data.get("registered_at"),
        age_ms=data.get("age_ms"),
        raw=data,
    )


# ---------------------------------------------------------------------------
# Gateway URL resolution
# ---------------------------------------------------------------------------

def resolve_gateway_url(gateway_url: Optional[str] = None) -> str:
    """Resolve the AgenticPlug gateway base URL.

    Precedence (highest first):

    1. Explicit ``gateway_url`` argument.
    2. ``AGENTICPLUG_BASE_URL`` environment variable.
    3. ``base_url`` from the AgenticPlug session file.
    4. Default: ``http://127.0.0.1:8080``.

    The returned URL never ends with ``/v1`` — callers append the path
    themselves.
    """
    url = gateway_url or os.getenv("AGENTICPLUG_BASE_URL")
    if not url:
        session = load_session_or_none()
        if session and session.base_url:
            url = session.base_url
    if not url:
        url = "http://127.0.0.1:8080"
    url = url.rstrip("/")
    if url.endswith("/v1"):
        url = url[:-3]
    return url


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def discover_connectors(
    gateway_url: Optional[str] = None,
    timeout: float = 10.0,
) -> List[Connector]:
    """Fetch all registered connectors from the AgenticPlug gateway.

    Args:
        gateway_url: Base URL of the gateway (see ``resolve_gateway_url``
            for resolution order).
        timeout: HTTP request timeout in seconds.

    Returns:
        List of ``Connector`` objects.

    Raises:
        ConnectorDiscoveryError: On network errors, non-200 responses, or
            malformed payloads.
    """
    base = resolve_gateway_url(gateway_url)
    url = f"{base}/v1/connectors"

    try:
        resp = requests.get(url, timeout=timeout)
    except requests.ConnectionError as exc:
        raise ConnectorDiscoveryError(
            f"Cannot reach AgenticPlug gateway at {base}.\n"
            "Ensure the gateway is running: node broker/server.js\n"
            "See docs/connector-discovery.md for setup instructions."
        ) from exc
    except requests.Timeout as exc:
        raise ConnectorDiscoveryError(
            f"AgenticPlug gateway at {base} timed out after {timeout}s.\n"
            "See docs/connector-discovery.md for troubleshooting."
        ) from exc

    if resp.status_code == 503:
        raise ConnectorDiscoveryError(
            "AgenticPlug gateway returned 503 — registry not configured.\n"
            "See docs/connector-discovery.md for setup instructions."
        )
    if resp.status_code != 200:
        raise ConnectorDiscoveryError(
            f"AgenticPlug gateway returned HTTP {resp.status_code}: "
            f"{resp.text[:200]}"
        )

    try:
        body = resp.json()
    except ValueError as exc:
        raise ConnectorDiscoveryError(
            f"AgenticPlug gateway returned non-JSON response: {resp.text[:200]}"
        ) from exc

    raw_connectors = body.get("connectors")
    if not isinstance(raw_connectors, list):
        raise ConnectorDiscoveryError(
            "AgenticPlug gateway response missing 'connectors' array."
        )

    return [_parse_connector(c) for c in raw_connectors if isinstance(c, dict)]


def discover_one(
    connector_id: str,
    gateway_url: Optional[str] = None,
    timeout: float = 10.0,
) -> Connector:
    """Fetch a single connector by ID.

    Args:
        connector_id: The stable connector identifier.
        gateway_url: Base URL of the gateway.
        timeout: HTTP request timeout in seconds.

    Returns:
        A ``Connector`` object.

    Raises:
        ConnectorDiscoveryError: On errors or if the connector is not found.
    """
    base = resolve_gateway_url(gateway_url)
    url = f"{base}/v1/connectors/{connector_id}"

    try:
        resp = requests.get(url, timeout=timeout)
    except requests.ConnectionError as exc:
        raise ConnectorDiscoveryError(
            f"Cannot reach AgenticPlug gateway at {base}.\n"
            "Ensure the gateway is running: node broker/server.js\n"
            "See docs/connector-discovery.md for setup instructions."
        ) from exc
    except requests.Timeout as exc:
        raise ConnectorDiscoveryError(
            f"AgenticPlug gateway at {base} timed out after {timeout}s.\n"
            "See docs/connector-discovery.md for troubleshooting."
        ) from exc

    if resp.status_code == 404:
        raise ConnectorDiscoveryError(
            f"Connector '{connector_id}' not found on gateway at {base}.\n"
            "Run `GET /v1/connectors` to list available connectors."
        )
    if resp.status_code == 503:
        raise ConnectorDiscoveryError(
            "AgenticPlug gateway returned 503 — registry not configured."
        )
    if resp.status_code != 200:
        raise ConnectorDiscoveryError(
            f"AgenticPlug gateway returned HTTP {resp.status_code}: "
            f"{resp.text[:200]}"
        )

    try:
        body = resp.json()
    except ValueError as exc:
        raise ConnectorDiscoveryError(
            f"AgenticPlug gateway returned non-JSON response: {resp.text[:200]}"
        ) from exc

    raw = body.get("connector") or body
    if not isinstance(raw, dict) or "connector_id" not in raw:
        raise ConnectorDiscoveryError(
            "AgenticPlug gateway response missing 'connector' object."
        )

    return _parse_connector(raw)


def check_connector_health(
    connector_id: str,
    gateway_url: Optional[str] = None,
    timeout: float = 5.0,
) -> HealthDetail:
    """Lightweight health check for a single connector.

    Args:
        connector_id: The stable connector identifier.
        gateway_url: Base URL of the gateway.
        timeout: HTTP request timeout in seconds.

    Returns:
        A ``HealthDetail`` object.

    Raises:
        ConnectorDiscoveryError: On errors or if the connector is not found.
    """
    base = resolve_gateway_url(gateway_url)
    url = f"{base}/v1/connectors/{connector_id}/health"

    try:
        resp = requests.get(url, timeout=timeout)
    except (requests.ConnectionError, requests.Timeout) as exc:
        raise ConnectorDiscoveryError(
            f"Health check failed for connector '{connector_id}' at {base}: {exc}"
        ) from exc

    if resp.status_code == 404:
        raise ConnectorDiscoveryError(
            f"Connector '{connector_id}' not found on gateway at {base}."
        )
    if resp.status_code != 200:
        raise ConnectorDiscoveryError(
            f"Health check returned HTTP {resp.status_code}: {resp.text[:200]}"
        )

    try:
        body = resp.json()
    except ValueError as exc:
        raise ConnectorDiscoveryError(
            f"Health check returned non-JSON response: {resp.text[:200]}"
        ) from exc

    detail = body.get("health_detail") or body
    return _parse_health_detail(detail) or HealthDetail(status=body.get("health", "unknown"))


def print_connector_summary(connectors: List[Connector]) -> None:
    """Print a human-readable summary of discovered connectors."""
    if not connectors:
        pretty_print("No connectors discovered.", color="warning")
        return

    pretty_print(f"Discovered {len(connectors)} connector(s):", color="status")
    for c in connectors:
        health_icon = {
            "online": "[OK]",
            "degraded": "[!!]",
            "stale": "[--]",
        }.get(c.health, "[??]")

        tools_str = ", ".join(
            f"{t.name}{'*' if t.approval_required else ''}"
            for t in c.enabled_tools()
        ) or "(none)"

        pretty_print(
            f"  {health_icon} {c.connector_id} ({c.connector_type}) "
            f"v{c.version} — tools: {tools_str}",
            color="success" if c.is_online else "warning",
        )
