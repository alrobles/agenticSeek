"""Tests for the ecocoder_local provider integration.

Covers:
- Provider initialization with ecocoder_local
- Ollama connection error handling (fail-closed)
- Model-not-found error handling
- Model name resolution (generic names → ecocoder)
- Streaming response assembly
- No regressions on other providers
"""

import unittest
from unittest.mock import patch, MagicMock

import httpx


class TestEcoCoderProviderInit(unittest.TestCase):
    """Provider initialization with ecocoder_local."""

    @patch("sources.llm_provider.pretty_print")
    def test_ecocoder_local_in_available_providers(self, _pp):
        from sources.llm_provider import Provider
        p = Provider("ecocoder_local", "ecocoder", server_address="127.0.0.1:11434", is_local=True)
        self.assertIn("ecocoder_local", p.available_providers)

    @patch("sources.llm_provider.pretty_print")
    def test_ecocoder_local_not_in_unsafe_providers(self, _pp):
        """EcoCoder local runs on localhost — it is NOT an unsafe cloud provider."""
        from sources.llm_provider import Provider
        p = Provider("ecocoder_local", "ecocoder", server_address="127.0.0.1:11434", is_local=True)
        self.assertNotIn("ecocoder_local", p.unsafe_providers)

    @patch("sources.llm_provider.pretty_print")
    def test_ecocoder_local_no_cloud_warning(self, mock_pp):
        """ecocoder_local should not trigger the cloud-usage warning."""
        from sources.llm_provider import Provider
        Provider("ecocoder_local", "ecocoder", server_address="127.0.0.1:11434", is_local=True)
        for call in mock_pp.call_args_list:
            self.assertNotIn("cloud", call[0][0].lower())

    @patch("sources.llm_provider.pretty_print")
    def test_ecocoder_local_no_init_print(self, mock_pp):
        """ecocoder_local should not print a generic 'initialized at' message."""
        from sources.llm_provider import Provider
        Provider("ecocoder_local", "ecocoder", server_address="127.0.0.1:11434", is_local=True)
        for call in mock_pp.call_args_list:
            self.assertNotIn("initialized at", call[0][0].lower())

    @patch("sources.llm_provider.pretty_print")
    def test_unknown_provider_raises(self, _pp):
        from sources.llm_provider import Provider
        with self.assertRaises(ValueError):
            Provider("nonexistent_provider", "model", is_local=True)


class TestEcoCoderModelResolution(unittest.TestCase):
    """Model name resolution and defaults."""

    @patch("sources.llm_provider.pretty_print")
    def test_explicit_ecocoder_model_preserved(self, _pp):
        """When model is 'ecocoder', it should stay 'ecocoder'."""
        from sources.llm_provider import Provider
        p = Provider("ecocoder_local", "ecocoder", server_address="127.0.0.1:11434", is_local=True)
        self.assertEqual(p.model, "ecocoder")

    @patch("sources.llm_provider.pretty_print")
    def test_ecocoder_latest_model_preserved(self, _pp):
        from sources.llm_provider import Provider
        p = Provider("ecocoder_local", "ecocoder:latest", server_address="127.0.0.1:11434", is_local=True)
        self.assertEqual(p.model, "ecocoder:latest")

    @patch("sources.llm_provider.pretty_print")
    def test_generic_model_resolved_at_call_time(self, _pp):
        """Generic model names like deepseek-r1:14b are resolved to ecocoder at call time."""
        from sources.llm_provider import Provider
        p = Provider("ecocoder_local", "deepseek-r1:14b", server_address="127.0.0.1:11434", is_local=True)
        # model stays as-is at init; resolution happens inside ecocoder_local_fn
        self.assertEqual(p.model, "deepseek-r1:14b")


