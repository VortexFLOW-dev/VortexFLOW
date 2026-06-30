# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from pydantic import (
    AliasChoices,
    BaseModel,
    Field,
    field_validator,
    model_validator,
)

# Accepted Vector component types, kind-aware. Generated from the Vector schema
# (the SAME source as the frontend catalog) by frontend/scripts/gen-catalog-manifest.ts
# → `make catalog`. Never hand-edit: the backend accepts exactly what the picker
# offers, and the Contract Drift Sentinel's C1 check guards the two stay equal.
_CATALOG_TYPES_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "catalog_types.json"
)


def _load_catalog_types() -> tuple[frozenset[str], frozenset[str]]:
    data = json.loads(_CATALOG_TYPES_PATH.read_text(encoding="utf-8"))
    return frozenset(data.get("sources", [])), frozenset(data.get("sinks", []))


_SOURCE_TYPES, _SINK_TYPES = _load_catalog_types()
# Union kept under the historical name (also the Sentinel C1 read surface).
_KNOWN_TYPES = _SOURCE_TYPES | _SINK_TYPES

# Cap the serialized config to bound DB storage / parse cost (mirrors the
# max_length hardening on route schemas). Catalog forms are far under this.
_MAX_CONFIG_BYTES = 64_000


def _check_config_size(v: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if v is not None and len(json.dumps(v)) > _MAX_CONFIG_BYTES:
        raise ValueError(f"config exceeds {_MAX_CONFIG_BYTES} bytes")
    return v


class ComponentCreate(BaseModel):
    fleet_id: str
    kind: str = Field(..., pattern="^(source|sink)$")
    name: str = Field(..., max_length=100)
    component_type: str = Field(..., max_length=100)
    config: dict[str, Any] = Field(default_factory=dict)
    # Sink direct inputs (source/stage ids) — quick-connect / fan-out.
    inputs: list[str] = Field(default_factory=list, max_length=50)
    # TLS cert-store refs: {"identity": <cert_id>?, "ca": <cert_id>?}.
    cert_refs: dict[str, str] = Field(default_factory=dict)

    @field_validator("config")
    @classmethod
    def _config_size(cls, v: dict[str, Any]) -> dict[str, Any]:
        return _check_config_size(v) or {}

    @model_validator(mode="after")
    def _validate_kind_type(self) -> "ComponentCreate":
        # Kind-aware: a source-only type can't be created as a sink, and vice
        # versa. (Deploy is still gated by `vector validate`; this is fail-fast UX.)
        allowed = _SOURCE_TYPES if self.kind == "source" else _SINK_TYPES
        if self.component_type not in allowed:
            other = _SINK_TYPES if self.kind == "source" else _SOURCE_TYPES
            if self.component_type in other:
                raise ValueError(
                    f"'{self.component_type}' is not a valid {self.kind} type"
                )
            raise ValueError(f"Unknown component type '{self.component_type}'")
        return self


class ComponentUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    config: Optional[dict[str, Any]] = None
    inputs: Optional[list[str]] = Field(None, max_length=50)
    cert_refs: Optional[dict[str, str]] = None

    @field_validator("config")
    @classmethod
    def _config_size(cls, v: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
        return _check_config_size(v)


class ComponentResponse(BaseModel):
    id: str
    fleet_id: str
    kind: str
    name: str
    component_type: str
    config: dict[str, Any] = Field(
        validation_alias=AliasChoices("config", "config_json"),
    )
    inputs: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("inputs", "inputs_json"),
    )
    cert_refs: dict[str, str] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("cert_refs", "cert_refs_json"),
    )
    created_by: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True, "populate_by_name": True}

    @field_validator("config", mode="before")
    @classmethod
    def parse_config(cls, v: object) -> object:
        if isinstance(v, str):
            try:
                raw = json.loads(v)
            except (json.JSONDecodeError, TypeError):
                return {}
            if not isinstance(raw, dict):
                return {}
            return raw
        return v

    @field_validator("inputs", mode="before")
    @classmethod
    def parse_inputs(cls, v: object) -> object:
        if isinstance(v, str):
            try:
                raw = json.loads(v)
            except (json.JSONDecodeError, TypeError):
                return []
            return raw if isinstance(raw, list) else []
        return v

    @field_validator("cert_refs", mode="before")
    @classmethod
    def parse_cert_refs(cls, v: object) -> object:
        if v is None:
            return {}
        if isinstance(v, str):
            try:
                raw = json.loads(v)
            except (json.JSONDecodeError, TypeError):
                return {}
            return raw if isinstance(raw, dict) else {}
        return v


class ComponentListResponse(BaseModel):
    components: list[ComponentResponse]
    total: int
