# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Deliver cert-store material to the hosts that run a fleet's Vector.

A component can reference stored certificates for its TLS (``cert_refs_json``).
At deploy/agent-render time we fetch + decrypt the referenced certs and hand the
material to the renderer, which rewrites the ``tls.*_file`` paths to a managed
on-host location and emits the files to write (``RenderResult.files``).

- **Local mode:** the server writes those files itself (``write_files_local``).
- **Agent mode:** the files ride along in the agent config response; the agent
  writes them before it validates/reloads Vector.
"""

import json
import os
import pathlib

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.certificate import Certificate
from app.services import cert_crypto


def _referenced_cert_ids(components: list) -> set[str]:
    ids: set[str] = set()
    for c in components:
        raw = getattr(c, "cert_refs_json", None)
        if not raw:
            continue
        try:
            refs = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(refs, dict):
            continue
        for role in ("identity", "ca"):
            v = refs.get(role)
            if v:
                ids.add(v)
    return ids


async def materials_for_components(
    components: list, db: AsyncSession
) -> dict[str, dict]:
    """Fetch + decrypt the cert material for every cert a component references.

    Returns ``{cert_id: {cert_pem, key_pem?, ca_chain_pem?, passphrase?}}``.
    Only called on the reveal (deploy/agent) path — never on preview."""
    ids = _referenced_cert_ids(components)
    if not ids:
        return {}
    rows = (
        (await db.execute(select(Certificate).where(Certificate.id.in_(ids))))
        .scalars()
        .all()
    )
    out: dict[str, dict] = {}
    for cert in rows:
        mat: dict = {"cert_pem": cert.cert_pem, "ca_chain_pem": cert.ca_chain_pem}
        if cert.key_pem_encrypted:
            try:
                mat["key_pem"] = cert_crypto.decrypt(
                    cert.key_pem_encrypted, settings.secret_key
                )
            except Exception:
                pass
        if cert.passphrase_encrypted:
            try:
                mat["passphrase"] = cert_crypto.decrypt(
                    cert.passphrase_encrypted, settings.secret_key
                )
            except Exception:
                pass
        out[cert.id] = mat
    return out


def write_files_local(files: list[dict]) -> None:
    """Write rendered cert files to the local filesystem (local-mode delivery).

    Hardened like the cert store's own writer: absolute paths only, confined to
    the managed cert dir, parent dir 0700, key files 0600, atomic O_NOFOLLOW
    write-then-rename."""
    from app.services.config_render import COMPONENT_CERTS_DIR

    base = pathlib.Path(COMPONENT_CERTS_DIR).resolve()
    for f in files:
        path = f["path"]
        content = f["content"]
        mode = int(f.get("mode", 0o644))
        if not os.path.isabs(path):
            raise ValueError(f"cert file path must be absolute: {path!r}")
        dest = pathlib.Path(path)
        # Defense in depth: the path segments are server-generated (UUID), but
        # never write outside the managed cert dir even if that ever changes.
        if not dest.resolve().is_relative_to(base):
            raise ValueError(f"cert file path escapes managed dir: {path!r}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            dest.parent.chmod(0o700)
        except PermissionError:
            pass
        tmp = str(dest) + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, mode)
        try:
            os.write(fd, content.encode())
        finally:
            os.close(fd)
        os.rename(tmp, str(dest))
