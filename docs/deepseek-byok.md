# DeepSeek BYOK (Bring Your Own Key) Setup

> **ADR:** [ADR-004 — DeepSeek BYOK Key Storage](../../knowledgebase/plans/ecoSeek/adr/ADR-004-deepseek-byok-key-storage.md)

EcoSeek supports using your own DeepSeek API key for strong reasoning
capabilities without local GPU hardware. Your key is stored **locally on
your machine** — it is never committed, logged, or sent to EcoSeek
infrastructure.

## Quick Start

```bash
# 1. Get a DeepSeek API key from https://platform.deepseek.com/api_keys

# 2. Store it securely
python -m sources.keystore set deepseek
# You will be prompted to enter the key (input is hidden).

# 3. Configure config.ini
# provider_name = deepseek_byok
# provider_model = deepseek-chat

# 4. Run EcoSeek normally — the key is loaded automatically.
```

## Key Storage

### Where keys are stored

Keys are stored using one of two backends (tried in order):

1. **OS keychain** (preferred) — macOS Keychain, GNOME Secret Service /
   KWallet on Linux, Windows Credential Manager. Requires the `keyring`
   Python package.
2. **Encrypted local file** — `~/.config/ecoseek/keys.json` with `0600`
   permissions. Used when `keyring` is unavailable. Encryption uses
   Fernet (AES-128-CBC + HMAC-SHA256) from the `cryptography` package,
   which is a **required dependency** — the keystore refuses to store
   or read secrets if `cryptography` is not importable, rather than
   silently writing reversible base64.

### Key resolution order

When EcoSeek needs the DeepSeek API key, it checks these sources in
order:

1. `DEEPSEEK_API_KEY` environment variable (CI / dev override).
2. Keystore entry `deepseek_api_key` (OS keychain or encrypted file).
3. If neither is found, an error is raised with setup instructions.

This preserves backward compatibility: users with `DEEPSEEK_API_KEY` in
`.env` keep working, but the keystore is the recommended path.

## CLI Commands

```bash
# Store the DeepSeek key
python -m sources.keystore set deepseek

# Verify the key is stored (shows redacted value)
python -m sources.keystore get deepseek

# List all stored keys
python -m sources.keystore list

# Remove the key
python -m sources.keystore delete deepseek
```

## config.ini Options

### BYOK mode (recommended)

```ini
[MAIN]
provider_name = deepseek_byok
provider_model = deepseek-chat
```

Uses the keystore exclusively. Best for users who want secure local key
storage.

### Legacy mode (backward compatible)

```ini
[MAIN]
provider_name = deepseek
provider_model = deepseek-chat
```

Also checks the keystore first, but falls back to the `DEEPSEEK_API_KEY`
environment variable.

## Security Properties

- **Never committed:** Keys are stored outside the repository in
  `~/.config/ecoseek/` or the OS keychain. The `.gitignore` excludes
  `.env` files.
- **Never logged:** Key values are redacted in all log output and error
  messages. Only the last 4 characters are shown for identification.
- **Never transmitted:** The key goes directly from your machine to the
  DeepSeek API (`https://api.deepseek.com`). EcoSeek infrastructure
  never sees it.
- **User-revocable:** Run `python -m sources.keystore delete deepseek`
  to remove the key at any time, or revoke it at
  https://platform.deepseek.com/api_keys.
- **File permissions:** The encrypted keys file is created with `0600`
  (owner-only read/write). The config directory is `0700`.

## Troubleshooting

### "DeepSeek API key not found"

Run `python -m sources.keystore set deepseek` to store your key, or set
`DEEPSEEK_API_KEY` in your `.env` file.

### "DeepSeek API key rejected"

Your key may be expired or invalid. Check at
https://platform.deepseek.com/api_keys. Re-store it with:

```bash
python -m sources.keystore set deepseek
```

### "keyring" not available

Install the `keyring` package for OS keychain integration:

```bash
pip install keyring
```

Without it, the encrypted file fallback is used. This is still secure
but the OS keychain is preferred.

### "EcoSeek keystore requires the 'cryptography' package"

Install the required dependency:

```bash
pip install cryptography
```

The keystore intentionally fails closed if `cryptography` is missing —
it will never silently fall back to plaintext or base64 for secret
storage.
