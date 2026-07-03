# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Encrypt sink/source credentials at rest.

A component's catalog form values are split into two stores:

- **Non-secret** fields stay in ``Component.config_json`` (plaintext — they show
  in the Config-modal preview and API responses).
- **Secret** fields (passwords, tokens, API/access keys, SASL passwords, …) are
  pulled out and stored Fernet-encrypted in ``Component.secrets_encrypted``
  (reusing the cert-store key-derivation, keyed off ``VORTEXFLOW_SECRET_KEY``).

Secrets are **decrypted only at deploy/render time** when the real Vector config
is written to a host, and **masked** (``MASK``) in every read path. On update, a
field that comes back as the ``MASK`` sentinel keeps its existing encrypted
value, so editing other fields never round-trips a secret through the browser.

Secret detection is by **config key name** (a conservative, fail-safe pattern
set): when a key clearly names a credential it is encrypted. This is the backend
source of truth; the frontend catalog mirrors it with a ``secret`` flag purely
for password-input UX.
"""

import json
import re

from app.services import cert_crypto

# Returned in place of a real secret in every read path. Also accepted on write
# to mean "keep the stored value unchanged" (the field was not edited).
MASK = "••••••••"

# Substrings/patterns (matched case-insensitively against the dot-key) that mark
# a field as a credential. Conservative but fail-safe — when in doubt, encrypt.
_SECRET_PATTERNS = [
    r"password",
    r"passwd",
    r"secret",
    r"token",
    r"api_?key",
    r"access_key",
    r"private_key",
    r"credential",
    r"sas_?key",
    r"license_key",
    r"auth_?key",
    r"passphrase",
    r"key_pass",  # Vector tls.key_pass — passphrase for an encrypted key file
    r"connection_string",  # Azure Blob / AMQP — embeds AccountKey / amqp password
    r"shared_key",  # Azure Monitor sink — base64 shared secret
    r"nkey",  # NATS nkey seed — a private credential
]

# Leaf keys that contain a secret-ish substring but are structural, not
# credentials — excluded to avoid masking a routing/partition field.
_NOT_SECRET_LEAVES = {
    "key",
    "key_field",
    "partition_key",
    "group_key",
    "routing_key",
    "message_key",
    "dedupe_key",
    "secret_name",  # a *reference* to a secret, not the secret itself
}

# Suffixes that denote a file path or a field name, never the secret value.
_NOT_SECRET_SUFFIXES = ("_file", "_field", "_path")

_secret_re = re.compile("|".join(_SECRET_PATTERNS), re.IGNORECASE)


def is_secret_key(dotkey: str) -> bool:
    """True if a component config key names a credential that must be encrypted."""
    leaf = dotkey.rsplit(".", 1)[-1].lower()
    if leaf in _NOT_SECRET_LEAVES:
        return False
    if dotkey.lower().endswith(_NOT_SECRET_SUFFIXES):
        return False
    return bool(_secret_re.search(dotkey))


def _is_unset(v: object) -> bool:
    """A secret value that means 'not provided' — dropped, never persisted."""
    return v is None or v == ""


def split_for_write(
    incoming: dict,
    existing_secrets_encrypted: str | None,
    secret_key: str,
) -> tuple[dict, str | None]:
    """Split an incoming full config into (public_config, secrets_encrypted).

    Works for both create (``existing_secrets_encrypted=None``) and update. A
    secret field whose incoming value is the ``MASK`` sentinel keeps its existing
    encrypted value; a real new value replaces it; an empty/absent value is
    dropped. A real value is encrypted **regardless of type** — a numeric or
    boolean value under a credential-named key (e.g. ``password: 1234``) must not
    fall through to plaintext public config.
    """
    existing = decrypt(existing_secrets_encrypted, secret_key)
    public: dict = {}
    secrets: dict = {}
    for k, v in incoming.items():
        if not is_secret_key(k):
            public[k] = v
            continue
        if v == MASK:
            if k in existing:
                secrets[k] = existing[k]  # unchanged — preserve
            # else: masked but nothing stored → treat as unset, drop
        elif _is_unset(v):
            public[k] = v  # empty/absent — nothing to hide, keep it public
        else:
            secrets[k] = v  # real secret of any type → encrypt
    return public, encrypt(secrets, secret_key)


def encrypt(secrets: dict, secret_key: str) -> str | None:
    """Fernet-encrypt a {key: value} secret map → ciphertext, or None if empty."""
    if not secrets:
        return None
    return cert_crypto.encrypt(json.dumps(secrets), secret_key)


def decrypt(secrets_encrypted: str | None, secret_key: str) -> dict:
    """Decrypt the stored secret map. Returns {} on absent/invalid ciphertext."""
    if not secrets_encrypted:
        return {}
    try:
        data = json.loads(cert_crypto.decrypt(secrets_encrypted, secret_key))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def merge_revealed(
    public_config: dict, secrets_encrypted: str | None, secret_key: str
) -> dict:
    """Public config + decrypted secrets — the real config for render/deploy."""
    return {**public_config, **decrypt(secrets_encrypted, secret_key)}


def merge_masked(
    public_config: dict, secrets_encrypted: str | None, secret_key: str
) -> dict:
    """Public config + a ``MASK`` placeholder per stored secret — for API reads."""
    keys = decrypt(secrets_encrypted, secret_key).keys()
    return {**public_config, **{k: MASK for k in keys}}
