# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""
Certificate store API.

Certificates are stored in the DB with private keys Fernet-encrypted.
Endpoints allow upload, list, get (public metadata only), and delete.
A /parse endpoint validates and extracts metadata without persisting.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.middleware.rbac import require_admin, require_viewer
from app.models.certificate import Certificate
from app.models.user import User
from app.services import audit, cert_crypto

logger = logging.getLogger(__name__)
router = APIRouter()

# ─── Pydantic schemas ─────────────────────────────────────────────────────────


class CertUpload(BaseModel):
    label: str = Field(max_length=255)
    cert_type: str = "server"  # server | ca | client — advisory
    cert_pem: str = Field(max_length=65536)
    key_pem: Optional[str] = Field(default=None, max_length=65536)
    passphrase: Optional[str] = Field(default=None, max_length=1024)
    ca_chain_pem: Optional[str] = Field(default=None, max_length=131072)
    notes: Optional[str] = Field(default=None, max_length=4096)


class CertParseRequest(BaseModel):
    cert_pem: str = Field(max_length=65536)
    key_pem: Optional[str] = Field(default=None, max_length=65536)
    passphrase: Optional[str] = Field(default=None, max_length=1024)


class CertMeta(BaseModel):
    fingerprint: Optional[str]
    cn: Optional[str]
    sans: list[str]
    eku: list[str]
    expires_at: Optional[datetime]
    expires_in_days: Optional[int]

    model_config = {"from_attributes": True}


class CertResponse(BaseModel):
    id: str
    label: str
    cert_type: str
    has_key: bool
    fingerprint: Optional[str]
    cn: Optional[str]
    sans: list[str]
    eku: list[str]
    expires_at: Optional[datetime]
    expires_in_days: Optional[int]
    ca_chain_pem: Optional[str]
    notes: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class CertPatch(BaseModel):
    label: Optional[str] = Field(default=None, max_length=255)
    notes: Optional[str] = Field(default=None, max_length=4096)


def _to_response(cert: Certificate) -> CertResponse:
    sans = json.loads(cert.sans) if cert.sans else []
    eku = json.loads(cert.eku) if cert.eku else []
    expires_in_days: Optional[int] = None
    if cert.expires_at:
        exp = cert.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        delta = exp - datetime.now(timezone.utc)
        expires_in_days = max(0, delta.days)
    return CertResponse(
        id=cert.id,
        label=cert.label,
        cert_type=cert.cert_type,
        has_key=cert.key_pem_encrypted is not None,
        fingerprint=cert.fingerprint,
        cn=cert.cn,
        sans=sans,
        eku=eku,
        expires_at=cert.expires_at,
        expires_in_days=expires_in_days,
        ca_chain_pem=cert.ca_chain_pem,
        notes=cert.notes,
        created_at=cert.created_at,
    )


# ─── Routes ───────────────────────────────────────────────────────────────────


@router.post("/parse", response_model=CertMeta)
async def parse_cert(
    body: CertParseRequest,
    _: User = Depends(require_admin),
) -> CertMeta:
    """Validate and extract cert metadata without persisting."""
    try:
        meta = cert_crypto.parse_cert(body.cert_pem)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid PEM certificate",
        )

    if body.key_pem:
        try:
            cert_crypto.validate_private_key(body.key_pem, body.passphrase)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid private key or passphrase",
            )

    sans = json.loads(meta["sans"]) if meta["sans"] else []
    eku = json.loads(meta["eku"]) if meta["eku"] else []
    expires_at: Optional[datetime] = meta.get("expires_at")
    expires_in_days: Optional[int] = None
    if expires_at:
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        expires_in_days = max(0, (expires_at - datetime.now(timezone.utc)).days)

    return CertMeta(
        fingerprint=meta["fingerprint"],
        cn=meta["cn"],
        sans=sans,
        eku=eku,
        expires_at=expires_at,
        expires_in_days=expires_in_days,
    )


@router.get("", response_model=list[CertResponse])
async def list_certs(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_viewer),
) -> list[CertResponse]:
    result = await db.execute(select(Certificate).order_by(Certificate.created_at))
    return [_to_response(c) for c in result.scalars().all()]


@router.post("", response_model=CertResponse, status_code=status.HTTP_201_CREATED)
async def upload_cert(
    body: CertUpload,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> CertResponse:
    if body.cert_type not in ("server", "ca", "client"):
        raise HTTPException(
            status_code=400, detail="cert_type must be server, ca, or client"
        )

    try:
        meta = cert_crypto.parse_cert(body.cert_pem)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid PEM certificate")

    key_enc: Optional[str] = None
    if body.key_pem:
        try:
            cert_crypto.validate_private_key(body.key_pem, body.passphrase)
        except ValueError:
            raise HTTPException(
                status_code=422, detail="Invalid private key or passphrase"
            )
        key_enc = cert_crypto.encrypt(body.key_pem, settings.secret_key)

    passphrase_enc: Optional[str] = None
    if body.passphrase:
        passphrase_enc = cert_crypto.encrypt(body.passphrase, settings.secret_key)

    # Validate every block in the CA chain — partial chains with bad blocks are rejected
    if body.ca_chain_pem:
        try:
            cert_crypto.validate_ca_chain(body.ca_chain_pem)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

    cert = Certificate(
        label=body.label,
        cert_type=body.cert_type,
        cert_pem=body.cert_pem,
        key_pem_encrypted=key_enc,
        passphrase_encrypted=passphrase_enc,
        fingerprint=meta["fingerprint"],
        cn=meta["cn"],
        sans=meta["sans"],
        eku=meta["eku"],
        expires_at=meta["expires_at"],
        ca_chain_pem=body.ca_chain_pem or None,
        notes=body.notes or None,
    )
    db.add(cert)
    await db.commit()
    await db.refresh(cert)
    logger.info("Certificate uploaded: %s (%s)", cert.label, cert.id)
    await audit.record(
        action="cert.upload",
        user_id=current_user.id,
        user_email=current_user.email,
        resource_type="certificate",
        resource_id=cert.id,
        detail=f"uploaded {cert.cert_type} cert '{cert.label}' (CN={cert.cn})",
    )
    return _to_response(cert)


@router.get("/{cert_id}", response_model=CertResponse)
async def get_cert(
    cert_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_viewer),
) -> CertResponse:
    cert = await _get_or_404(cert_id, db)
    return _to_response(cert)


@router.patch("/{cert_id}", response_model=CertResponse)
async def patch_cert(
    cert_id: str,
    body: CertPatch,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> CertResponse:
    cert = await _get_or_404(cert_id, db)
    data = body.model_dump(exclude_unset=True)
    if "label" in data:
        cert.label = data["label"]
    if "notes" in data:
        cert.notes = data["notes"]
    db.add(cert)
    await db.commit()
    await db.refresh(cert)
    return _to_response(cert)


@router.delete("/{cert_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_cert(
    cert_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> None:
    cert = await _get_or_404(cert_id, db)
    label = cert.label
    await db.delete(cert)
    await db.commit()
    await audit.record(
        action="cert.delete",
        user_id=current_user.id,
        user_email=current_user.email,
        resource_type="certificate",
        resource_id=cert_id,
        detail=f"deleted cert '{label}'",
    )


async def _get_or_404(cert_id: str, db: AsyncSession) -> Certificate:
    cert = await db.get(Certificate, cert_id)
    if not cert:
        raise HTTPException(status_code=404, detail="Certificate not found")
    return cert
