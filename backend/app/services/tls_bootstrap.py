# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""First-boot self-signed TLS for the deploy.

Generates a self-signed CA + server certificate into the TLS cert dir on first
boot, so the stack is HTTPS out of the box and agents can verify it (the install
script ships the CA to each agent). If a certificate is already present — e.g. a
real cert the operator dropped in — we leave it untouched.

Files written into the cert dir:
  ca.pem    — the CA cert (served at /install/ca.crt; agents trust it)
  cert.pem  — the server leaf cert (nginx ssl_certificate)
  key.pem   — the server private key (0600; nginx ssl_certificate_key)
"""

import datetime
import ipaddress
import logging
import os
from pathlib import Path
from urllib.parse import urlparse

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

logger = logging.getLogger(__name__)

CA_FILE = "ca.pem"
CERT_FILE = "cert.pem"
KEY_FILE = "key.pem"


def _san_entries(public_url: str | None) -> list[x509.GeneralName]:
    """SANs the server cert must be valid for. The agent connects to public_url,
    so its hostname must be covered or verification fails even with the CA
    trusted. Always include localhost/127.0.0.1 for same-host use."""
    names: list[x509.GeneralName] = [
        x509.DNSName("localhost"),
        x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
    ]
    if public_url:
        host = urlparse(public_url).hostname
        if host:
            try:
                names.append(x509.IPAddress(ipaddress.ip_address(host)))
            except ValueError:
                names.append(x509.DNSName(host))
    return names


def _write(path: Path, data: bytes, mode: int) -> None:
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


def ensure_self_signed(cert_dir: str, public_url: str | None) -> None:
    """Generate a CA + server cert into cert_dir if cert.pem is absent. No-op if
    a cert already exists (operator-provided or previously generated)."""
    directory = Path(cert_dir)
    directory.mkdir(parents=True, exist_ok=True)
    if (directory / CERT_FILE).exists():
        return

    primary = "localhost"
    if public_url:
        primary = urlparse(public_url).hostname or "localhost"

    now = datetime.datetime.now(datetime.timezone.utc)
    not_after = now + datetime.timedelta(days=3650)

    # ── CA ────────────────────────────────────────────────────────────────────
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "VortexFlow CA")])
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(not_after)
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_cert_sign=True,
                crl_sign=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )

    # ── Server leaf, signed by the CA ───────────────────────────────────────────
    srv_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    srv_cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, primary)]))
        .issuer_name(ca_name)
        .public_key(srv_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(not_after)
        .add_extension(
            x509.SubjectAlternativeName(_san_entries(public_url)), critical=False
        )
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=True,
                content_commitment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )

    _write(directory / CA_FILE, ca_cert.public_bytes(serialization.Encoding.PEM), 0o644)
    _write(
        directory / CERT_FILE, srv_cert.public_bytes(serialization.Encoding.PEM), 0o644
    )
    _write(
        directory / KEY_FILE,
        srv_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        ),
        0o600,
    )
    logger.warning(
        "Generated self-signed TLS cert for %s in %s. Replace with a real cert "
        "for production; agents trust the bundled CA via the install script.",
        primary,
        cert_dir,
    )
