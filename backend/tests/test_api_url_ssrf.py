# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Agent/instance api_url must reject loopback + link-local (SSRF) — auth F8."""

import os

os.environ.setdefault(
    "VORTEXFLOW_SECRET_KEY",
    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
)

import pytest  # noqa: E402

from app.core.netutil import validate_agent_api_url  # noqa: E402
from app.schemas.instance import InstanceCreate, InstanceUpdate  # noqa: E402
from app.schemas.fleet import RegisterAgentRequest  # noqa: E402

BLOCKED = [
    "http://127.0.0.1:8686",
    "http://169.254.169.254/latest/meta-data/",  # cloud metadata
    "https://[::1]:8686",
]
ALLOWED = [
    "http://10.0.0.5:8686",  # RFC1918 — allowed by design
    "http://192.168.1.10:8686",
    "https://vector.internal.example.com",
]


@pytest.mark.parametrize("url", BLOCKED)
def test_helper_blocks_ssrf(url):
    with pytest.raises(ValueError):
        validate_agent_api_url(url)


@pytest.mark.parametrize("url", ALLOWED)
def test_helper_allows_private_and_dns(url):
    assert validate_agent_api_url(url) == url.rstrip("/")


@pytest.mark.parametrize("url", BLOCKED)
def test_instance_create_blocks_ssrf(url):
    with pytest.raises(ValueError):
        InstanceCreate(label="x", api_url=url)


@pytest.mark.parametrize("url", BLOCKED)
def test_instance_update_blocks_ssrf(url):
    # Update previously had NO api_url validator (the F8 gap).
    with pytest.raises(ValueError):
        InstanceUpdate(api_url=url)


def test_instance_update_allows_none():
    assert InstanceUpdate(api_url=None).api_url is None


@pytest.mark.parametrize("url", BLOCKED)
def test_register_agent_blocks_ssrf(url):
    with pytest.raises(ValueError):
        RegisterAgentRequest(hostname="h", api_url=url)
