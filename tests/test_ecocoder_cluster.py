"""Tests for the ecocoder_cluster provider integration.

Covers:
- Provider initialization with ecocoder_cluster
- Unsafe provider classification (data leaves the machine)
- AgenticPlug session loading and env var overrides
- Model name resolution (generic names -> ecocoder)
- Model validation warnings
- Route header defaults and overrides
- Auth error handling (401 -> actionable hint)
- Model-not-found error handling (404)
- Connection error handling (fail-closed)
- Successful response assembly
- No regressions on other providers
"""

import json
import unittest
from unittest.mock import patch, MagicMock, PropertyMock

from sources.agenticplug_session import AgenticPlugSession
from pathlib import Path


def _mock_session(**overrides):
    """Build a fake AgenticPlugSession for testing."""
    defaults = dict(
        path=Path("/fake/session.json"),
        base_url="http://gateway.test:8080/v1",
        token="test-bearer-token",
        token_type="Bearer",
        expires_at=None,
        user={"login": "testuser"},
        scopes=["read:user"],
        route_header="ecocoder",
        model="ecocoder",
        default_cluster="ku-hpc",
        raw={},
    )
    defaults.update(overrides)
    return AgenticPlugSession(**defaults)


class TestEcoCoderClusterInit(unittest.TestCase):
    """Provider initialization with ecocoder_cluster."""

    @patch("sources.llm_provider.pretty_print")
    def test_ecocoder_cluster_in_available_providers(self, _pp):
        from sources.llm_provider import Provider
        p = Provider("ecocoder_cluster", "ecocoder", server_address="127.0.0.1:8080", is_local=False)
        self.assertIn("ecocoder_cluster", p.available_providers)

    @patch("sources.llm_provider.pretty_print")
    def test_ecocoder_cluster_in_unsafe_providers(self, _pp):
        """ecocoder_cluster sends data to a remote cluster — it IS unsafe."""
        from sources.llm_provider import Provider
        p = Provider("ecocoder_cluster", "ecocoder", server_address="127.0.0.1:8080", is_local=False)
        self.assertIn("ecocoder_cluster", p.unsafe_providers)

    @patch("sources.llm_provider.pretty_print")
    def test_ecocoder_cluster_cloud_warning_when_not_local(self, mock_pp):
        """ecocoder_cluster with is_local=False should trigger cloud-usage warning."""
        from sources.llm_provider import Provider
        Provider("ecocoder_cluster", "ecocoder", server_address="127.0.0.1:8080", is_local=False)
        cloud_warnings = [
            call for call in mock_pp.call_args_list
            if call[0] and "cloud" in call[0][0].lower()
        ]
        self.assertTrue(len(cloud_warnings) > 0, "Expected cloud-usage warning")

    @patch("sources.llm_provider.pretty_print")
    def test_ecocoder_cluster_no_cloud_warning_when_local(self, mock_pp):
        """ecocoder_cluster with is_local=True should not trigger cloud warning."""
        from sources.llm_provider import Provider
        Provider("ecocoder_cluster", "ecocoder", server_address="127.0.0.1:8080", is_local=True)
        cloud_warnings = [
            call for call in mock_pp.call_args_list
            if call[0] and "cloud" in call[0][0].lower()
        ]
        self.assertEqual(len(cloud_warnings), 0, "Unexpected cloud-usage warning for local")

    @patch("sources.llm_provider.pretty_print")
    def test_ecocoder_local_still_not_unsafe(self, _pp):
        """Verify ecocoder_local is still NOT in unsafe_providers."""
        from sources.llm_provider import Provider
        p = Provider("ecocoder_local", "ecocoder", server_address="127.0.0.1:11434", is_local=True)
        self.assertNotIn("ecocoder_local", p.unsafe_providers)


