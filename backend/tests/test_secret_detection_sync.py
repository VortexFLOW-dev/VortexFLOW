# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Fail-closed backstop for secret detection (ultra M6 / P6 root cause).

The backend `is_secret_key` (the encryptor) and the frontend `isSecretKey`
(password-input UX + preview masking) are hand-mirrored regexes in two
languages. If they drift, a credential-named field could render in a plaintext
input / preview on one side while the other treats it differently. This test
fails CI the moment the two definitions diverge, so drift can't ship silently.
"""

import re
from pathlib import Path

from app.services import secrets as s

_CATALOG_TS = (
    Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "catalog.ts"
)


def _read_catalog() -> str:
    return _CATALOG_TS.read_text(encoding="utf-8")


def test_secret_pattern_regex_in_sync():
    # Backend compiles `"|".join(_SECRET_PATTERNS)`; the frontend hard-codes the
    # same alternation as a /.../i literal. They must match exactly.
    backend_body = "|".join(s._SECRET_PATTERNS)
    src = _read_catalog()
    m = re.search(r"_SECRET_RE\s*=\s*\n?\s*/(?P<body>.+?)/i", src, re.DOTALL)
    assert m, "could not find _SECRET_RE in catalog.ts"
    frontend_body = m.group("body").strip()
    assert frontend_body == backend_body, (
        "secret-detection regex drifted between backend secrets.py and frontend "
        f"catalog.ts:\n  backend:  {backend_body}\n  frontend: {frontend_body}"
    )


def test_not_secret_leaves_in_sync():
    src = _read_catalog()
    m = re.search(
        r"_NOT_SECRET_LEAVES\s*=\s*new Set\(\[(?P<body>.+?)\]\)", src, re.DOTALL
    )
    assert m, "could not find _NOT_SECRET_LEAVES in catalog.ts"
    frontend_leaves = set(re.findall(r"'([^']+)'", m.group("body")))
    assert frontend_leaves == set(s._NOT_SECRET_LEAVES), (
        "not-secret leaf set drifted between backend and frontend:\n"
        f"  backend:  {sorted(s._NOT_SECRET_LEAVES)}\n"
        f"  frontend: {sorted(frontend_leaves)}"
    )


def test_not_secret_suffixes_in_sync():
    src = _read_catalog()
    # frontend: /(_file|_field|_path)$/i
    m = re.search(r"/\((?P<body>[^)]+)\)\$/i", src)
    assert m, "could not find the not-secret suffix regex in catalog.ts"
    frontend_suffixes = tuple(m.group("body").split("|"))
    # Backend stores full suffixes ("_file", ...); frontend uses the same tokens.
    assert set(frontend_suffixes) == set(s._NOT_SECRET_SUFFIXES), (
        f"suffix drift:\n  backend: {s._NOT_SECRET_SUFFIXES}\n"
        f"  frontend: {frontend_suffixes}"
    )
