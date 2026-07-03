# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""at_rest_key: separate encryption key with backward-compatible fallback (ADR-002)."""

import os

os.environ.setdefault(
    "VORTEXFLOW_SECRET_KEY",
    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
)

from app.core.config import settings  # noqa: E402
from app.services import cert_crypto  # noqa: E402


def test_falls_back_to_secret_key_when_unset(monkeypatch):
    monkeypatch.setattr(settings, "encryption_key", None)
    assert settings.at_rest_key == settings.secret_key


def test_uses_encryption_key_when_set(monkeypatch):
    ek = "f" * 40
    monkeypatch.setattr(settings, "encryption_key", ek)
    assert settings.at_rest_key == ek
    assert settings.at_rest_key != settings.secret_key


def test_backward_compat_ciphertext_decrypts_when_unset(monkeypatch):
    # Data encrypted under secret_key (historical) still decrypts when no
    # dedicated encryption_key is configured.
    monkeypatch.setattr(settings, "encryption_key", None)
    blob = cert_crypto.encrypt("s3cr3t", settings.secret_key)
    assert cert_crypto.decrypt(blob, settings.at_rest_key) == "s3cr3t"


def test_separated_key_isolates_at_rest_from_jwt(monkeypatch):
    # With a dedicated key, at-rest ciphertext is tied to encryption_key, not the
    # JWT secret_key — decrypting with secret_key must fail.
    monkeypatch.setattr(settings, "encryption_key", "e" * 48)
    blob = cert_crypto.encrypt("s3cr3t", settings.at_rest_key)
    assert cert_crypto.decrypt(blob, settings.at_rest_key) == "s3cr3t"
    import pytest

    with pytest.raises(Exception):
        cert_crypto.decrypt(blob, settings.secret_key)
