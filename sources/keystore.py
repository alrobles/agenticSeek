"""Secure local key storage for EcoSeek BYOK credentials.

Implements ADR-004: DeepSeek API keys (and future BYOK credentials) are
stored **locally on the user's machine**, never committed, logged, or
transmitted to EcoSeek infrastructure.

Storage backends (tried in order):

1. **OS keychain** via the ``keyring`` library (macOS Keychain, GNOME
   Secret Service / KWallet on Linux, Windows Credential Manager).
2. **Encrypted local file** at ``~/.config/ecoseek/keys.json`` with
   ``0600`` permissions when ``keyring`` is unavailable.

The file-based fallback uses Fernet symmetric encryption (AES-128-CBC
+ HMAC-SHA256) with a machine-derived key so the JSON on disk is not
plaintext. ``cryptography`` is a required dependency; the keystore
fails closed with an actionable installation error if it cannot be
imported. There is no plaintext or base64 fallback for secret values.

This is not HSM-grade security — it defends against casual file reads,
not a determined attacker with root on the same machine. The OS
keychain is strongly preferred.

All public functions redact key values from exceptions and log output.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import platform
import stat
from pathlib import Path
from typing import Dict, List, Optional

from sources.logger import Logger

_SERVICE_NAME = "ecoseek"
_CONFIG_DIR = Path.home() / ".config" / "ecoseek"
_KEYS_FILE = _CONFIG_DIR / "keys.json"
_REDACTED = "***REDACTED***"

_CRYPTO_INSTALL_MSG = (
    "EcoSeek keystore requires the 'cryptography' package for at-rest "
    "encryption of BYOK secrets. Install it with:\n"
    "    pip install cryptography\n"
    "Refusing to store secrets without real encryption."
)


class KeystoreCryptoUnavailable(RuntimeError):
    """Raised when ``cryptography`` is not importable.

    The keystore refuses to fall back to base64 or plaintext; callers
    must install ``cryptography`` (declared as a required dependency)
    before storing or retrieving secrets.
    """


_logger = Logger("keystore.log")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _derive_fernet_key() -> bytes:
    """Derive a Fernet key from stable machine identifiers.

    This is *not* a password — it is a defense-in-depth measure so the
    keys file is not stored as plaintext JSON.  A determined local
    attacker can reproduce this key, but casual ``cat`` of the file
    reveals nothing useful.
    """
    try:
        login = os.getlogin()
    except (OSError, AttributeError):
        login = os.getenv("USER", os.getenv("USERNAME", "user"))
    salt = f"{platform.node()}-{login}-ecoseek"
    raw = hashlib.sha256(salt.encode()).digest()
    return base64.urlsafe_b64encode(raw)


def _ensure_config_dir() -> None:
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        _CONFIG_DIR.chmod(0o700)
    except OSError:
        pass


def _secure_permissions(path: Path) -> None:
    """Set file to owner-only read/write (0600)."""
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def _require_fernet():
    """Import Fernet or raise an actionable error.

    The keystore never silently downgrades to base64 — that would
    write secrets to disk in trivially reversible form. If
    ``cryptography`` is missing we fail closed.
    """
    try:
        from cryptography.fernet import Fernet
    except ImportError as exc:
        raise KeystoreCryptoUnavailable(_CRYPTO_INSTALL_MSG) from exc
    return Fernet


def _encrypt(plaintext: str) -> str:
    """Fernet-encrypt *plaintext* and return a URL-safe base64 string.

    Raises:
        KeystoreCryptoUnavailable: if ``cryptography`` is not installed.
    """
    Fernet = _require_fernet()
    f = Fernet(_derive_fernet_key())
    return f.encrypt(plaintext.encode()).decode()


def _decrypt(token: str) -> str:
    """Decrypt a token produced by ``_encrypt``.

    Raises:
        KeystoreCryptoUnavailable: if ``cryptography`` is not installed.
    """
    Fernet = _require_fernet()
    f = Fernet(_derive_fernet_key())
    return f.decrypt(token.encode()).decode()


# ---------------------------------------------------------------------------
# Keyring backend
# ---------------------------------------------------------------------------

def _keyring_available() -> bool:
    try:
        import keyring as _kr
        _kr.get_password(_SERVICE_NAME, "__probe__")
        return True
    except Exception:
        return False


def _keyring_store(name: str, value: str) -> None:
    import keyring as _kr
    _kr.set_password(_SERVICE_NAME, name, value)


def _keyring_get(name: str) -> Optional[str]:
    import keyring as _kr
    return _kr.get_password(_SERVICE_NAME, name)


def _keyring_delete(name: str) -> None:
    import keyring as _kr
    try:
        _kr.delete_password(_SERVICE_NAME, name)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# File backend
# ---------------------------------------------------------------------------

def _file_read_store() -> Dict[str, str]:
    if not _KEYS_FILE.exists():
        return {}
    try:
        raw = json.loads(_KEYS_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return raw


def _file_write_store(store: Dict[str, str]) -> None:
    _ensure_config_dir()
    _KEYS_FILE.write_text(json.dumps(store, indent=2))
    _secure_permissions(_KEYS_FILE)


def _file_store(name: str, value: str) -> None:
    store = _file_read_store()
    store[name] = _encrypt(value)
    _file_write_store(store)


def _file_get(name: str) -> Optional[str]:
    store = _file_read_store()
    token = store.get(name)
    if token is None:
        return None
    try:
        return _decrypt(token)
    except KeystoreCryptoUnavailable:
        # Propagate so callers see the actionable setup error instead
        # of silently treating "no crypto installed" as "key missing".
        raise
    except Exception:
        return None


def _file_delete(name: str) -> None:
    store = _file_read_store()
    store.pop(name, None)
    _file_write_store(store)


def _file_list() -> List[str]:
    return list(_file_read_store().keys())


def _file_store_name_only(name: str) -> None:
    """Record key name in file index without storing the value."""
    store = _file_read_store()
    if name not in store:
        store[name] = _encrypt("__keyring__")
        _file_write_store(store)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_USE_KEYRING: Optional[bool] = None


def _backend() -> bool:
    """Return True if using OS keyring, False for file backend."""
    global _USE_KEYRING
    if _USE_KEYRING is None:
        _USE_KEYRING = _keyring_available()
        backend_name = "OS keyring" if _USE_KEYRING else "encrypted file"
        _logger.info(f"Keystore backend: {backend_name}")
    return _USE_KEYRING


def store_key(name: str, value: str) -> None:
    """Store a credential.  Raises ``ValueError`` on empty input."""
    if not name or not name.strip():
        raise ValueError("Key name must not be empty")
    if not value or not value.strip():
        raise ValueError("Key value must not be empty")
    name = name.strip()
    value = value.strip()

    if _backend():
        _keyring_store(name, value)
    else:
        _file_store(name, value)
    # Always write the name (not value) to the file index so list_keys works
    if _backend():
        _file_store_name_only(name)
    _logger.info(f"Stored key: {name}")


def get_key(name: str) -> Optional[str]:
    """Retrieve a credential by name, or ``None`` if absent."""
    name = name.strip()
    if _backend():
        return _keyring_get(name)
    return _file_get(name)


def delete_key(name: str) -> None:
    """Delete a credential.  No-op if absent."""
    name = name.strip()
    if _backend():
        _keyring_delete(name)
    _file_delete(name)
    _logger.info(f"Deleted key: {name}")


def list_keys() -> List[str]:
    """Return names of all stored credentials (values are never exposed).

    Note: the OS keyring does not support enumeration, so this always
    reads from the file store which tracks key names (but not values
    when the keyring backend is active — values live in the keychain).
    """
    return _file_list()


def get_deepseek_key() -> Optional[str]:
    """Convenience: retrieve the DeepSeek API key.

    Resolution order (first non-empty wins):

    1. ``DEEPSEEK_API_KEY`` environment variable (CI / dev override).
    2. Keystore entry ``deepseek_api_key``.
    3. ``None`` — caller should prompt the user.

    The env-var fallback preserves backward compatibility with users who
    already have ``.env`` configured.
    """
    from dotenv import load_dotenv
    load_dotenv()
    env_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if env_key and env_key != "xxxxx":
        return env_key
    return get_key("deepseek_api_key")


def store_deepseek_key(value: str) -> None:
    """Convenience: store the DeepSeek API key securely."""
    store_key("deepseek_api_key", value)


def delete_deepseek_key() -> None:
    """Convenience: remove the DeepSeek API key."""
    delete_key("deepseek_api_key")


def redact(value: str) -> str:
    """Replace all but the last 4 characters with asterisks."""
    if not value or len(value) <= 4:
        return _REDACTED
    return "*" * (len(value) - 4) + value[-4:]


# ---------------------------------------------------------------------------
# CLI entry point:  python -m sources.keystore {set|get|list|delete} [name]
# ---------------------------------------------------------------------------

_KEY_ALIASES = {
    "deepseek": "deepseek_api_key",
}


def _cli() -> None:
    import getpass
    import sys

    usage = (
        "Usage: python -m sources.keystore <command> [name]\n"
        "\n"
        "Commands:\n"
        "  set <name>     Store a key (input is hidden)\n"
        "  get <name>     Show redacted key value\n"
        "  list           List stored key names\n"
        "  delete <name>  Remove a stored key\n"
        "\n"
        "Name aliases: deepseek -> deepseek_api_key\n"
    )

    args = sys.argv[1:] if len(sys.argv) > 1 else []
    if not args or args[0] in ("-h", "--help"):
        print(usage)
        sys.exit(0)

    cmd = args[0]
    name = _KEY_ALIASES.get(args[1], args[1]) if len(args) > 1 else None

    if cmd == "set":
        if not name:
            print("Error: key name required.  Example: python -m sources.keystore set deepseek")
            sys.exit(1)
        value = getpass.getpass(f"Enter value for {name}: ")
        store_key(name, value)
        print(f"Stored: {name}")

    elif cmd == "get":
        if not name:
            print("Error: key name required.")
            sys.exit(1)
        value = get_key(name)
        if value:
            print(f"{name}: {redact(value)}")
        else:
            print(f"{name}: not found")
            sys.exit(1)

    elif cmd == "list":
        keys = list_keys()
        if keys:
            for k in keys:
                print(f"  {k}")
        else:
            print("No keys stored.")

    elif cmd == "delete":
        if not name:
            print("Error: key name required.")
            sys.exit(1)
        delete_key(name)
        print(f"Deleted: {name}")

    else:
        print(f"Unknown command: {cmd}")
        print(usage)
        sys.exit(1)


if __name__ == "__main__":
    _cli()