class TestEcoCoderClusterModelResolution(unittest.TestCase):
    """Model name resolution at call time."""

    @patch("sources.llm_provider.load_session_or_none", return_value=None)
    @patch("sources.llm_provider.load_dotenv")
    @patch("sources.llm_provider.pretty_print")
    def test_generic_deepseek_resolved_to_ecocoder(self, _pp, _env, _sess):
        from sources.llm_provider import Provider
        p = Provider("ecocoder_cluster", "deepseek-r1:14b", server_address="127.0.0.1:8080", is_local=False)

        with patch("sources.llm_provider.OpenAI") as MockOpenAI:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]
            mock_response.choices[0].message.content = "ok"
            mock_client.chat.completions.create.return_value = mock_response
            MockOpenAI.return_value = mock_client

            p.ecocoder_cluster_fn([{"role": "user", "content": "test"}])
            call_args = mock_client.chat.completions.create.call_args
            self.assertEqual(call_args[1]["model"], "ecocoder")

    @patch("sources.llm_provider.load_session_or_none", return_value=None)
    @patch("sources.llm_provider.load_dotenv")
    @patch("sources.llm_provider.pretty_print")
    def test_deepseek_chat_resolved_to_ecocoder(self, _pp, _env, _sess):
        from sources.llm_provider import Provider
        p = Provider("ecocoder_cluster", "deepseek-chat", server_address="127.0.0.1:8080", is_local=False)

        with patch("sources.llm_provider.OpenAI") as MockOpenAI:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]
            mock_response.choices[0].message.content = "ok"
            mock_client.chat.completions.create.return_value = mock_response
            MockOpenAI.return_value = mock_client

            p.ecocoder_cluster_fn([{"role": "user", "content": "test"}])
            call_args = mock_client.chat.completions.create.call_args
            self.assertEqual(call_args[1]["model"], "ecocoder")

    @patch("sources.llm_provider.load_session_or_none", return_value=None)
    @patch("sources.llm_provider.load_dotenv")
    @patch("sources.llm_provider.pretty_print")
    def test_explicit_ecocoder_stays(self, _pp, _env, _sess):
        from sources.llm_provider import Provider
        p = Provider("ecocoder_cluster", "ecocoder", server_address="127.0.0.1:8080", is_local=False)

        with patch("sources.llm_provider.OpenAI") as MockOpenAI:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]
            mock_response.choices[0].message.content = "ok"
            mock_client.chat.completions.create.return_value = mock_response
            MockOpenAI.return_value = mock_client

            p.ecocoder_cluster_fn([{"role": "user", "content": "test"}])
            call_args = mock_client.chat.completions.create.call_args
            self.assertEqual(call_args[1]["model"], "ecocoder")

    @patch("sources.llm_provider.load_session_or_none", return_value=None)
    @patch("sources.llm_provider.load_dotenv")
    @patch("sources.llm_provider.pretty_print")
    def test_qwen_alias_resolved(self, _pp, _env, _sess):
        from sources.llm_provider import Provider
        p = Provider("ecocoder_cluster", "qwen2.5-coder:7b", server_address="127.0.0.1:8080", is_local=False)

        with patch("sources.llm_provider.OpenAI") as MockOpenAI:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]
            mock_response.choices[0].message.content = "ok"
            mock_client.chat.completions.create.return_value = mock_response
            MockOpenAI.return_value = mock_client

            p.ecocoder_cluster_fn([{"role": "user", "content": "test"}])
            call_args = mock_client.chat.completions.create.call_args
            self.assertEqual(call_args[1]["model"], "ecocoder")

    @patch("sources.llm_provider.load_session_or_none", return_value=None)
    @patch("sources.llm_provider.load_dotenv")
    @patch("sources.llm_provider.pretty_print")
    def test_custom_model_preserved(self, _pp, _env, _sess):
        from sources.llm_provider import Provider
        p = Provider("ecocoder_cluster", "ecocoder:7b", server_address="127.0.0.1:8080", is_local=False)

        with patch("sources.llm_provider.OpenAI") as MockOpenAI:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]
            mock_response.choices[0].message.content = "ok"
            mock_client.chat.completions.create.return_value = mock_response
            MockOpenAI.return_value = mock_client

            p.ecocoder_cluster_fn([{"role": "user", "content": "test"}])
            call_args = mock_client.chat.completions.create.call_args
            self.assertEqual(call_args[1]["model"], "ecocoder:7b")


