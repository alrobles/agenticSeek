"""Tests for sources.keystore — secure local key storage (ADR-004).

All tests use the file backend with a temporary directory so they run
in CI without an OS keychain.  The keyring backend is tested via a
mock to avoid platform-specific setup.
"""

import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import sources.keystore as ks


class _TempKeystoreMixin:
    """Redirect keystore to a temporary directory and force file backend."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._orig_config_dir = ks._CONFIG_DIR
        self._orig_keys_file = ks._KEYS_FILE
        self._orig_use_keyring = ks._USE_KEYRING

        ks._CONFIG_DIR = Path(self.tmp.name) / "ecoseek"
        ks._KEYS_FILE = ks._CONFIG_DIR / "keys.json"
        ks._USE_KEYRING = False  # force file backend

    def tearDown(self):
        ks._CONFIG_DIR = self._orig_config_dir
        ks._KEYS_FILE = self._orig_keys_file
        ks._USE_KEYRING = self._orig_use_keyring
        self.tmp.cleanup()


class TestStoreAndRetrieve(_TempKeystoreMixin, unittest.TestCase):

    def test_store_and_get_roundtrip(self):
        ks.store_key("test_key", "secret-value-123")
        self.assertEqual(ks.get_key("test_key"), "secret-value-123")

    def test_get_missing_returns_none(self):
        self.assertIsNone(ks.get_key("nonexistent"))

    def test_store_overwrites_existing(self):
        ks.store_key("k", "v1")
        ks.store_key("k", "v2")
        self.assertEqual(ks.get_key("k"), "v2")

    def test_delete_removes_key(self):
        ks.store_key("k", "v")
        ks.delete_key("k")
        self.assertIsNone(ks.get_key("k"))

    def test_delete_missing_is_noop(self):
        ks.delete_key("never-existed")

    def test_list_keys(self):
        ks.store_key("a", "1")
        ks.store_key("b", "2")
        names = ks.list_keys()
        self.assertIn("a", names)
        self.assertIn("b", names)

    def test_list_keys_empty(self):
        self.assertEqual(ks.list_keys(), [])


class TestValidation(_TempKeystoreMixin, unittest.TestCase):

    def test_empty_name_raises(self):
        with self.assertRaises(ValueError):
            ks.store_key("", "value")

    def test_whitespace_name_raises(self):
        with self.assertRaises(ValueError):
            ks.store_key("   ", "value")

    def test_empty_value_raises(self):
        with self.assertRaises(ValueError):
            ks.store_key("name", "")

    def test_whitespace_value_raises(self):
        with self.assertRaises(ValueError):
            ks.store_key("name", "   ")

    def test_name_is_stripped(self):
        ks.store_key("  padded  ", "val")
        self.assertEqual(ks.get_key("padded"), "val")

    def test_value_is_stripped(self):
        ks.store_key("k", "  spaced  ")
        self.assertEqual(ks.get_key("k"), "spaced")


class TestFilePermissions(_TempKeystoreMixin, unittest.TestCase):

    def test_keys_file_is_0600(self):
        ks.store_key("k", "v")
        mode = ks._KEYS_FILE.stat().st_mode
        self.assertEqual(stat.S_IMODE(mode), 0o600)

    def test_config_dir_is_0700(self):
        ks.store_key("k", "v")
        mode = ks._CONFIG_DIR.stat().st_mode
        self.assertEqual(stat.S_IMODE(mode), 0o700)


class TestEncryptionRoundtrip(_TempKeystoreMixin, unittest.TestCase):

    def test_raw_file_is_not_plaintext(self):
        ks.store_key("secret", "my-api-key-12345")
        raw = json.loads(ks._KEYS_FILE.read_text())
        self.assertNotEqual(raw.get("secret"), "my-api-key-12345")

    def test_decrypt_recovers_original(self):
        token = ks._encrypt("hello-world")
        self.assertEqual(ks._decrypt(token), "hello-world")

    def test_stored_value_is_not_base64_reversible(self):
        """Regression test for issue #30.

        Earlier behavior fell back to base64 silently when
        ``cryptography`` was unavailable, which is trivially
        reversible. After the fix, the stored token must not decode
        to the original plaintext via base64.
        """
        plaintext = "sk-deepseek-secret-very-distinct-1234567890"
        ks.store_key("dsk", plaintext)
        token = json.loads(ks._KEYS_FILE.read_text())["dsk"]

        # The token must not be empty and must not equal the plaintext.
        self.assertTrue(token)
        self.assertNotEqual(token, plaintext)

        # Plain urlsafe-base64 decode of the token must not yield the
        # plaintext bytes. Fernet output starts with a version byte
        # (0x80) and contains a 128-bit IV and HMAC; base64-decoding
        # it produces binary noise, not the original secret.
        import base64 as _b64
        try:
            decoded = _b64.urlsafe_b64decode(token.encode())
        except Exception:
            decoded = b""
        self.assertNotIn(plaintext.encode(), decoded)

        # Standard base64 alphabet (non-urlsafe) must also not reverse.
        try:
            decoded_std = _b64.b64decode(token.encode(), validate=False)
        except Exception:
            decoded_std = b""
        self.assertNotIn(plaintext.encode(), decoded_std)


class TestCryptoUnavailableFailsClosed(_TempKeystoreMixin, unittest.TestCase):
    """Regression test for issue #30: no silent base64 fallback.

    When the ``cryptography`` package is missing, the keystore must
    raise ``KeystoreCryptoUnavailable`` rather than silently writing
    base64-encoded plaintext.
    """

    def test_encrypt_raises_when_cryptography_missing(self):
        with patch('sources.keystore._require_fernet',
                   side_effect=ks.KeystoreCryptoUnavailable(ks._CRYPTO_INSTALL_MSG)):
            with self.assertRaises(ks.KeystoreCryptoUnavailable):
                ks._encrypt("anything")

    def test_decrypt_raises_when_cryptography_missing(self):
        with patch('sources.keystore._require_fernet',
                   side_effect=ks.KeystoreCryptoUnavailable(ks._CRYPTO_INSTALL_MSG)):
            with self.assertRaises(ks.KeystoreCryptoUnavailable):
                ks._decrypt("anything")

    def test_store_key_raises_when_cryptography_missing(self):
        with patch('sources.keystore._require_fernet',
                   side_effect=ks.KeystoreCryptoUnavailable(ks._CRYPTO_INSTALL_MSG)):
            with self.assertRaises(ks.KeystoreCryptoUnavailable):
                ks.store_key("name", "value")

    def test_error_message_is_actionable(self):
        msg = ks._CRYPTO_INSTALL_MSG
        self.assertIn("cryptography", msg.lower())
        self.assertIn("pip install", msg)

    def test_require_fernet_translates_importerror(self):
        """Simulate ImportError at the cryptography import site."""
        import builtins
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "cryptography.fernet" or name.startswith("cryptography"):
                raise ImportError("No module named 'cryptography'")
            return real_import(name, *args, **kwargs)

        with patch.object(builtins, '__import__', side_effect=fake_import):
            with self.assertRaises(ks.KeystoreCryptoUnavailable):
                ks._require_fernet()


class TestCorruptedFile(_TempKeystoreMixin, unittest.TestCase):

    def test_corrupted_json_returns_empty(self):
        ks._ensure_config_dir()
        ks._KEYS_FILE.write_text("{ not json")
        self.assertEqual(ks.list_keys(), [])
        self.assertIsNone(ks.get_key("anything"))

    def test_non_dict_json_returns_empty(self):
        ks._ensure_config_dir()
        ks._KEYS_FILE.write_text(json.dumps(["a", "list"]))
        self.assertEqual(ks.list_keys(), [])

    def test_corrupted_value_returns_none(self):
        ks._ensure_config_dir()
        ks._KEYS_FILE.write_text(json.dumps({"k": "not-a-valid-encrypted-token!@#"}))
        self.assertIsNone(ks.get_key("k"))


class TestRedact(unittest.TestCase):

    def test_redact_long_key(self):
        result = ks.redact("sk-abc123456789")
        self.assertTrue(result.endswith("6789"))
        self.assertNotIn("abc", result)

    def test_redact_short_key(self):
        result = ks.redact("abc")
        self.assertEqual(result, ks._REDACTED)

    def test_redact_empty(self):
        self.assertEqual(ks.redact(""), ks._REDACTED)

    def test_redact_none_like(self):
        self.assertEqual(ks.redact(""), ks._REDACTED)


class TestDeepSeekKeyResolution(_TempKeystoreMixin, unittest.TestCase):

    def test_env_var_wins_over_keystore(self):
        ks.store_key("deepseek_api_key", "keystore-key")
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "env-key"}):
            self.assertEqual(ks.get_deepseek_key(), "env-key")

    def test_keystore_used_when_env_unset(self):
        ks.store_key("deepseek_api_key", "keystore-key")
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DEEPSEEK_API_KEY", None)
            self.assertEqual(ks.get_deepseek_key(), "keystore-key")

    def test_placeholder_env_var_ignored(self):
        ks.store_key("deepseek_api_key", "real-key")
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "xxxxx"}):
            self.assertEqual(ks.get_deepseek_key(), "real-key")

    def test_returns_none_when_nothing_set(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DEEPSEEK_API_KEY", None)
            self.assertIsNone(ks.get_deepseek_key())

    def test_store_and_delete_deepseek_key(self):
        ks.store_deepseek_key("test-key")
        self.assertEqual(ks.get_key("deepseek_api_key"), "test-key")
        ks.delete_deepseek_key()
        self.assertIsNone(ks.get_key("deepseek_api_key"))


class TestKeyringBackendMock(unittest.TestCase):
    """Verify the keyring codepath using mocks."""

    def setUp(self):
        self._orig_use_keyring = ks._USE_KEYRING

    def tearDown(self):
        ks._USE_KEYRING = self._orig_use_keyring

    @patch('sources.keystore._keyring_store')
    @patch('sources.keystore._keyring_available', return_value=True)
    def test_store_uses_keyring_when_available(self, mock_avail, mock_store):
        ks._USE_KEYRING = None  # force re-detection
        ks.store_key("k", "v")
        mock_store.assert_called_once_with("k", "v")

    @patch('sources.keystore._keyring_get', return_value="from-keyring")
    @patch('sources.keystore._keyring_available', return_value=True)
    def test_get_uses_keyring_when_available(self, mock_avail, mock_get):
        ks._USE_KEYRING = None
        result = ks.get_key("k")
        self.assertEqual(result, "from-keyring")
        mock_get.assert_called_once_with("k")


class TestDeepSeekBYOKProvider(_TempKeystoreMixin, unittest.TestCase):
    """Verify the deepseek_byok provider uses the keystore."""

    @patch('sources.llm_provider.OpenAI')
    def test_byok_provider_reads_from_keystore(self, mock_openai_class):
        ks.store_key("deepseek_api_key", "sk-test-byok-key")
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DEEPSEEK_API_KEY", None)

            mock_client = MagicMock()
            mock_openai_class.return_value = mock_client
            mock_client.chat.completions.create.return_value = MagicMock(
                choices=[MagicMock(message=MagicMock(content="hello from deepseek"))]
            )

            from sources.llm_provider import Provider
            provider = Provider("deepseek_byok", "deepseek-chat",
                                server_address="127.0.0.1:11434", is_local=True)
            result = provider.deepseek_byok_fn(
                [{"role": "user", "content": "test"}]
            )

            self.assertEqual(result, "hello from deepseek")
            kwargs = mock_openai_class.call_args.kwargs
            self.assertEqual(kwargs["api_key"], "sk-test-byok-key")
            self.assertEqual(kwargs["base_url"], "https://api.deepseek.com")

    def test_byok_provider_raises_when_no_key(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DEEPSEEK_API_KEY", None)

            from sources.llm_provider import Provider
            provider = Provider("deepseek_byok", "deepseek-chat",
                                server_address="127.0.0.1:11434", is_local=True)
            with self.assertRaises(Exception) as ctx:
                provider.deepseek_byok_fn(
                    [{"role": "user", "content": "test"}]
                )
            self.assertIn("BYOK key not found", str(ctx.exception))
            self.assertIn("ecoseek keys set deepseek", str(ctx.exception))

    @patch('sources.llm_provider.OpenAI')
    def test_deepseek_fn_also_checks_keystore(self, mock_openai_class):
        """deepseek_fn should prefer keystore over self.api_key."""
        ks.store_key("deepseek_api_key", "sk-from-keystore")
        # Provider.__init__ calls get_api_key() which needs env var for
        # non-BYOK deepseek provider, so supply a dummy during init.
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-dummy-init"}, clear=False):
            mock_client = MagicMock()
            mock_openai_class.return_value = mock_client
            mock_client.chat.completions.create.return_value = MagicMock(
                choices=[MagicMock(message=MagicMock(content="ok"))]
            )

            from sources.llm_provider import Provider
            provider = Provider("deepseek", "deepseek-chat",
                                server_address="127.0.0.1:11434", is_local=False)

        # Now unset env var so only keystore supplies the key
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DEEPSEEK_API_KEY", None)
            provider.deepseek_fn(
                [{"role": "user", "content": "test"}]
            )

            kwargs = mock_openai_class.call_args.kwargs
            self.assertEqual(kwargs["api_key"], "sk-from-keystore")


class TestKeyAliases(unittest.TestCase):

    def test_deepseek_alias(self):
        self.assertEqual(ks._KEY_ALIASES.get("deepseek"), "deepseek_api_key")


if __name__ == '__main__':
    unittest.main()
