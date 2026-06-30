# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Audit logging.

Records security- and config-relevant actions to the ``audit_log`` table: who
did what, to which resource, from where, and when.

Writes happen in their **own** database session, decoupled from the caller's
transaction, for two reasons:

1. **Durability** — the audit entry persists even if the caller's transaction
   later rolls back (we audit that an action was *attempted/performed*).
2. **Safety** — an audit failure can never break or roll back the action being
   audited. ``record()`` swallows its own errors and only logs a warning.

Pass plain ``user_id`` / ``user_email`` (not a session-bound ORM object), since
the write runs in a separate session.
"""

import logging

from app.core.database import AsyncSessionLocal
from app.models.audit_log import AuditLog

logger = logging.getLogger(__name__)


async def record(
    *,
    action: str,
    user_id: str | None = None,
    user_email: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    detail: str | None = None,
    ip: str | None = None,
) -> None:
    """Best-effort audit write. Never raises into the caller.

    ``action`` is a stable verb-ish key, e.g. ``auth.login``,
    ``auth.login_failed``, ``user.create``, ``fleet.deploy``, ``cert.apply``.
    """
    try:
        async with AsyncSessionLocal() as session:
            session.add(
                AuditLog(
                    user_id=user_id,
                    user_email=user_email,
                    action=action,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    detail=(detail[:2000] if detail else None),
                    ip_address=ip,
                )
            )
            await session.commit()
    except Exception as e:  # pragma: no cover - audit must never break the action
        logger.warning(f"audit write failed for action={action!r}: {e}")
