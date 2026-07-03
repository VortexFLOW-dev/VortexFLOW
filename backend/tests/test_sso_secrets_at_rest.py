# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""SSO IdP secrets are encrypted at rest (not stored plaintext in system_settings).

Exercises the pure persistence/read transforms + the loader's decrypt path
without a DB. Run: `pytest tests/test_sso_secrets_at_rest.py`.
"""

import os

os.environ.setdefault(
    "VORTEXFLOW_SECRET_KEY",
    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
)

from app.api.v1.settings import _mask_secrets, _seal_secrets  # noqa: E402
from app.services.secrets import MASK  # noqa: E402
from app.services.sso_config import _secret  # noqa: E402


def test_plaintext_secret_never_persisted():
    sealed = _seal_secrets({"client_secret": "hunter2"}, {}, "client_secret")
    # The plaintext key is gone; only a ciphertext is written.
    assert "client_secret" not in sealed
    assert sealed["client_secret_encrypted"]
    assert "hunter2" not in sealed["client_secret_encrypted"]


def test_read_masks_and_strips_ciphertext():
    sealed = _seal_secrets({"client_secret": "hunter2"}, {}, "client_secret")
    masked = _mask_secrets(sealed, "client_secret")
    assert masked["client_secret"] == MASK
    assert "client_secret_encrypted" not in masked  # ciphertext never leaves server


def test_loader_decrypts_roundtrip():
    sealed = _seal_secrets({"client_secret": "hunter2"}, {}, "client_secret")
    assert _secret(sealed, "client_secret", None) == "hunter2"


def test_mask_input_preserves_stored_secret():
    sealed = _seal_secrets({"client_secret": "hunter2"}, {}, "client_secret")
    # Client sends MASK back (unchanged) → ciphertext preserved verbatim.
    again = _seal_secrets({"client_secret": MASK}, sealed, "client_secret")
    assert again["client_secret_encrypted"] == sealed["client_secret_encrypted"]
    assert _secret(again, "client_secret", None) == "hunter2"


def test_legacy_plaintext_migrates_on_write():
    legacy = {"client_secret": "old-plaintext"}
    migrated = _seal_secrets({"client_secret": MASK}, legacy, "client_secret")
    assert "client_secret" not in migrated
    assert migrated["client_secret_encrypted"]
    assert _secret(migrated, "client_secret", None) == "old-plaintext"


def test_loader_reads_legacy_plaintext():
    # Pre-encryption install with plaintext still on disk (not yet re-saved).
    assert _secret({"bind_password": "legacy"}, "bind_password", None) == "legacy"


def test_undecryptable_ciphertext_fails_closed():
    # Secret key rotated / corrupt ciphertext → empty, not an exception.
    assert (
        _secret({"client_secret_encrypted": "not-a-token"}, "client_secret", None) == ""
    )


def test_env_fallback_when_unset():
    assert _secret({}, "client_secret", "from-env") == "from-env"
    assert _secret({}, "client_secret", None) == ""
