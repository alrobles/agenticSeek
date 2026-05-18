"""Tests for the connector_discovery client module.

Covers:
- Connector/tool data class construction and properties
- Gateway URL resolution (arg, env, session, default)
- discover_connectors() — success, connection error, timeout, 503, 404, malformed
- discover_one() — success, 404, connection error
- check_connector_health() — success, 404, connection error
- print_connector_summary() — output formatting
- No regressions on existing modules
"""

import json
import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path

from sources.connector_discovery import (
    Connector,
    ConnectorTool,
    ConnectorDiscoveryError,
    HealthDetail,
    discover_connectors,
    discover_one,
    check_connector_health,
    resolve_gateway_url,
    print_connector_summary,
    _parse_connector,
    _parse_tool,
    _parse_health_detail,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_CONNECTOR = {
    "connector_id": "reumanlab",
    "display_name": "Reumanlab HPC",
    "owner": "alice",
    "version": "0.2.0",
    "connector_type": "hpc",
    "capabilities": {"github": True, "hpc_read": True, "hpc_submit": False},
    "tools": [
        {"name": "github", "enabled": True, "risk_level": "read", "approval_required": False},
        {"name": "hpc_read", "enabled": True, "risk_level": "read", "approval_required": False},
        {"name": "hpc_submit", "enabled": False, "risk_level": "compute", "approval_required": True},
    ],
    "health": "online",
    "health_detail": {
        "status": "online",
        "last_heartbeat_at": "2026-05-17T20:00:00.000Z",
        "age_ms": 5000,
        "stale_threshold_ms": 90000,
    },
    "last_heartbeat_at": "2026-05-17T20:00:00.000Z",
    "registered_at": "2026-05-17T19:00:00.000Z",
    "age_ms": 5000,
}

SAMPLE_LIST_RESPONSE = {"connectors": [SAMPLE_CONNECTOR]}
SAMPLE_SINGLE_RESPONSE = {"connector": SAMPLE_CONNECTOR}
SAMPLE_HEALTH_RESPONSE = {
    "connector_id": "reumanlab",
    "health": "online",
    "health_detail": {
        "status": "online",
        "last_heartbeat_at": "2026-05-17T20:00:00.000Z",
        "age_ms": 5000,
        "stale_threshold_ms": 90000,
    },
}


def _mock_response(status_code=200, json_data=None, text=""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text or json.dumps(json_data or {})
    resp.json.return_value = json_data
    return resp


# ---------------------------------------------------------------------------
# Data class tests
# ---------------------------------------------------------------------------

class TestConnectorTool(unittest.TestCase):

    def test_read_tool_not_write(self):
        t = ConnectorTool(name="github", enabled=True, risk_level="read")
        self.assertFalse(t.is_write())

    def test_compute_tool_is_write(self):
        t = ConnectorTool(name="hpc_submit", enabled=False, risk_level="compute")
        self.assertTrue(t.is_write())

    def test_defaults(self):
        t = ConnectorTool(name="x")
        self.assertFalse(t.enabled)
        self.assertEqual(t.risk_level, "read")
        self.assertFalse(t.approval_required)


class TestConnector(unittest.TestCase):

    def test_is_online(self):
        c = Connector(connector_id="a", health="online")
        self.assertTrue(c.is_online)
        self.assertFalse(c.is_stale)

    def test_is_stale(self):
        c = Connector(connector_id="a", health="stale")
        self.assertTrue(c.is_stale)
        self.assertFalse(c.is_online)

    def test_enabled_tools(self):
        c = _parse_connector(SAMPLE_CONNECTOR)
        enabled = c.enabled_tools()
        self.assertEqual(len(enabled), 2)
        names = [t.name for t in enabled]
        self.assertIn("github", names)
        self.assertIn("hpc_read", names)

    def test_approval_gated_tools(self):
        c = _parse_connector(SAMPLE_CONNECTOR)
        gated = c.approval_gated_tools()
        self.assertEqual(len(gated), 1)
        self.assertEqual(gated[0].name, "hpc_submit")

    def test_has_capability(self):
        c = _parse_connector(SAMPLE_CONNECTOR)
        self.assertTrue(c.has_capability("github"))
        self.assertFalse(c.has_capability("hpc_submit"))
        self.assertFalse(c.has_capability("nonexistent"))

    def test_defaults(self):
        c = Connector(connector_id="x")
        self.assertEqual(c.connector_type, "local")
        self.assertEqual(c.health, "unknown")
        self.assertEqual(c.tools, [])


class TestHealthDetail(unittest.TestCase):

    def test_fields(self):
        hd = HealthDetail(status="online", age_ms=5000, stale_threshold_ms=90000)
        self.assertEqual(hd.status, "online")
        self.assertEqual(hd.age_ms, 5000)

    def test_defaults(self):
        hd = HealthDetail()
        self.assertEqual(hd.status, "unknown")
        self.assertIsNone(hd.last_heartbeat_at)


# ---------------------------------------------------------------------------
# Parsing tests
# ---------------------------------------------------------------------------

class TestParsing(unittest.TestCase):

    def test_parse_tool(self):
        t = _parse_tool({"name": "hpc_read", "enabled": True, "risk_level": "read", "approval_required": False})
        self.assertEqual(t.name, "hpc_read")
        self.assertTrue(t.enabled)

    def test_parse_tool_missing_fields(self):
        t = _parse_tool({"name": "x"})
        self.assertFalse(t.enabled)
        self.assertEqual(t.risk_level, "read")

    def test_parse_health_detail(self):
        hd = _parse_health_detail({"status": "degraded", "age_ms": 100})
        self.assertEqual(hd.status, "degraded")
        self.assertEqual(hd.age_ms, 100)

    def test_parse_health_detail_none(self):
        self.assertIsNone(_parse_health_detail(None))
        self.assertIsNone(_parse_health_detail("not a dict"))

    def test_parse_connector_full(self):
        c = _parse_connector(SAMPLE_CONNECTOR)
        self.assertEqual(c.connector_id, "reumanlab")
        self.assertEqual(c.connector_type, "hpc")
        self.assertEqual(len(c.tools), 3)
        self.assertEqual(c.health, "online")
        self.assertIsNotNone(c.health_detail)
        self.assertEqual(c.health_detail.status, "online")

    def test_parse_connector_minimal(self):
        c = _parse_connector({"connector_id": "bare"})
        self.assertEqual(c.connector_id, "bare")
        self.assertEqual(c.connector_type, "local")
        self.assertEqual(c.tools, [])


# ---------------------------------------------------------------------------
# Gateway URL resolution
# ---------------------------------------------------------------------------

class TestResolveGatewayUrl(unittest.TestCase):

    def test_explicit_arg_wins(self):
        url = resolve_gateway_url("http://custom:9090")
        self.assertEqual(url, "http://custom:9090")

    @patch.dict("os.environ", {"AGENTICPLUG_BASE_URL": "http://env-gw:8080"})
    def test_env_var(self):
        url = resolve_gateway_url()
        self.assertEqual(url, "http://env-gw:8080")

    @patch.dict("os.environ", {}, clear=True)
    @patch("sources.connector_discovery.load_session_or_none")
    def test_session_url(self, mock_sess):
        from sources.agenticplug_session import AgenticPlugSession
        mock_sess.return_value = AgenticPlugSession(
            path=Path("/fake"), base_url="http://sess-gw:8080/v1"
        )
        url = resolve_gateway_url()
        self.assertEqual(url, "http://sess-gw:8080")

    @patch.dict("os.environ", {}, clear=True)
    @patch("sources.connector_discovery.load_session_or_none", return_value=None)
    def test_default(self, _):
        url = resolve_gateway_url()
        self.assertEqual(url, "http://127.0.0.1:8080")

    def test_strips_trailing_v1(self):
        url = resolve_gateway_url("http://gw:8080/v1")
        self.assertEqual(url, "http://gw:8080")

    def test_strips_trailing_slash(self):
        url = resolve_gateway_url("http://gw:8080/")
        self.assertEqual(url, "http://gw:8080")


# ---------------------------------------------------------------------------
# discover_connectors()
# ---------------------------------------------------------------------------

class TestDiscoverConnectors(unittest.TestCase):

    @patch("sources.connector_discovery.requests.get")
    def test_success(self, mock_get):
        mock_get.return_value = _mock_response(200, SAMPLE_LIST_RESPONSE)
        connectors = discover_connectors("http://gw:8080")
        self.assertEqual(len(connectors), 1)
        self.assertEqual(connectors[0].connector_id, "reumanlab")
        mock_get.assert_called_once_with("http://gw:8080/v1/connectors", timeout=10.0)

    @patch("sources.connector_discovery.requests.get")
    def test_empty_list(self, mock_get):
        mock_get.return_value = _mock_response(200, {"connectors": []})
        connectors = discover_connectors("http://gw:8080")
        self.assertEqual(connectors, [])

    @patch("sources.connector_discovery.requests.get")
    def test_connection_error(self, mock_get):
        import requests
        mock_get.side_effect = requests.ConnectionError("refused")
        with self.assertRaises(ConnectorDiscoveryError) as ctx:
            discover_connectors("http://gw:8080")
        self.assertIn("Cannot reach", str(ctx.exception))
        self.assertIn("connector-discovery.md", str(ctx.exception))

    @patch("sources.connector_discovery.requests.get")
    def test_timeout(self, mock_get):
        import requests
        mock_get.side_effect = requests.Timeout("timed out")
        with self.assertRaises(ConnectorDiscoveryError) as ctx:
            discover_connectors("http://gw:8080")
        self.assertIn("timed out", str(ctx.exception))

    @patch("sources.connector_discovery.requests.get")
    def test_503_registry_not_configured(self, mock_get):
        mock_get.return_value = _mock_response(503, text="registry_not_configured")
        with self.assertRaises(ConnectorDiscoveryError) as ctx:
            discover_connectors("http://gw:8080")
        self.assertIn("503", str(ctx.exception))
        self.assertIn("registry not configured", str(ctx.exception))

    @patch("sources.connector_discovery.requests.get")
    def test_non_200(self, mock_get):
        mock_get.return_value = _mock_response(500, text="Internal Server Error")
        with self.assertRaises(ConnectorDiscoveryError) as ctx:
            discover_connectors("http://gw:8080")
        self.assertIn("500", str(ctx.exception))

    @patch("sources.connector_discovery.requests.get")
    def test_malformed_json(self, mock_get):
        resp = MagicMock()
        resp.status_code = 200
        resp.text = "not json"
        resp.json.side_effect = ValueError("bad json")
        mock_get.return_value = resp
        with self.assertRaises(ConnectorDiscoveryError) as ctx:
            discover_connectors("http://gw:8080")
        self.assertIn("non-JSON", str(ctx.exception))

    @patch("sources.connector_discovery.requests.get")
    def test_missing_connectors_key(self, mock_get):
        mock_get.return_value = _mock_response(200, {"data": []})
        with self.assertRaises(ConnectorDiscoveryError) as ctx:
            discover_connectors("http://gw:8080")
        self.assertIn("missing 'connectors' array", str(ctx.exception))

    @patch("sources.connector_discovery.requests.get")
    def test_multiple_connectors(self, mock_get):
        second = dict(SAMPLE_CONNECTOR, connector_id="dev-local", connector_type="local", health="stale")
        mock_get.return_value = _mock_response(200, {"connectors": [SAMPLE_CONNECTOR, second]})
        connectors = discover_connectors("http://gw:8080")
        self.assertEqual(len(connectors), 2)
        self.assertEqual(connectors[1].connector_id, "dev-local")
        self.assertTrue(connectors[1].is_stale)


# ---------------------------------------------------------------------------
# discover_one()
# ---------------------------------------------------------------------------

class TestDiscoverOne(unittest.TestCase):

    @patch("sources.connector_discovery.requests.get")
    def test_success(self, mock_get):
        mock_get.return_value = _mock_response(200, SAMPLE_SINGLE_RESPONSE)
        c = discover_one("reumanlab", "http://gw:8080")
        self.assertEqual(c.connector_id, "reumanlab")
        mock_get.assert_called_once_with("http://gw:8080/v1/connectors/reumanlab", timeout=10.0)

    @patch("sources.connector_discovery.requests.get")
    def test_404(self, mock_get):
        mock_get.return_value = _mock_response(404, text='{"error":"not found"}')
        with self.assertRaises(ConnectorDiscoveryError) as ctx:
            discover_one("missing", "http://gw:8080")
        self.assertIn("not found", str(ctx.exception))

    @patch("sources.connector_discovery.requests.get")
    def test_connection_error(self, mock_get):
        import requests
        mock_get.side_effect = requests.ConnectionError("refused")
        with self.assertRaises(ConnectorDiscoveryError) as ctx:
            discover_one("reumanlab", "http://gw:8080")
        self.assertIn("Cannot reach", str(ctx.exception))

    @patch("sources.connector_discovery.requests.get")
    def test_503(self, mock_get):
        mock_get.return_value = _mock_response(503, text="registry_not_configured")
        with self.assertRaises(ConnectorDiscoveryError) as ctx:
            discover_one("reumanlab", "http://gw:8080")
        self.assertIn("503", str(ctx.exception))

    @patch("sources.connector_discovery.requests.get")
    def test_malformed_response(self, mock_get):
        mock_get.return_value = _mock_response(200, {"unexpected": "shape"})
        with self.assertRaises(ConnectorDiscoveryError) as ctx:
            discover_one("reumanlab", "http://gw:8080")
        self.assertIn("missing 'connector' object", str(ctx.exception))


# ---------------------------------------------------------------------------
# check_connector_health()
# ---------------------------------------------------------------------------

class TestCheckConnectorHealth(unittest.TestCase):

    @patch("sources.connector_discovery.requests.get")
    def test_success(self, mock_get):
        mock_get.return_value = _mock_response(200, SAMPLE_HEALTH_RESPONSE)
        hd = check_connector_health("reumanlab", "http://gw:8080")
        self.assertEqual(hd.status, "online")
        self.assertEqual(hd.age_ms, 5000)

    @patch("sources.connector_discovery.requests.get")
    def test_404(self, mock_get):
        mock_get.return_value = _mock_response(404, text='{"error":"not found"}')
        with self.assertRaises(ConnectorDiscoveryError) as ctx:
            check_connector_health("missing", "http://gw:8080")
        self.assertIn("not found", str(ctx.exception))

    @patch("sources.connector_discovery.requests.get")
    def test_connection_error(self, mock_get):
        import requests
        mock_get.side_effect = requests.ConnectionError("refused")
        with self.assertRaises(ConnectorDiscoveryError) as ctx:
            check_connector_health("reumanlab", "http://gw:8080")
        self.assertIn("Health check failed", str(ctx.exception))

    @patch("sources.connector_discovery.requests.get")
    def test_timeout(self, mock_get):
        import requests
        mock_get.side_effect = requests.Timeout("timed out")
        with self.assertRaises(ConnectorDiscoveryError) as ctx:
            check_connector_health("reumanlab", "http://gw:8080")
        self.assertIn("Health check failed", str(ctx.exception))


# ---------------------------------------------------------------------------
# print_connector_summary()
# ---------------------------------------------------------------------------

class TestPrintConnectorSummary(unittest.TestCase):

    @patch("sources.connector_discovery.pretty_print")
    def test_empty_list(self, mock_pp):
        print_connector_summary([])
        mock_pp.assert_called_once()
        self.assertIn("No connectors", mock_pp.call_args[0][0])

    @patch("sources.connector_discovery.pretty_print")
    def test_one_online(self, mock_pp):
        c = _parse_connector(SAMPLE_CONNECTOR)
        print_connector_summary([c])
        calls = [call[0][0] for call in mock_pp.call_args_list]
        self.assertTrue(any("reumanlab" in s for s in calls))
        self.assertTrue(any("[OK]" in s for s in calls))

    @patch("sources.connector_discovery.pretty_print")
    def test_stale_connector(self, mock_pp):
        data = dict(SAMPLE_CONNECTOR, connector_id="stale-one", health="stale")
        c = _parse_connector(data)
        print_connector_summary([c])
        calls = [call[0][0] for call in mock_pp.call_args_list]
        self.assertTrue(any("[--]" in s for s in calls))


# ---------------------------------------------------------------------------
# Regression: existing modules still importable
# ---------------------------------------------------------------------------

class TestNoRegressions(unittest.TestCase):

    def test_agenticplug_session_importable(self):
        from sources.agenticplug_session import AgenticPlugSession, load_session_or_none
        self.assertTrue(callable(load_session_or_none))

    def test_schemas_importable(self):
        from sources.schemas import AgenticPlugTask, AgenticPlugTaskState
        self.assertIsNotNone(AgenticPlugTaskState.TASK_CREATED)

    def test_agenticplug_ux_importable(self):
        from sources.agenticplug_ux import AgenticPlugUXStore
        self.assertTrue(callable(AgenticPlugUXStore))


if __name__ == "__main__":
    unittest.main()