class TestEcoCoderConnectionErrors(unittest.TestCase):
    """Ollama connection error handling — fail-closed with actionable messages."""

    @patch("sources.llm_provider.pretty_print")
    def test_connect_error_raises_with_setup_hint(self, _pp):
        from sources.llm_provider import Provider
        p = Provider("ecocoder_local", "ecocoder", server_address="127.0.0.1:11434", is_local=True)

        with patch("sources.llm_provider.OllamaClient") as MockClient:
            mock_client = MagicMock()
            mock_client.chat.side_effect = httpx.ConnectError("Connection refused")
            MockClient.return_value = mock_client

            with self.assertRaises(Exception) as ctx:
                p.ecocoder_local_fn([{"role": "user", "content": "test"}])
            self.assertIn("ollama serve", str(ctx.exception).lower())
            self.assertIn("ecocoder-local.md", str(ctx.exception))

    @patch("sources.llm_provider.pretty_print")
    def test_connection_refused_raises_with_hint(self, _pp):
        from sources.llm_provider import Provider
        p = Provider("ecocoder_local", "ecocoder", server_address="127.0.0.1:11434", is_local=True)

        with patch("sources.llm_provider.OllamaClient") as MockClient:
            mock_client = MagicMock()
            err = Exception("Connection refused by server")
            mock_client.chat.side_effect = err
            MockClient.return_value = mock_client

            with self.assertRaises(Exception) as ctx:
                p.ecocoder_local_fn([{"role": "user", "content": "test"}])
            self.assertIn("ollama serve", str(ctx.exception).lower())

    @patch("sources.llm_provider.pretty_print")
    def test_model_not_found_raises_with_pull_hint(self, _pp):
        from sources.llm_provider import Provider
        p = Provider("ecocoder_local", "ecocoder", server_address="127.0.0.1:11434", is_local=True)

        with patch("sources.llm_provider.OllamaClient") as MockClient:
            mock_client = MagicMock()
            err = Exception("model not found")
            err.status_code = 404
            mock_client.chat.side_effect = err
            MockClient.return_value = mock_client

            with self.assertRaises(Exception) as ctx:
                p.ecocoder_local_fn([{"role": "user", "content": "test"}])
            self.assertIn("ollama pull ecocoder", str(ctx.exception).lower())

    @patch("sources.llm_provider.pretty_print")
    def test_unexpected_error_reraises(self, _pp):
        from sources.llm_provider import Provider
        p = Provider("ecocoder_local", "ecocoder", server_address="127.0.0.1:11434", is_local=True)

        with patch("sources.llm_provider.OllamaClient") as MockClient:
            mock_client = MagicMock()
            mock_client.chat.side_effect = RuntimeError("GPU out of memory")
            MockClient.return_value = mock_client

            with self.assertRaises(Exception) as ctx:
                p.ecocoder_local_fn([{"role": "user", "content": "test"}])
            self.assertIn("GPU out of memory", str(ctx.exception))


class TestEcoCoderStreaming(unittest.TestCase):
    """Streaming response assembly."""

    @patch("sources.llm_provider.pretty_print")
    def test_streaming_assembles_full_response(self, _pp):
        from sources.llm_provider import Provider
        p = Provider("ecocoder_local", "ecocoder", server_address="127.0.0.1:11434", is_local=True)

        chunks = [
            {"message": {"content": "def shannon"}},
            {"message": {"content": "_diversity"}},
            {"message": {"content": "(counts):"}},
        ]

        with patch("sources.llm_provider.OllamaClient") as MockClient:
            mock_client = MagicMock()
            mock_client.chat.return_value = iter(chunks)
            MockClient.return_value = mock_client

            result = p.ecocoder_local_fn([{"role": "user", "content": "test"}])
            self.assertEqual(result, "def shannon_diversity(counts):")

    @patch("sources.llm_provider.pretty_print")
    def test_streaming_empty_response(self, _pp):
        from sources.llm_provider import Provider
        p = Provider("ecocoder_local", "ecocoder", server_address="127.0.0.1:11434", is_local=True)

        with patch("sources.llm_provider.OllamaClient") as MockClient:
            mock_client = MagicMock()
            mock_client.chat.return_value = iter([])
            MockClient.return_value = mock_client

            result = p.ecocoder_local_fn([{"role": "user", "content": "test"}])
            self.assertEqual(result, "")

    @patch("sources.llm_provider.pretty_print")
    def test_verbose_mode_prints_chunks(self, _pp):
        from sources.llm_provider import Provider
        p = Provider("ecocoder_local", "ecocoder", server_address="127.0.0.1:11434", is_local=True)

        chunks = [{"message": {"content": "hello"}}]

        with patch("sources.llm_provider.OllamaClient") as MockClient:
            mock_client = MagicMock()
            mock_client.chat.return_value = iter(chunks)
            MockClient.return_value = mock_client

            with patch("builtins.print") as mock_print:
                result = p.ecocoder_local_fn(
                    [{"role": "user", "content": "test"}], verbose=True
                )
                mock_print.assert_called_with("hello", end="", flush=True)
            self.assertEqual(result, "hello")