class TestEcoCoderClusterModelValidation(unittest.TestCase):
    """Model validation warns on unrecognized variants."""

    @patch("sources.llm_provider.load_session_or_none", return_value=None)
    @patch("sources.llm_provider.load_dotenv")
    @patch("sources.llm_provider.pretty_print")
    def test_recognized_model_no_warning(self, mock_pp, _env, _sess):
        from sources.llm_provider import Provider
        p = Provider("ecocoder_cluster", "ecocoder", server_address="127.0.0.1:8080", is_local=False)

        with patch("sources.llm_provider.OpenAI") as MockOpenAI:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]
            mock_response.choices[0].message.content = "ok"
            mock_client.chat.completions.create.return_value = mock_response
            MockOpenAI.return_value = mock_client

            p.ecocoder_cluster_fn([{"role": "user", "content": "test"}])
            for call in mock_pp.call_args_list:
                if call[0] and "not a recognized" in str(call[0][0]):
                    self.fail("Unexpected warning for recognized model 'ecocoder'")

    @patch("sources.llm_provider.load_session_or_none", return_value=None)
    @patch("sources.llm_provider.load_dotenv")
    @patch("sources.llm_provider.pretty_print")
    def test_unrecognized_model_emits_warning(self, mock_pp, _env, _sess):
        from sources.llm_provider import Provider
        p = Provider("ecocoder_cluster", "my-custom-model", server_address="127.0.0.1:8080", is_local=False)

        with patch("sources.llm_provider.OpenAI") as MockOpenAI:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]
            mock_response.choices[0].message.content = "ok"
            mock_client.chat.completions.create.return_value = mock_response
            MockOpenAI.return_value = mock_client

            p.ecocoder_cluster_fn([{"role": "user", "content": "test"}])
            warning_found = any(
                "not a recognized" in str(call[0][0])
                for call in mock_pp.call_args_list
                if call[0]
            )
            self.assertTrue(warning_found, "Expected warning for unrecognized model")


