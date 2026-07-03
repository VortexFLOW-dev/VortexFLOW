# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Password policy: min length + bcrypt 72-byte cap (no silent truncation) — F12."""

import os

os.environ.setdefault(
    "VORTEXFLOW_SECRET_KEY",
    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
)

import pytest  # noqa: E402

from app.core.security import (  # noqa: E402
    BCRYPT_MAX_BYTES,
    get_password_hash,
    validate_password_policy,
    verify_password,
)


def test_too_short_rejected():
    with pytest.raises(ValueError):
        validate_password_policy("short1")


def test_min_length_override():
    validate_password_policy("exactly8", min_length=8)  # ok
    with pytest.raises(ValueError):
        validate_password_policy("only10chars", min_length=12)


def test_over_72_bytes_rejected():
    with pytest.raises(ValueError):
        validate_password_policy("a" * (BCRYPT_MAX_BYTES + 1))


def test_multibyte_counted_as_bytes():
    # 40 × 2-byte chars = 80 bytes > 72, even though len() == 40.
    pw = "é" * 40
    assert len(pw) == 40
    with pytest.raises(ValueError):
        validate_password_policy(pw)


def test_get_password_hash_refuses_over_72_bytes():
    # Defense in depth: never silently truncate at the hash boundary.
    with pytest.raises(ValueError):
        get_password_hash("a" * 100)


def test_normal_password_roundtrips():
    validate_password_policy("correct horse battery")
    h = get_password_hash("correct horse battery")
    assert verify_password("correct horse battery", h)
