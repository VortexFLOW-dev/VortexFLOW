# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
import uuid


class ApiToken(Base):
    """A personal access token (PAT) for programmatic API access.

    Format: ``vf_pat_<token_id>_<secret>``. ``token_id`` is stored plaintext for
    O(1) lookup; only the SHA-256 of the high-entropy ``secret`` is stored — the
    secret itself is shown to the user exactly once at creation. A request
    authenticated by a PAT acts as the owning user and **inherits that user's
    role live** (so RBAC, deactivation, and role changes apply immediately).
    """

    __tablename__ = "api_tokens"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    # Public lookup id embedded in the token (not secret).
    token_id: Mapped[str] = mapped_column(
        String, unique=True, nullable=False, index=True
    )
    # SHA-256 (hex) of the secret half. High-entropy → a fast hash is correct
    # (bcrypt is for low-entropy passwords); never store the secret itself.
    token_hash: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