class TestEcoCoderClusterSessionConfig(unittest.TestCase):
    """AgenticPlug session loading and env var overrides."""

    @patch("sources.llm_provider.pretty_print")
    def test_session_base_url_used(self, _pp):
        from sources.llm_provider import Provider
        p = Provider("ecocoder_cluster", "ecocoder", server_address="127.0.0.1:8080", is_local=False)
        session = _mock_session(base_url="http://custom-gateway:9090/v1")

        with patch("sources.llm_provider.load_session_or_none", return_value=session), \
             patch("sources.llm_provider.load_dotenv"), \
             patch.dict("os.environ", {}, clear=True), \
             patch("sources.llm_provider.OpenAI") as MockOpenAI:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]
            mock_response.choices[0].message.content = "ok"
            mock_client.chat.completions.create.return_value = mock_response
            MockOpenAI.return_value = mock_client

            p.ecocoder_cluster_fn([{"role": "user", "content": "test"}])
            openai_kwargs = MockOpenAI.call_args[1]
            self.assertEqual(openai_kwargs["base_url"], "http://custom-gateway:9090/v1")

    @patch("sources.llm_provider.pretty_print")
    def test_env_var_overrides_session(self, _pp):
        from sources.llm_provider import Provider
        p = Provider("ecocoder_cluster", "ecocoder", server_address="127.0.0.1:8080", is_local=False)
        session = _mock_session(base_url="http://session-gateway/v1")

        env = {
            "ECOCODER_CLUSTER_BASE_URL": "http://env-gateway/v1",
            "ECOCODER_CLUSTER_API_KEY": "env-key",
            "ECOCODER_CLUSTER_ROUTE": "env-route",
        }

        with patch("sources.llm_provider.load_session_or_none", return_value=session), \
             patch("sources.llm_provider.load_dotenv"), \
             patch.dict("os.environ", env, clear=True), \
             patch("sources.llm_provider.OpenAI") as MockOpenAI:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]
            mock_response.choices[0].message.content = "ok"
            mock_client.chat.completions.create.return_value = mock_response
            MockOpenAI.return_value = mock_client

            p.ecocoder_cluster_fn([{"role": "user", "content": "test"}])
            openai_kwargs = MockOpenAI.call_args[1]
            self.assertEqual(openai_kwargs["base_url"], "http://env-gateway/v1")
            self.assertEqual(openai_kwargs["api_key"], "env-key")
            self.assertEqual(openai_kwargs["default_headers"]["X-AgenticPlug-Route"], "env-route")

    @patch("sources.llm_provider.pretty_print")
    def test_env_model_overrides_resolution(self, _pp):
        from sources.llm_provider import Provider
        p = Provider("ecocoder_cluster", "ecocoder", server_address="127.0.0.1:8080", is_local=False)

        env = {"ECOCODER_CLUSTER_MODEL": "ecocoder-v2"}

        with patch("sources.llm_provider.load_session_or_none", return_value=None), \
             patch("sources.llm_provider.load_dotenv"), \
             patch.dict("os.environ", env, clear=True), \
             patch("sources.llm_provider.OpenAI") as MockOpenAI:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]
            mock_response.choices[0].message.content = "ok"
            mock_client.chat.completions.create.return_value = mock_response
            MockOpenAI.return_value = mock_client

            p.ecocoder_cluster_fn([{"role": "user", "content": "test"}])
            call_args = mock_client.chat.completions.create.call_args
            self.assertEqual(call_args[1]["model"], "ecocoder-v2")

    @patch("sources.llm_provider.pretty_print")
    def test_fallback_to_server_address(self, _pp):
        from sources.llm_provider import Provider
        p = Provider("ecocoder_cluster", "ecocoder", server_address="10.0.0.5:9090", is_local=False)

        with patch("sources.llm_provider.load_session_or_none", return_value=None), \
             patch("sources.llm_provider.load_dotenv"), \
             patch.dict("os.environ", {}, clear=True), \
             patch("sources.llm_provider.OpenAI") as MockOpenAI:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]
            mock_response.choices[0].message.content = "ok"
            mock_client.chat.completions.create.return_value = mock_response
            MockOpenAI.return_value = mock_client

            p.ecocoder_cluster_fn([{"role": "user", "content": "test"}])
            openai_kwargs = MockOpenAI.call_args[1]
            self.assertEqual(openai_kwargs["base_url"], "http://10.0.0.5:9090/v1")

    @patch("sources.llm_provider.pretty_print")
    def test_no_session_uses_not_required_key(self, _pp):
        from sources.llm_provider import Provider
        p = Provider("ecocoder_cluster", "ecocoder", server_address="127.0.0.1:8080", is_local=False)

        with patch("sources.llm_provider.load_session_or_none", return_value=None), \
             patch("sources.llm_provider.load_dotenv"), \
             patch.dict("os.environ", {}, clear=True), \
             patch("sources.llm_provider.OpenAI") as MockOpenAI:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]
            mock_response.choices[0].message.content = "ok"
            mock_client.chat.completions.create.return_value = mock_response
            MockOpenAI.return_value = mock_client

            p.ecocoder_cluster_fn([{"role": "user", "content": "test"}])
            openai_kwargs = MockOpenAI.call_args[1]
            self.assertEqual(openai_kwargs["api_key"], "not-required")