class TestEcoCoderModelNameAtCallTime(unittest.TestCase):
    """Model name is resolved correctly when ecocoder_local_fn is called."""

    @patch("sources.llm_provider.pretty_print")
    def test_deepseek_r1_resolved_to_ecocoder(self, _pp):
        from sources.llm_provider import Provider
        p = Provider("ecocoder_local", "deepseek-r1:14b", server_address="127.0.0.1:11434", is_local=True)

        with patch("sources.llm_provider.OllamaClient") as MockClient:
            mock_client = MagicMock()
            mock_client.chat.return_value = iter([{"message": {"content": "ok"}}])
            MockClient.return_value = mock_client

            p.ecocoder_local_fn([{"role": "user", "content": "test"}])
            call_args = mock_client.chat.call_args
            self.assertEqual(call_args[1]["model"], "ecocoder")

    @patch("sources.llm_provider.pretty_print")
    def test_deepseek_chat_resolved_to_ecocoder(self, _pp):
        from sources.llm_provider import Provider
        p = Provider("ecocoder_local", "deepseek-chat", server_address="127.0.0.1:11434", is_local=True)

        with patch("sources.llm_provider.OllamaClient") as MockClient:
            mock_client = MagicMock()
            mock_client.chat.return_value = iter([{"message": {"content": "ok"}}])
            MockClient.return_value = mock_client

            p.ecocoder_local_fn([{"role": "user", "content": "test"}])
            call_args = mock_client.chat.call_args
            self.assertEqual(call_args[1]["model"], "ecocoder")

    @patch("sources.llm_provider.pretty_print")
    def test_explicit_ecocoder_stays_ecocoder(self, _pp):
        from sources.llm_provider import Provider
        p = Provider("ecocoder_local", "ecocoder", server_address="127.0.0.1:11434", is_local=True)

        with patch("sources.llm_provider.OllamaClient") as MockClient:
            mock_client = MagicMock()
            mock_client.chat.return_value = iter([{"message": {"content": "ok"}}])
            MockClient.return_value = mock_client

            p.ecocoder_local_fn([{"role": "user", "content": "test"}])
            call_args = mock_client.chat.call_args
            self.assertEqual(call_args[1]["model"], "ecocoder")

    @patch("sources.llm_provider.pretty_print")
    def test_custom_model_name_preserved(self, _pp):
        """A user-specified model like 'ecocoder:7b' should not be overridden."""
        from sources.llm_provider import Provider
        p = Provider("ecocoder_local", "ecocoder:7b", server_address="127.0.0.1:11434", is_local=True)

        with patch("sources.llm_provider.OllamaClient") as MockClient:
            mock_client = MagicMock()
            mock_client.chat.return_value = iter([{"message": {"content": "ok"}}])
            MockClient.return_value = mock_client

            p.ecocoder_local_fn([{"role": "user", "content": "test"}])
            call_args = mock_client.chat.call_args
            self.assertEqual(call_args[1]["model"], "ecocoder:7b")


