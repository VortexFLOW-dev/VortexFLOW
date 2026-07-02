# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from sqlalchemy import String, Boolean, DateTime, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base
import uuid


class Fleet(Base):
    __tablename__ = "fleets"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    bootstrap_token_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Published config generation. Bumped on Deploy/rollback; agents pull the
    # published generation and only reload when it changes.
    generation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Fernet-encrypted snapshot of the last SUCCESSFULLY-deployed render (the
    # config dict + cert files + warnings). Agents are served this snapshot, never
    # a live DB render, so an un-deployed edit can't reach a host. Encrypted at
    # rest because it holds decrypted secrets + cert private keys. NULL until the
    # first successful deploy.
    deployed_config: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Per-fleet desired Vector version. NULL/empty = inherit the global default
    # (general.desired_vector_version). Lets you roll a version to one fleet at a
    # time instead of all-at-once. Resolved as fleet override → global default.
    desired_vector_version: Mapped[str | None] = mapped_column(String, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
