import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sources.agenticplug_session import (
    AgenticPlugSession,
    AgenticPlugSessionError,
    default_session_path,
    load_session,
    load_session_or_none,
)


class TestAgenticPlugSession(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "session.json"

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, payload):
        self.path.write_text(json.dumps(payload))

    def test_default_path_uses_env_override(self):
        with patch.dict(os.environ, {"AGENTICPLUG_SESSION_FILE": "/tmp/custom.json"}):
            self.assertEqual(default_session_path(), Path("/tmp/custom.json"))

    def test_default_path_falls_back_to_home(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AGENTICPLUG_SESSION_FILE", None)
            self.assertEqual(
                default_session_path(),
                Path.home() / ".config" / "agenticplug" / "session.json",
            )

    def test_load_session_parses_full_payload(self):
        self._write({
            "base_url": "https://gw.example.com/v1",
            "token": "ghp_xxx",
            "token_type": "Bearer",
            "expires_at": "2099-01-01T00:00:00Z",
            "user": {"login": "octocat", "id": 1},
            "scopes": ["read:user"],
            "route_header": "hermes",
            "model": "hermes",
            "default_cluster": "ku-hpc",
        })
        session = load_session(self.path)
        self.assertEqual(session.base_url, "https://gw.example.com/v1")
        self.assertEqual(session.token, "ghp_xxx")
        self.assertEqual(session.identity, "octocat")
        self.assertEqual(session.scopes, ["read:user"])
        self.assertEqual(session.route_header, "hermes")
        self.assertEqual(session.default_cluster, "ku-hpc")
        self.assertEqual(session.authorization_header(), "Bearer ghp_xxx")
        self.assertFalse(session.is_expired())

    def test_load_session_missing_file_raises_with_hint(self):
        missing = self.path.parent / "nope.json"
        with self.assertRaises(AgenticPlugSessionError) as ctx:
            load_session(missing)
        self.assertIn("agenticplug login", str(ctx.exception))

    def test_load_session_invalid_json_raises(self):
        self.path.write_text("{ not json")
        with self.assertRaises(AgenticPlugSessionError) as ctx:
            load_session(self.path)
        self.assertIn("not valid JSON", str(ctx.exception))

    def test_load_session_wrong_type_raises(self):
        self.path.write_text(json.dumps(["a", "list"]))
        with self.assertRaises(AgenticPlugSessionError):
            load_session(self.path)

    def test_load_session_or_none_returns_none_when_missing(self):
        self.assertIsNone(load_session_or_none(self.path.parent / "absent.json"))

    def test_load_session_or_none_propagates_corruption(self):
        self.path.write_text("{ bad")
        with self.assertRaises(AgenticPlugSessionError):
            load_session_or_none(self.path)

    def test_is_expired_true_for_past(self):
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        self._write({"expires_at": past})
        self.assertTrue(load_session(self.path).is_expired())

    def test_is_expired_false_when_no_expiry(self):
        self._write({"token": "x"})
        self.assertFalse(load_session(self.path).is_expired())

    def test_unknown_fields_preserved_in_raw(self):
        self._write({"token": "x", "future_field": 42})
        session = load_session(self.path)
        self.assertEqual(session.raw.get("future_field"), 42)


class TestProviderConsumesSession(unittest.TestCase):
    """The provider should fall back to session-file values when env is unset."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "session.json"
        self.path.write_text(json.dumps({
            "base_url": "https://gw.example.com/v1",
            "token": "session-token",
            "route_header": "hermes-from-session",
        }))

    def tearDown(self):
        self.tmp.cleanup()

    def _clean_env(self):
        for var in ("AGENTICPLUG_BASE_URL", "AGENTICPLUG_API_KEY",
                    "AGENTICPLUG_MODEL", "AGENTICPLUG_ROUTE_HEADER"):
            os.environ.pop(var, None)

    @patch('sources.llm_provider.OpenAI')
    def test_session_supplies_base_url_token_and_route(self, mock_openai_class):
        self._clean_env()
        os.environ["AGENTICPLUG_SESSION_FILE"] = str(self.path)
        try:
            mock_client = MagicMock()
            mock_openai_class.return_value = mock_client
            mock_client.chat.completions.create.return_value = MagicMock(
                choices=[MagicMock(message=MagicMock(content="ok"))]
            )

            from sources.llm_provider import Provider
            provider = Provider("agenticplug", "hermes",
                                server_address="127.0.0.1:8080", is_local=True)
            provider.agenticplug_fn([{"role": "user", "content": "hi"}])

            kwargs = mock_openai_class.call_args.kwargs
            self.assertEqual(kwargs["base_url"], "https://gw.example.com/v1")
            self.assertEqual(kwargs["api_key"], "session-token")
            self.assertEqual(
                kwargs["default_headers"],
                {"X-AgenticPlug-Route": "hermes-from-session"},
            )
        finally:
            os.environ.pop("AGENTICPLUG_SESSION_FILE", None)

    @patch('sources.llm_provider.OpenAI')
    def test_env_overrides_session(self, mock_openai_class):
        self._clean_env()
        os.environ["AGENTICPLUG_SESSION_FILE"] = str(self.path)
        os.environ["AGENTICPLUG_BASE_URL"] = "http://127.0.0.1:9999/v1"
        os.environ["AGENTICPLUG_API_KEY"] = "env-token"
        try:
            mock_client = MagicMock()
            mock_openai_class.return_value = mock_client
            mock_client.chat.completions.create.return_value = MagicMock(
                choices=[MagicMock(message=MagicMock(content="ok"))]
            )

            from sources.llm_provider import Provider
            provider = Provider("agenticplug", "hermes",
                                server_address="127.0.0.1:8080", is_local=True)
            provider.agenticplug_fn([{"role": "user", "content": "hi"}])

            kwargs = mock_openai_class.call_args.kwargs
            self.assertEqual(kwargs["base_url"], "http://127.0.0.1:9999/v1")
            self.assertEqual(kwargs["api_key"], "env-token")
        finally:
            for var in ("AGENTICPLUG_SESSION_FILE",
                        "AGENTICPLUG_BASE_URL", "AGENTICPLUG_API_KEY"):
                os.environ.pop(var, None)


class TestModelPrecedence(unittest.TestCase):
    """Regression: ``model`` must follow env → session → config (self.model).

    Earlier versions resolved ``self.model`` before the session, which meant a
    session-supplied model could never take effect when config.ini also set
    ``provider_model`` (which it always does). The docs promise the order
    above; this suite locks it in.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "session.json"

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, payload):
        self.path.write_text(json.dumps(payload))

    def _clean_env(self):
        for var in ("AGENTICPLUG_BASE_URL", "AGENTICPLUG_API_KEY",
                    "AGENTICPLUG_MODEL", "AGENTICPLUG_ROUTE_HEADER",
                    "AGENTICPLUG_SESSION_FILE"):
            os.environ.pop(var, None)

    def _run(self, mock_openai_class):
        mock_client = MagicMock()
        mock_openai_class.return_value = mock_client
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="ok"))]
        )
        from sources.llm_provider import Provider
        provider = Provider("agenticplug", "config-model",
                            server_address="127.0.0.1:8080", is_local=True)
        provider.agenticplug_fn([{"role": "user", "content": "hi"}])
        return mock_client.chat.completions.create.call_args.kwargs["model"]

    @patch('sources.llm_provider.OpenAI')
    def test_env_model_wins_over_session_and_config(self, mock_openai_class):
        self._clean_env()
        self._write({"model": "session-model"})
        os.environ["AGENTICPLUG_SESSION_FILE"] = str(self.path)
        os.environ["AGENTICPLUG_MODEL"] = "env-model"
        try:
            self.assertEqual(self._run(mock_openai_class), "env-model")
        finally:
            self._clean_env()

    @patch('sources.llm_provider.OpenAI')
    def test_session_model_wins_over_config_when_env_unset(self, mock_openai_class):
        self._clean_env()
        self._write({"model": "session-model"})
        os.environ["AGENTICPLUG_SESSION_FILE"] = str(self.path)
        try:
            self.assertEqual(self._run(mock_openai_class), "session-model")
        finally:
            self._clean_env()

    @patch('sources.llm_provider.OpenAI')
    def test_config_model_used_when_env_and_session_unset(self, mock_openai_class):
        self._clean_env()
        self._write({})  # session present but no model field
        os.environ["AGENTICPLUG_SESSION_FILE"] = str(self.path)
        try:
            self.assertEqual(self._run(mock_openai_class), "config-model")
        finally:
            self._clean_env()

    @patch('sources.llm_provider.OpenAI')
    def test_config_model_used_when_no_session_file(self, mock_openai_class):
        self._clean_env()
        os.environ["AGENTICPLUG_SESSION_FILE"] = str(self.path.parent / "nope.json")
        try:
            self.assertEqual(self._run(mock_openai_class), "config-model")
        finally:
            self._clean_env()


