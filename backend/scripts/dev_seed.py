# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""
Seed a known LOCAL DEV admin so you can log in without the first-run setup token.

DEV ONLY. Run via `make dev-seed` (which loads backend/.env.dev). Idempotent —
re-running resets the password. Never run against a production database: the
setup-token flow is the real first-admin control there.

  Login:  admin@vortexflow.dev  /  devpassword
"""

import asyncio
import sys

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import get_password_hash
from app.models.user import User

DEV_EMAIL = "admin@vortexflow.dev"
DEV_PASSWORD = "devpassword"  # noqa: S105 — local dev credential, not a secret


async def main() -> None:
    async with AsyncSessionLocal() as db:
        user = (
            await db.execute(select(User).where(User.email == DEV_EMAIL))
        ).scalar_one_or_none()
        if user is None:
            db.add(
                User(
                    email=DEV_EMAIL,
                    name="Dev Admin",
                    role="admin",
                    auth_method="local",
                    hashed_password=get_password_hash(DEV_PASSWORD),
                    is_active=True,
                    must_change_password=False,
                )
            )
            action = "created"
        else:
            user.hashed_password = get_password_hash(DEV_PASSWORD)
            user.role = "admin"
            user.is_active = True
            user.must_change_password = False
            action = "reset"
        await db.commit()

    print(f"dev admin {action}: {DEV_EMAIL} / {DEV_PASSWORD}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:  # pragma: no cover - dev convenience script
        print(f"dev-seed failed: {exc}", file=sys.stderr)
        sys.exit(1)
