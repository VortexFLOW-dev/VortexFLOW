# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""
Certificate encryption helpers.

Private keys are encrypted at rest with Fernet symmetric encryption keyed off
VORTEXFLOW_SECRET_KEY. The cert PEM (public) is stored plaintext.
"""

import base64
import hashlib
import json
import os
import re
from datetime import timezone
from pathlib import Path
from typing import Optional

from cryptography import x509
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


def _fernet(secret_key: str) -> Fernet:
    # PBKDF2-HMAC-SHA256 with fixed app-level salt — provides key stretching
    # so DB + key leak alone is insufficient for offline brute force.
    key_bytes = hashlib.pbkdf2_hmac(
        "sha256",
        secret_key.encode(),
        b"vortexflow-cert-store-v1",
        260_000,
    )
    return Fernet(base64.urlsafe_b64encode(key_bytes))


def encrypt(plaintext: str, secret_key: str) -> str:
    return _fernet(secret_key).encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str, secret_key: str) -> str:
    return _fernet(secret_key).decrypt(ciphertext.encode()).decode()


_EKU_NAMES = {
    ExtendedKeyUsageOID.SERVER_AUTH: "TLS Web Server Authentication",
    ExtendedKeyUsageOID.CLIENT_AUTH: "TLS Web Client Authentication",
    ExtendedKeyUsageOID.CODE_SIGNING: "Code Signing",
    ExtendedKeyUsageOID.EMAIL_PROTECTION: "Email Protection",
    ExtendedKeyUsageOID.TIME_STAMPING: "Time Stamping",
    ExtendedKeyUsageOID.OCSP_SIGNING: "OCSP Signing",
}

# Matches one complete PEM block
_PEM_RE = re.compile(
    rb"-----BEGIN [A-Z ]+-----[\s\S]+?-----END [A-Z ]+-----",
    re.MULTILINE,
)


def parse_cert(cert_pem: str) -> dict:
    """
    Parse a PEM certificate and return metadata dict:
      fingerprint, cn, sans (JSON str), eku (JSON str), expires_at (datetime)
    Raises ValueError if the PEM is not a valid certificate.
    """
    try:
        cert = x509.load_pem_x509_certificate(cert_pem.encode())
    except Exception:
        raise ValueError("Invalid PEM certificate")

    der = cert.public_bytes(serialization.Encoding.DER)
    fp_bytes = hashlib.sha256(der).digest()
    fingerprint = ":".join(f"{b:02X}" for b in fp_bytes)

    try:
        cn = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
    except (IndexError, Exception):
        cn = None

    sans: list[str] = []
    try:
        ext = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        for name in ext.value:
            if isinstance(name, x509.DNSName):
                sans.append(f"DNS:{name.value}")
            elif isinstance(name, x509.IPAddress):
                sans.append(f"IP:{name.value}")
    except x509.ExtensionNotFound:
        pass

    eku_names: list[str] = []
    try:
        ext_eku = cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage)
        for oid in ext_eku.value:
            eku_names.append(_EKU_NAMES.get(oid, oid.dotted_string))
    except x509.ExtensionNotFound:
        pass

    expires_at = (
        cert.not_valid_after_utc
        if hasattr(cert, "not_valid_after_utc")
        else cert.not_valid_after.replace(tzinfo=timezone.utc)
    )

    return {
        "fingerprint": fingerprint,
        "cn": cn,
        "sans": json.dumps(sans),
        "eku": json.dumps(eku_names),
        "expires_at": expires_at,
    }


def validate_ca_chain(ca_chain_pem: str) -> None:
    """
    Validate every PEM block in a CA chain string.
    Raises ValueError if any block is not a valid certificate.
    """
    blocks = _PEM_RE.findall(ca_chain_pem.encode())
    if not blocks:
        raise ValueError("No PEM certificate blocks found in CA chain")
    for i, block in enumerate(blocks):
        try:
            x509.load_pem_x509_certificate(block)
        except Exception:
            raise ValueError(f"CA chain block {i + 1} is not a valid certificate")


def validate_private_key(key_pem: str, passphrase: Optional[str] = None) -> None:
    """Validate that key_pem is a parseable PEM private key. Raises ValueError on failure."""
    pw = passphrase.encode() if passphrase else None
    try:
        load_pem_private_key(key_pem.encode(), password=pw)
    except Exception:
        raise ValueError("Invalid private key")


# ─── Disk write helpers ───────────────────────────────────────────────────────


def _get_certs_dir() -> Path:
    raw = os.environ.get("VORTEXFLOW_CERTS_DIR", "/etc/vortexflow/certs")
    p = Path(raw)
    if not p.is_absolute():
        raise ValueError(f"VORTEXFLOW_CERTS_DIR must be an absolute path, got: {raw!r}")
    return p


def write_tls_files(
    cert_pem: str,
    key_pem: str,
    ca_chain_pem: Optional[str] = None,
) -> dict[str, str]:
    """
    Write cert, key, and optional CA chain to CERTS_DIR atomically.
    The private key temp file is created with mode 0o600 before any bytes
    are written, eliminating the world-readable window.
    Returns a dict of {role: absolute_path}.
    """
    certs_dir = _get_certs_dir()
    # Restrict directory so only the service user can create files inside
    certs_dir.mkdir(parents=True, exist_ok=True)
    try:
        certs_dir.chmod(0o700)
    except PermissionError:
        pass  # Already restricted by owner; non-fatal if we don't own it

    paths: dict[str, str] = {}

    def _write_secure(name: str, content: str, mode: int = 0o644) -> str:
        dest = certs_dir / name
        # Create temp file with correct permissions BEFORE writing content
        fd = os.open(
            str(dest) + ".tmp",
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW,
            mode,
        )
        try:
            os.write(fd, content.encode())
        finally:
            os.close(fd)
        os.rename(str(dest) + ".tmp", str(dest))
        return str(dest)

    paths["cert"] = _write_secure("server.crt", cert_pem, mode=0o644)
    paths["key"] = _write_secure("server.key", key_pem, mode=0o600)
    if ca_chain_pem:
        paths["ca"] = _write_secure("ca-chain.crt", ca_chain_pem, mode=0o644)

    return paths
