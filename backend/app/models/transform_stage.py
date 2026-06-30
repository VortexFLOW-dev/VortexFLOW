# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Remap stage — a fleet-scoped VRL transform placed in the data path.

Makes the VRL library deployable: a stage sits between sources and routes
(``source → remap → route``), declaring what it reads via ``inputs_json`` and
emitting a Vector ``remap`` transform at render time. Either inline VRL or a
reference to a global ``vrl_transforms`` template (resolved at render).
"""

from datetime import datetime
import uuid

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class TransformStage(Base):
    __tablename__ = "transform_stages"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    fleet_id: Mapped[str] = mapped_column(
        String, ForeignKey("fleets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    # inline | library
    mode: Mapped[str] = mapped_column(String, nullable=False, default="inline")
    # VRL when mode=inline
    source_vrl: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Library template reference when mode=library (VRL resolved at render).
    transform_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("vrl_transforms.id", ondelete="SET NULL"), nullable=True
    )
    # JSON list of upstream ids this stage reads (source components or stages).
    inputs_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
