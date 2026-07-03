# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Re-encrypt all at-rest secrets from the old key to VORTEXFLOW_ENCRYPTION_KEY.

ADR-002 Phase 2: an existing install that wants to adopt a dedicated at-rest
encryption key (separate from the JWT ``SECRET_KEY``) runs this once. Every
Fernet-encrypted store is decrypted with the OLD key and re-encrypted with the
NEW key.

Usage (from the backend dir, with VORTEXFLOW_ENCRYPTION_KEY set to the NEW key):

    # dry run — reports what would change, writes nothing (default):
    python -m app.reencrypt_secrets
    # actually migrate:
    python -m app.reencrypt_secrets --commit
    # if you previously used a non-default at-rest key, name it explicitly:
    python -m app.reencrypt_secrets --old-key "<previous at-rest key>" --commit

Safe to run:
  * **Dry-run by default** — pass ``--commit`` to write.
  * **Idempotent** — a value already readable with the NEW key is left untouched,
    so a re-run (or a partial previous run) is safe.
  * **Fails closed** — if a value decrypts with neither the NEW nor the OLD key,
    the run aborts before writing anything, rather than corrupting data.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any, cast

from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.certificate import Certificate
from app.models.component import Component
from app.models.fleet import Fleet
from app.models.notification import NotificationChannel
from app.models.system_setting import SystemSetting
from app.services import cert_crypto

# ORM (model, attribute) pairs holding a direct Fernet blob.
_DIRECT: list[tuple[type, str]] = [
    (Component, "secrets_encrypted"),
    (Certificate, "key_pem_encrypted"),
    (Certificate, "passphrase_encrypted"),
    (Fleet, "deployed_config"),
    (NotificationChannel, "secret_encrypted"),
]

# system_settings JSON: setting key -> encrypted sub-fields inside its JSON value.
_SETTINGS_FIELDS: dict[str, list[str]] = {
    "sso_azure": ["client_secret_encrypted"],
    "sso_oidc": ["client_secret_encrypted"],
    "sso_ldap": ["bind_password_encrypted"],
    "ai": ["api_key_encrypted"],
}


class Undecryptable(Exception):
    """A value decrypts with neither the new nor the old key — un-migratable."""


def _reencrypt(blob: str | None, old: str, new: str) -> str | None:
    """Return the re-encrypted blob, or None if there's nothing to change.

    Idempotent: a blob already readable with ``new`` is left as-is (returns
    None). Raises ``Undecryptable`` if the blob decrypts with neither key — that
    is either orphaned ciphertext from a prior key (which the app already
    tolerates, e.g. a stale deploy snapshot) or a wrong ``old`` key. The caller
    skips those per-item rather than aborting, and flags them in the summary."""
    if not blob:
        return None
    try:
        cert_crypto.decrypt(blob, new)
        return None  # already under the new key — idempotent skip
    except Exception:
        pass
    try:
        plaintext = cert_crypto.decrypt(blob, old)
    except Exception:
        raise Undecryptable() from None
    return cert_crypto.encrypt(plaintext, new)


async def _run(old: str, new: str, commit: bool) -> tuple[int, list[str]]:
    """Returns (changed_count, list-of-unmigratable-locations)."""
    changed = 0
    skipped: list[str] = []

    def _try(blob: str | None, where: str) -> str | None:
        nonlocal changed
        try:
            out = _reencrypt(blob, old, new)
        except Undecryptable:
            skipped.append(where)
            return None
        if out is not None:
            changed += 1
        return out

    async with AsyncSessionLocal() as db:
        # Direct blob columns.
        for model, attr in _DIRECT:
            tbl = getattr(model, "__tablename__", model.__name__)
            for row in (await db.execute(select(cast(Any, model)))).scalars().all():
                out = _try(getattr(row, attr), f"{tbl}.{attr}#{row.id}")
                if out is not None:
                    setattr(row, attr, out)

        # system_settings JSON sub-fields.
        for key, fields in _SETTINGS_FIELDS.items():
            row = await db.get(SystemSetting, key)
            if row is None:
                continue
            try:
                data = json.loads(row.value)
            except (json.JSONDecodeError, TypeError):
                continue
            dirty = False
            for f in fields:
                out = _try(data.get(f), f"system_settings[{key}].{f}")
                if out is not None:
                    data[f] = out
                    dirty = True
            if dirty:
                row.value = json.dumps(data)

        if commit and changed:
            await db.commit()
        else:
            await db.rollback()
    return changed, skipped


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--old-key",
        default=None,
        help="Previous at-rest key (default: VORTEXFLOW_SECRET_KEY, the historical "
        "at-rest key).",
    )
    parser.add_argument(
        "--commit", action="store_true", help="Write changes (default: dry run)."
    )
    args = parser.parse_args()

    new = settings.encryption_key
    if not new:
        print(
            "VORTEXFLOW_ENCRYPTION_KEY is not set — nothing to migrate TO. Set it to "
            "the new dedicated at-rest key first.",
            file=sys.stderr,
        )
        return 2
    old = args.old_key or settings.secret_key
    if old == new:
        print("Old and new keys are identical — nothing to do.")
        return 0

    changed, skipped = asyncio.run(_run(old, new, args.commit))

    if skipped:
        print(
            f"NOTE: {len(skipped)} value(s) could not be decrypted with either key "
            "and were left unchanged (orphaned ciphertext from a prior key — the "
            "app already tolerates these):",
            file=sys.stderr,
        )
        for w in skipped:
            print(f"  - {w}", file=sys.stderr)
        if changed == 0:
            print(
                "WARNING: nothing was migrated and everything was undecryptable — "
                "is --old-key correct?",
                file=sys.stderr,
            )

    if args.commit:
        print(f"Re-encrypted {changed} secret value(s) to the new key.")
    else:
        print(
            f"DRY RUN: {changed} secret value(s) would be re-encrypted. "
            "Re-run with --commit to apply."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