class TestEcoCoderClusterRouteHeader(unittest.TestCase):
    """Route header defaults and overrides."""

    @patch("sources.llm_provider.pretty_print")
    def test_default_route_is_ecocoder(self, _pp):
        from sources.llm_provider import Provider
        p = Provider("ecocoder_cluster", "ecocoder", server_address="127.0.0.1:8080", is_local=False)

        with patch("sources.llm_provider.load_session_or_none", return_value=None), \
             patch("sources.llm_provider.load_dotenv"), \
             patch.dict("os.environ", {}, clear=True), \
             patch("sources.llm_provider.OpenAI") as MockOpenAI:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]
            mock_response.choices[0].message.content = "ok"
            mock_client.chat.completions.create.return_value = mock_response
            MockOpenAI.return_value = mock_client

            p.ecocoder_cluster_fn([{"role": "user", "content": "test"}])
            openai_kwargs = MockOpenAI.call_args[1]
            self.assertEqual(openai_kwargs["default_headers"]["X-AgenticPlug-Route"], "ecocoder")

    @patch("sources.llm_provider.pretty_print")
    def test_session_route_used(self, _pp):
        from sources.llm_provider import Provider
        p = Provider("ecocoder_cluster", "ecocoder", server_address="127.0.0.1:8080", is_local=False)
        session = _mock_session(route_header="ecocoder-v2")

        with patch("sources.llm_provider.load_session_or_none", return_value=session), \
             patch("sources.llm_provider.load_dotenv"), \
             patch.dict("os.environ", {}, clear=True), \
             patch("sources.llm_provider.OpenAI") as MockOpenAI:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]
            mock_response.choices[0].message.content = "ok"
            mock_client.chat.completions.create.return_value = mock_response
            MockOpenAI.return_value = mock_client

            p.ecocoder_cluster_fn([{"role": "user", "content": "test"}])
            openai_kwargs = MockOpenAI.call_args[1]
            self.assertEqual(openai_kwargs["default_headers"]["X-AgenticPlug-Route"], "ecocoder-v2")

    @patch("sources.llm_provider.pretty_print")
    def test_env_route_overrides_session(self, _pp):
        from sources.llm_provider import Provider
        p = Provider("ecocoder_cluster", "ecocoder", server_address="127.0.0.1:8080", is_local=False)
        session = _mock_session(route_header="session-route")

        with patch("sources.llm_provider.load_session_or_none", return_value=session), \
             patch("sources.llm_provider.load_dotenv"), \
             patch.dict("os.environ", {"ECOCODER_CLUSTER_ROUTE": "env-route"}, clear=True), \
             patch("sources.llm_provider.OpenAI") as MockOpenAI:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]
            mock_response.choices[0].message.content = "ok"
            mock_client.chat.completions.create.return_value = mock_response
            MockOpenAI.return_value = mock_client

            p.ecocoder_cluster_fn([{"role": "user", "content": "test"}])
            openai_kwargs = MockOpenAI.call_args[1]
            self.assertEqual(openai_kwargs["default_headers"]["X-AgenticPlug-Route"], "env-route")


