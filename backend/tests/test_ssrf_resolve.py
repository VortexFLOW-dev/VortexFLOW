# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Call-time SSRF guard: resolve host + reject loopback/link-local — ultra H1.
Closes the DNS-name→private and alt-encoding bypasses the literal check missed."""

import asyncio
import os
import socket

os.environ.setdefault(
    "VORTEXFLOW_SECRET_KEY",
    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
)

import pytest  # noqa: E402

from app.core import netutil  # noqa: E402
from app.core.netutil import _addr_blocked, assert_resolved_host_public  # noqa: E402


def _fake_getaddrinfo(ips):
    async def _f(host, port, **kw):
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (ip, 0)) for ip in ips]

    return _f


def _run(host, monkeypatch, resolves_to):
    class _Loop:
        async def getaddrinfo(self, host, port, **kw):
            return [
                (socket.AF_INET, socket.SOCK_STREAM, 0, "", (ip, 0))
                for ip in resolves_to
            ]

    monkeypatch.setattr(netutil.asyncio, "get_running_loop", lambda: _Loop())
    return asyncio.run(assert_resolved_host_public(host))


def test_addr_blocked_direct():
    assert _addr_blocked("127.0.0.1")
    assert _addr_blocked("169.254.169.254")  # cloud metadata
    assert _addr_blocked("::1")
    assert _addr_blocked("::ffff:127.0.0.1")  # IPv4-mapped IPv6 loopback
    assert not _addr_blocked("10.0.0.5")  # RFC1918 allowed
    assert not _addr_blocked("93.184.216.34")  # public


def test_dns_name_resolving_to_loopback_is_blocked(monkeypatch):
    # The core bypass: a DNS name (passes the literal check) that resolves to
    # loopback / metadata must now be rejected at call time.
    with pytest.raises(ValueError):
        _run("evil.attacker.com", monkeypatch, ["127.0.0.1"])
    with pytest.raises(ValueError):
        _run("metadata.attacker.com", monkeypatch, ["169.254.169.254"])


def test_dns_name_resolving_to_private_is_allowed(monkeypatch):
    # RFC1918 stays allowed by design (agents on private networks).
    _run("vector.internal", monkeypatch, ["10.1.2.3"])


def test_any_blocked_ip_in_a_multi_record_answer_rejects(monkeypatch):
    # DNS-rebind-ish: a name resolving to both a public and an internal IP is
    # rejected (we don't get to pick which the connector would use).
    with pytest.raises(ValueError):
        _run("mixed.attacker.com", monkeypatch, ["93.184.216.34", "127.0.0.1"])


def test_empty_host_rejected():
    with pytest.raises(ValueError):
        asyncio.run(assert_resolved_host_public(""))
