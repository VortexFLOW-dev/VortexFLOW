# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from sqlalchemy import String, DateTime, Text, func, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base
import uuid


class Route(Base):
    __tablename__ = "routes"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    fleet_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("fleets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # JSON array: [{"name": str, "condition": str, "sink_ids": [str]}, ...]
    # Passthrough (_unmatched) is implicit — not stored as a branch, but its
    # destinations live in passthrough_sink_ids_json.
    branches_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    # Source component ids that feed this route (the route transform's inputs).
    source_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    # Sink component ids the _unmatched (passthrough) output feeds.
    passthrough_sink_ids_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]"
    )
    created_by: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