class TestEcoCoderClusterErrors(unittest.TestCase):
    """Error handling — fail-closed with actionable messages."""

    @patch("sources.llm_provider.load_session_or_none", return_value=None)
    @patch("sources.llm_provider.load_dotenv")
    @patch("sources.llm_provider.pretty_print")
    def test_auth_error_401(self, _pp, _env, _sess):
        from sources.llm_provider import Provider
        p = Provider("ecocoder_cluster", "ecocoder", server_address="127.0.0.1:8080", is_local=False)

        with patch("sources.llm_provider.OpenAI") as MockOpenAI:
            mock_client = MagicMock()
            mock_client.chat.completions.create.side_effect = Exception("401 Unauthorized")
            MockOpenAI.return_value = mock_client

            with self.assertRaises(Exception) as ctx:
                p.ecocoder_cluster_fn([{"role": "user", "content": "test"}])
            self.assertIn("agenticplug login", str(ctx.exception))
            self.assertIn("ecocoder-cluster.md", str(ctx.exception))

    @patch("sources.llm_provider.load_session_or_none", return_value=None)
    @patch("sources.llm_provider.load_dotenv")
    @patch("sources.llm_provider.pretty_print")
    def test_model_not_found_404(self, _pp, _env, _sess):
        from sources.llm_provider import Provider
        p = Provider("ecocoder_cluster", "ecocoder", server_address="127.0.0.1:8080", is_local=False)

        with patch("sources.llm_provider.OpenAI") as MockOpenAI:
            mock_client = MagicMock()
            mock_client.chat.completions.create.side_effect = Exception("404 model not found")
            MockOpenAI.return_value = mock_client

            with self.assertRaises(Exception) as ctx:
                p.ecocoder_cluster_fn([{"role": "user", "content": "test"}])
            self.assertIn("ollama pull ecocoder", str(ctx.exception))
            self.assertIn("ecocoder-cluster.md", str(ctx.exception))

    @patch("sources.llm_provider.load_session_or_none", return_value=None)
    @patch("sources.llm_provider.load_dotenv")
    @patch("sources.llm_provider.pretty_print")
    def test_connection_refused(self, _pp, _env, _sess):
        from sources.llm_provider import Provider
        p = Provider("ecocoder_cluster", "ecocoder", server_address="127.0.0.1:8080", is_local=False)

        with patch("sources.llm_provider.OpenAI") as MockOpenAI:
            mock_client = MagicMock()
            mock_client.chat.completions.create.side_effect = Exception("Connection refused")
            MockOpenAI.return_value = mock_client

            with self.assertRaises(Exception) as ctx:
                p.ecocoder_cluster_fn([{"role": "user", "content": "test"}])
            self.assertIn("gateway connection failed", str(ctx.exception).lower())
            self.assertIn("ecocoder-cluster.md", str(ctx.exception))

    @patch("sources.llm_provider.load_session_or_none", return_value=None)
    @patch("sources.llm_provider.load_dotenv")
    @patch("sources.llm_provider.pretty_print")
    def test_connect_error(self, _pp, _env, _sess):
        from sources.llm_provider import Provider
        p = Provider("ecocoder_cluster", "ecocoder", server_address="127.0.0.1:8080", is_local=False)

        with patch("sources.llm_provider.OpenAI") as MockOpenAI:
            mock_client = MagicMock()
            mock_client.chat.completions.create.side_effect = Exception("ConnectError: network unreachable")
            MockOpenAI.return_value = mock_client

            with self.assertRaises(Exception) as ctx:
                p.ecocoder_cluster_fn([{"role": "user", "content": "test"}])
            self.assertIn("gateway connection failed", str(ctx.exception).lower())

    @patch("sources.llm_provider.load_session_or_none", return_value=None)
    @patch("sources.llm_provider.load_dotenv")
    @patch("sources.llm_provider.pretty_print")
    def test_unexpected_error_reraises(self, _pp, _env, _sess):
        from sources.llm_provider import Provider
        p = Provider("ecocoder_cluster", "ecocoder", server_address="127.0.0.1:8080", is_local=False)

        with patch("sources.llm_provider.OpenAI") as MockOpenAI:
            mock_client = MagicMock()
            mock_client.chat.completions.create.side_effect = RuntimeError("GPU OOM on cluster")
            MockOpenAI.return_value = mock_client

            with self.assertRaises(Exception) as ctx:
                p.ecocoder_cluster_fn([{"role": "user", "content": "test"}])
            self.assertIn("GPU OOM on cluster", str(ctx.exception))

    @patch("sources.llm_provider.load_session_or_none", return_value=None)
    @patch("sources.llm_provider.load_dotenv")
    @patch("sources.llm_provider.pretty_print")
    def test_empty_response_raises(self, _pp, _env, _sess):
        from sources.llm_provider import Provider
        p = Provider("ecocoder_cluster", "ecocoder", server_address="127.0.0.1:8080", is_local=False)

        with patch("sources.llm_provider.OpenAI") as MockOpenAI:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = None
            MockOpenAI.return_value = mock_client

            with self.assertRaises(Exception) as ctx:
                p.ecocoder_cluster_fn([{"role": "user", "content": "test"}])
            self.assertIn("empty response", str(ctx.exception).lower())


