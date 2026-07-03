# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""The notification test path must not echo host/errno details (SSRF oracle) —
auth F10. Raw SMTP/socket errors are collapsed to a sanitized, host-free
RuntimeError."""

import asyncio
import os
import smtplib

os.environ.setdefault(
    "VORTEXFLOW_SECRET_KEY",
    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
)

import pytest  # noqa: E402

from app.services import notify  # noqa: E402
from app.services.notify import EventView  # noqa: E402

EV = EventView(
    event_id="test",
    kind="test",
    severity="warning",
    title="t",
    body="b",
    resource_type=None,
    resource_id=None,
)


def test_send_email_sanitizes_connection_error(monkeypatch):
    secret_host = "internal-mail.corp.local"

    def boom(*a, **k):
        raise smtplib.SMTPConnectError(111, f"connection refused to {secret_host}")

    monkeypatch.setattr(notify, "_smtp_send", boom)
    config = {"host": secret_host, "from_addr": "a@b.c", "to_addrs": ["x@y.z"]}
    with pytest.raises(RuntimeError) as ei:
        asyncio.run(notify._send_email({}, config, EV, "test"))
    msg = str(ei.value)
    assert secret_host not in msg  # host never leaks
    assert "111" not in msg  # errno never leaks
    assert "SMTPConnectError" in msg  # coarse type hint only


def test_send_email_sanitizes_dns_failure(monkeypatch):
    def boom(*a, **k):
        raise OSError(-2, "Name or service not known")

    monkeypatch.setattr(notify, "_smtp_send", boom)
    config = {"host": "nope.invalid", "from_addr": "a@b.c", "to_addrs": ["x@y.z"]}
    with pytest.raises(RuntimeError) as ei:
        asyncio.run(notify._send_email({}, config, EV, "test"))
    assert "Name or service not known" not in str(ei.value)