class TestSmokeRedaction(unittest.TestCase):
    """The smoke script must not echo bearer tokens, even in --json output."""

    def test_redact_replaces_token_fields_recursively(self):
        sys.path.insert(0, os.path.abspath(
            os.path.join(os.path.dirname(__file__), '..', 'scripts')))
        from agenticplug_smoke import _redact, _REDACTED_PLACEHOLDER

        payload = {
            "identity": {"login": "octocat", "access_token": "gho_xxx"},
            "ls": {"entries": [{"name": "a"}, {"name": "b"}]},
            "nested": [{"token": "secret"}, {"safe": "ok"}],
            "top_token": "should-not-be-redacted-top-level-unknown-key",
        }
        out = _redact(payload)
        self.assertEqual(out["identity"]["login"], "octocat")
        self.assertEqual(out["identity"]["access_token"], _REDACTED_PLACEHOLDER)
        self.assertEqual(out["nested"][0]["token"], _REDACTED_PLACEHOLDER)
        self.assertEqual(out["nested"][1]["safe"], "ok")
        # Non-credential keys are left alone.
        self.assertEqual(out["top_token"], "should-not-be-redacted-top-level-unknown-key")
        # Original payload is not mutated.
        self.assertEqual(payload["identity"]["access_token"], "gho_xxx")


if __name__ == "__main__":
    unittest.main()
