# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""AI assistant provider configuration (BYO-LLM).

Stored in ``system_settings`` under key ``ai``. The API key is **Fernet-encrypted
at rest** (reusing the cert-store key derivation keyed off ``VORTEXFLOW_SECRET_KEY``)
and **never returned to a client** — read paths mask it, exactly like sink secrets.

This module is the storage + crypto layer only. The LLM client that consumes
``api_key`` lives in B2 (``ai_client.py``); it calls :func:`get_api_key` to obtain
the decrypted secret at request time.

Providers:
- ``anthropic``     — Claude via the Anthropic API (default; latest Claude).
- ``openai``        — OpenAI via the OpenAI API.
- ``self_hosted``   — any OpenAI-compatible endpoint (Ollama / vLLM) at ``base_url``;
                      the no-egress / air-gapped path. May need no API key.

Self-hosted is a day-one provider, not a follow-up — it's the moat (your data, your
model).
"""

import json

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.system_setting import SystemSetting
from app.services import cert_crypto

_KEY = "ai"

PROVIDERS = {"anthropic", "openai", "self_hosted"}

# Providers that authenticate with an API key. Self-hosted (Ollama/vLLM) commonly
# runs unauthenticated on an internal network, so a key is optional there.
KEYED_PROVIDERS = {"anthropic", "openai"}

# Public defaults (never includes a secret). ``api_key_encrypted`` is stored
# alongside but stripped from every read path.
DEFAULTS: dict = {
    "enabled": False,
    "provider": "anthropic",
    "base_url": "",  # required for self_hosted; optional override for others
    "model": "claude-opus-4-8",
    # Opt-in: dotted field paths redacted from the sample event before it is sent
    # to the model (enforced in B3's generate loop). Empty = send raw sample.
    "redact_fields": [],
}


async def load_raw(db: AsyncSession) -> dict:
    """Full stored config including ``api_key_encrypted`` — internal use only.

    Never return this directly to a client; use :func:`public_view` for reads.
    """
    row = await db.get(SystemSetting, _KEY)
    if row is None:
        return {**DEFAULTS, "api_key_encrypted": ""}
    try:
        data = json.loads(row.value)
    except json.JSONDecodeError:
        return {**DEFAULTS, "api_key_encrypted": ""}
    if not isinstance(data, dict):
        return {**DEFAULTS, "api_key_encrypted": ""}
    return {**DEFAULTS, "api_key_encrypted": "", **data}


async def save_raw(db: AsyncSession, data: dict) -> None:
    row = await db.get(SystemSetting, _KEY)
    if row is None:
        db.add(SystemSetting(key=_KEY, value=json.dumps(data)))
    else:
        row.value = json.dumps(data)
    await db.commit()


def public_view(raw: dict) -> dict:
    """Config safe to return to an admin client: secret replaced by a boolean.

    The ciphertext and plaintext key never leave the server. The client learns
    only whether a key is set, so the form can show a masked placeholder.
    """
    return {
        "enabled": bool(raw.get("enabled", False)),
        "provider": raw.get("provider", DEFAULTS["provider"]),
        "base_url": raw.get("base_url", ""),
        "model": raw.get("model", DEFAULTS["model"]),
        "redact_fields": list(raw.get("redact_fields", [])),
        "api_key_set": bool(raw.get("api_key_encrypted")),
    }


def get_api_key(raw: dict, secret_key: str) -> str | None:
    """Decrypt the stored API key, or None if unset/undecryptable. For B2."""
    enc = raw.get("api_key_encrypted") or ""
    if not enc:
        return None
    try:
        return cert_crypto.decrypt(enc, secret_key)
    except Exception:
        return None


def encrypt_api_key(plaintext: str, secret_key: str) -> str:
    return cert_crypto.encrypt(plaintext, secret_key)
