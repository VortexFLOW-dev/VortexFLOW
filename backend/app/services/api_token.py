# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""
Personal access token (PAT) helpers.

Token format: ``vf_pat_<token_id>_<secret>``
  - ``token_id``  16 hex chars — public, stored plaintext, used for O(1) lookup.
  - ``secret``    43 url-safe chars (~256 bits) — never stored; only its SHA-256.

Verification is a constant-time compare of SHA-256(secret) against the stored
hash. A fast hash is correct here: the secret is high-entropy, so brute force is
infeasible regardless (bcrypt's slowness only matters for low-entropy passwords).
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

PREFIX = "vf_pat_"


def is_pat(credential: str) -> bool:
    return credential.startswith(PREFIX)


def generate() -> tuple[str, str, str]:
    """Return (token_id, secret, full_token). Persist token_id + hash(secret)."""
    token_id = secrets.token_hex(8)  # 16 hex chars
    secret = secrets.token_urlsafe(32)  # ~43 chars, 256 bits
    full = f"{PREFIX}{token_id}_{secret}"
    return token_id, secret, full


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def parse(credential: str) -> tuple[str, str] | None:
    """Split a presented PAT into (token_id, secret); None if malformed."""
    if not credential.startswith(PREFIX):
        return None
    body = credential[len(PREFIX) :]
    token_id, sep, secret = body.partition("_")
    if not sep or not token_id or not secret:
        return None
    return token_id, secret


def verify(secret: str, stored_hash: str) -> bool:
    return hmac.compare_digest(hash_secret(secret), stored_hash)