class TestEcoCoderModelValidation(unittest.TestCase):
    """Model name validation warns on unrecognized variants."""

    @patch("sources.llm_provider.pretty_print")
    def test_recognized_model_no_warning(self, mock_pp):
        from sources.llm_provider import Provider
        p = Provider("ecocoder_local", "ecocoder", server_address="127.0.0.1:11434", is_local=True)

        with patch("sources.llm_provider.OllamaClient") as MockClient:
            mock_client = MagicMock()
            mock_client.chat.return_value = iter([{"message": {"content": "ok"}}])
            MockClient.return_value = mock_client

            p.ecocoder_local_fn([{"role": "user", "content": "test"}])
            # No warning should be emitted for recognized model
            for call in mock_pp.call_args_list:
                if call[0] and "not a recognized" in str(call[0][0]):
                    self.fail("Unexpected warning for recognized model 'ecocoder'")

    @patch("sources.llm_provider.pretty_print")
    def test_unrecognized_model_emits_warning(self, mock_pp):
        from sources.llm_provider import Provider
        p = Provider("ecocoder_local", "my-custom-model", server_address="127.0.0.1:11434", is_local=True)

        with patch("sources.llm_provider.OllamaClient") as MockClient:
            mock_client = MagicMock()
            mock_client.chat.return_value = iter([{"message": {"content": "ok"}}])
            MockClient.return_value = mock_client

            p.ecocoder_local_fn([{"role": "user", "content": "test"}])
            warning_found = any(
                "not a recognized" in str(call[0][0])
                for call in mock_pp.call_args_list
                if call[0]
            )
            self.assertTrue(warning_found, "Expected warning for unrecognized model")

    @patch("sources.llm_provider.pretty_print")
    def test_generic_alias_resolved_no_warning(self, mock_pp):
        """Generic aliases like deepseek-r1:7b should resolve to ecocoder without warning."""
        from sources.llm_provider import Provider
        p = Provider("ecocoder_local", "deepseek-r1:7b", server_address="127.0.0.1:11434", is_local=True)

        with patch("sources.llm_provider.OllamaClient") as MockClient:
            mock_client = MagicMock()
            mock_client.chat.return_value = iter([{"message": {"content": "ok"}}])
            MockClient.return_value = mock_client

            p.ecocoder_local_fn([{"role": "user", "content": "test"}])
            call_args = mock_client.chat.call_args
            self.assertEqual(call_args[1]["model"], "ecocoder")

    @patch("sources.llm_provider.pretty_print")
    def test_qwen_alias_resolved_to_ecocoder(self, _pp):
        from sources.llm_provider import Provider
        p = Provider("ecocoder_local", "qwen2.5-coder", server_address="127.0.0.1:11434", is_local=True)

        with patch("sources.llm_provider.OllamaClient") as MockClient:
            mock_client = MagicMock()
            mock_client.chat.return_value = iter([{"message": {"content": "ok"}}])
            MockClient.return_value = mock_client

            p.ecocoder_local_fn([{"role": "user", "content": "test"}])
            call_args = mock_client.chat.call_args
            self.assertEqual(call_args[1]["model"], "ecocoder")

    @patch("sources.llm_provider.pretty_print")
    def test_unrecognized_model_still_passed_to_ollama(self, _pp):
        """Unrecognized models proceed (just with a warning) — not blocked."""
        from sources.llm_provider import Provider
        p = Provider("ecocoder_local", "my-custom-model", server_address="127.0.0.1:11434", is_local=True)

        with patch("sources.llm_provider.OllamaClient") as MockClient:
            mock_client = MagicMock()
            mock_client.chat.return_value = iter([{"message": {"content": "ok"}}])
            MockClient.return_value = mock_client

            result = p.ecocoder_local_fn([{"role": "user", "content": "test"}])
            call_args = mock_client.chat.call_args
            self.assertEqual(call_args[1]["model"], "my-custom-model")
            self.assertEqual(result, "ok")


class TestEcoCoderHostResolution(unittest.TestCase):
    """Host URL construction for local vs remote."""

    @patch("sources.llm_provider.pretty_print")
    def test_local_host_uses_internal_url(self, _pp):
        from sources.llm_provider import Provider
        p = Provider("ecocoder_local", "ecocoder", server_address="127.0.0.1:11434", is_local=True)

        with patch("sources.llm_provider.OllamaClient") as MockClient:
            mock_client = MagicMock()
            mock_client.chat.return_value = iter([{"message": {"content": "ok"}}])
            MockClient.return_value = mock_client

            p.ecocoder_local_fn([{"role": "user", "content": "test"}])
            host_arg = MockClient.call_args[1].get("host") or MockClient.call_args[0][0]
            self.assertIn("11434", host_arg)

    @patch("sources.llm_provider.pretty_print")
    def test_remote_host_uses_http_prefix(self, _pp):
        from sources.llm_provider import Provider
        p = Provider("ecocoder_local", "ecocoder", server_address="192.168.1.100:11434", is_local=False)

        with patch("sources.llm_provider.OllamaClient") as MockClient:
            mock_client = MagicMock()
            mock_client.chat.return_value = iter([{"message": {"content": "ok"}}])
            MockClient.return_value = mock_client

            p.ecocoder_local_fn([{"role": "user", "content": "test"}])
            host_arg = MockClient.call_args[1].get("host") or MockClient.call_args[0][0]
            self.assertTrue(host_arg.startswith("http://"))
            self.assertIn("192.168.1.100:11434", host_arg)


class TestExistingProvidersUnchanged(unittest.TestCase):
    """Regression: existing providers must still initialize."""

    @patch("sources.llm_provider.pretty_print")
    def test_ollama_still_available(self, _pp):
        from sources.llm_provider import Provider
        p = Provider("ollama", "deepseek-r1:14b", server_address="127.0.0.1:11434", is_local=True)
        self.assertIn("ollama", p.available_providers)

    @patch("sources.llm_provider.pretty_print")
    def test_test_provider_still_available(self, _pp):
        from sources.llm_provider import Provider
        p = Provider("test", "test-model", server_address="127.0.0.1:5000", is_local=True)
        self.assertIn("test", p.available_providers)


if __name__ == "__main__":
    unittest.main()
