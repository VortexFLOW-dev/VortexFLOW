# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from datetime import datetime
from sqlalchemy import String, Boolean, DateTime, ForeignKey, Integer, func
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base
import uuid


class Instance(Base):
    __tablename__ = "instances"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    label: Mapped[str] = mapped_column(String, nullable=False)
    api_url: Mapped[str] = mapped_column(String, nullable=False)
    config_push_mode: Mapped[str] = mapped_column(
        String, nullable=False, default="local"
    )
    config_dir: Mapped[str | None] = mapped_column(String, nullable=True)
    agent_url: Mapped[str | None] = mapped_column(String, nullable=True)
    agent_token_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    fleet_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("fleets.id", ondelete="SET NULL"), nullable=True
    )
    role: Mapped[str] = mapped_column(String, nullable=False, default="agent")
    # Vector global options, applied per-instance at deploy time (each host has
    # its own data_dir). data_dir is Vector's on-disk state/buffer location —
    # required for disk buffers; expire_metrics_secs bounds metric cardinality.
    data_dir: Mapped[str | None] = mapped_column(String, nullable=True)
    expire_metrics_secs: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Agent reported state (agent-mode only). applied_generation tracks which
    # published fleet generation the agent has applied; agent_status is a short
    # state string ("ok" / "validate_failed" / etc.).
    applied_generation: Mapped[int | None] = mapped_column(Integer, nullable=True)
    agent_last_seen: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    agent_status: Mapped[str | None] = mapped_column(String, nullable=True)
    # Vector version the agent last reported as installed (drift vs desired).
    vector_version: Mapped[str | None] = mapped_column(String, nullable=True)
    tls_verify: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    tls_ca_cert: Mapped[str | None] = mapped_column(String, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
