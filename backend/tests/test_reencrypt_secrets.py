# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Re-encrypt migration core logic (ADR-002 Phase 2)."""

import os

os.environ.setdefault(
    "VORTEXFLOW_SECRET_KEY",
    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
)

import pytest  # noqa: E402

from app.reencrypt_secrets import Undecryptable, _reencrypt  # noqa: E402
from app.services import cert_crypto  # noqa: E402

OLD = "o" * 40
NEW = "n" * 40
THIRD = "t" * 40


def test_reencrypts_old_to_new():
    blob = cert_crypto.encrypt("s3cr3t", OLD)
    out = _reencrypt(blob, OLD, NEW)
    assert out is not None
    assert cert_crypto.decrypt(out, NEW) == "s3cr3t"
    with pytest.raises(Exception):
        cert_crypto.decrypt(out, OLD)  # no longer readable with the old key


def test_idempotent_already_under_new():
    blob = cert_crypto.encrypt("s3cr3t", NEW)
    assert _reencrypt(blob, OLD, NEW) is None  # already migrated → skip


def test_undecryptable_when_neither_key_works():
    # Orphaned ciphertext (prior key) → per-item Undecryptable so the caller can
    # skip it and keep migrating the rest, rather than aborting the whole run.
    blob = cert_crypto.encrypt("s3cr3t", THIRD)
    with pytest.raises(Undecryptable):
        _reencrypt(blob, OLD, NEW)


def test_empty_is_noop():
    assert _reencrypt(None, OLD, NEW) is None
    assert _reencrypt("", OLD, NEW) is None
