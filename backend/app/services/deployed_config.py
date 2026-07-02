# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Encrypted snapshot of a fleet's last successfully-deployed render.

Agents are served this snapshot (decrypted at request time), never a live DB
render — so an editor's un-deployed change can't reach a host. The blob is
Fernet-encrypted at rest because it contains the revealed secrets embedded in the
config and the private keys in the cert files. Only :func:`deploy_fleet` writes
it, and only after ``vector validate`` has passed.
"""

import json
from typing import Any

from app.services import cert_crypto


def encode(
    config: dict[str, Any],
    files: list[dict[str, Any]],
    warnings: list[str],
    secret_key: str,
) -> str:
    """Serialize + Fernet-encrypt a validated render for storage on the fleet."""
    payload = json.dumps({"config": config, "files": files, "warnings": warnings})
    return cert_crypto.encrypt(payload, secret_key)


def decode(blob: str, secret_key: str) -> dict[str, Any]:
    """Decrypt + parse a stored snapshot into ``{config, files, warnings}``."""
    return json.loads(cert_crypto.decrypt(blob, secret_key))
