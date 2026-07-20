# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from sqlalchemy import String, DateTime, Text, func, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base
import uuid


class Component(Base):
    """A fleet-scoped Vector component resource — a reusable Source or
    Destination (sink). Pipelines and routes wire these together by id.

    kind discriminates source|sink (transform reserved for future use).
    config_json holds the catalog form values used to generate Vector YAML.
    """

    __tablename__ = "components"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    fleet_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("fleets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String, nullable=False, index=True)  # source|sink
    name: Mapped[str] = mapped_column(String, nullable=False)
    component_type: Mapped[str] = mapped_column(String, nullable=False)  # e.g. kafka
    config_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    # Secret catalog fields (passwords, tokens, keys) pulled out of config_json
    # and Fernet-encrypted at rest — a JSON {dotkey: value} map. See
    # app/services/secrets.py. Decrypted only at deploy/render; masked elsewhere.
    secrets_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    # TLS cert-store references — a JSON {"identity": <cert_id>?, "ca": <cert_id>?}.
    # `identity` provides tls.crt_file + key_file (+ key_pass); `ca` provides
    # tls.ca_file. At deploy the referenced certs are written to the host and the
    # tls.* paths are rewritten to the managed location. See config_render.
    cert_refs_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Direct upstream ids a sink reads (source/stage), in addition to any
    # route-branch outputs that target it. Lets a destination be wired without a
    # route (quick-connect / fan-out). Unused for sources.
    inputs_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]", server_default="[]"
    )
    created_by: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