class TestEcoCoderClusterSuccess(unittest.TestCase):
    """Successful response assembly."""

    @patch("sources.llm_provider.load_session_or_none", return_value=None)
    @patch("sources.llm_provider.load_dotenv")
    @patch("sources.llm_provider.pretty_print")
    def test_successful_response(self, _pp, _env, _sess):
        from sources.llm_provider import Provider
        p = Provider("ecocoder_cluster", "ecocoder", server_address="127.0.0.1:8080", is_local=False)

        with patch("sources.llm_provider.OpenAI") as MockOpenAI:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]
            mock_response.choices[0].message.content = "def shannon_diversity(counts): pass"
            mock_client.chat.completions.create.return_value = mock_response
            MockOpenAI.return_value = mock_client

            result = p.ecocoder_cluster_fn([{"role": "user", "content": "test"}])
            self.assertEqual(result, "def shannon_diversity(counts): pass")

    @patch("sources.llm_provider.load_session_or_none", return_value=None)
    @patch("sources.llm_provider.load_dotenv")
    @patch("sources.llm_provider.pretty_print")
    def test_verbose_mode_prints(self, _pp, _env, _sess):
        from sources.llm_provider import Provider
        p = Provider("ecocoder_cluster", "ecocoder", server_address="127.0.0.1:8080", is_local=False)

        with patch("sources.llm_provider.OpenAI") as MockOpenAI:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]
            mock_response.choices[0].message.content = "hello"
            mock_client.chat.completions.create.return_value = mock_response
            MockOpenAI.return_value = mock_client

            with patch("builtins.print") as mock_print:
                result = p.ecocoder_cluster_fn(
                    [{"role": "user", "content": "test"}], verbose=True
                )
                mock_print.assert_called_with("hello")
            self.assertEqual(result, "hello")

    @patch("sources.llm_provider.pretty_print")
    def test_session_token_used_as_api_key(self, _pp):
        from sources.llm_provider import Provider
        p = Provider("ecocoder_cluster", "ecocoder", server_address="127.0.0.1:8080", is_local=False)
        session = _mock_session(token="my-secret-token")

        with patch("sources.llm_provider.load_session_or_none", return_value=session), \
             patch("sources.llm_provider.load_dotenv"), \
             patch.dict("os.environ", {}, clear=True), \
             patch("sources.llm_provider.OpenAI") as MockOpenAI:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]
            mock_response.choices[0].message.content = "ok"
            mock_client.chat.completions.create.return_value = mock_response
            MockOpenAI.return_value = mock_client

            p.ecocoder_cluster_fn([{"role": "user", "content": "test"}])
            openai_kwargs = MockOpenAI.call_args[1]
            self.assertEqual(openai_kwargs["api_key"], "my-secret-token")


class TestExistingProvidersStillWork(unittest.TestCase):
    """No regressions on existing providers."""

    @patch("sources.llm_provider.pretty_print")
    def test_ollama_still_available(self, _pp):
        from sources.llm_provider import Provider
        p = Provider("ollama", "deepseek-r1:14b", server_address="127.0.0.1:11434", is_local=True)
        self.assertIn("ollama", p.available_providers)

    @patch("sources.llm_provider.pretty_print")
    def test_agenticplug_still_available(self, _pp):
        from sources.llm_provider import Provider
        p = Provider("agenticplug", "hermes", server_address="127.0.0.1:8080", is_local=False)
        self.assertIn("agenticplug", p.available_providers)

    @patch("sources.llm_provider.pretty_print")
    def test_ecocoder_local_still_available(self, _pp):
        from sources.llm_provider import Provider
        p = Provider("ecocoder_local", "ecocoder", server_address="127.0.0.1:11434", is_local=True)
        self.assertIn("ecocoder_local", p.available_providers)

    @patch("sources.llm_provider.pretty_print")
    def test_test_provider_still_available(self, _pp):
        from sources.llm_provider import Provider
        p = Provider("test", "test", server_address="127.0.0.1:5000", is_local=True)
        self.assertIn("test", p.available_providers)


if __name__ == "__main__":
    unittest.main()
