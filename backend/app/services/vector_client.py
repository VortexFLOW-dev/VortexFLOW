# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""
Vector API client.

Vector exposes two relevant endpoints on its API port (default :8686):
  GET  /health          — liveness + version
  POST /graphql         — topology, component metrics (read-only)
  WS   /graphql         — subscriptions (tap/outputEvents)

The GraphQL API is read-only. Config changes are made by writing YAML files
to the watched config directory (local mode) or via the VortexFlow agent
(agent mode) — not through the Vector API.

All functions take a base api_url (e.g. "http://localhost:8686") and return
typed dicts. They raise VectorClientError on connection/timeout failures so
callers can surface a clean "unreachable" state rather than a 500.
"""

import json
import logging
import ssl
from collections.abc import AsyncGenerator
from typing import Any, Optional
from urllib.parse import urlparse

import httpx
import websockets
import websockets.exceptions

log = logging.getLogger("vortexflow.vector")

_TIMEOUT = httpx.Timeout(5.0, connect=3.0)


def _ssl_context(tls_verify: bool, tls_ca_cert: Optional[str]) -> bool | ssl.SSLContext:
    """Build an httpx-compatible SSL context from instance TLS settings."""
    if not tls_verify:
        return False
    if tls_ca_cert:
        ctx = ssl.create_default_context()
        ctx.load_verify_locations(cadata=tls_ca_cert)
        return ctx
    return True  # httpx default — verify using system CAs


# GraphQL query: fetch all component IDs, types, and their inputs
_TOPOLOGY_QUERY = """
query Topology {
  components {
    ... on Source {
      componentId
      componentType
      outputs { outputId receivedEventsThroughput sentEventsThroughput }
    }
    ... on Transform {
      componentId
      componentType
      inputs { componentId }
      outputs { outputId receivedEventsThroughput sentEventsThroughput }
    }
    ... on Sink {
      componentId
      componentType
      inputs { componentId }
      receivedEventsThroughput
    }
  }
}
"""

# Simpler query just for health check — avoids topology parse on ping
_VERSION_QUERY = """
query Version {
  meta { versionString }
}
"""

# GraphQL subscription: tap live output events from one component.
# Vector uses the graphql-ws protocol (not graphql-transport-ws).
# Schema is for Vector 0.4x: `outputEventsByComponentIdPatterns` returns a list
# of the OutputEventsPayload union (Log | Metric | Trace | EventNotification),
# and each member exposes `string`/`json` rather than the old typed `fields`
# map. `outputsPatterns` accepts glob patterns; an exact component id matches
# itself.
_TAP_SUBSCRIPTION = """
subscription TapComponent($patterns: [String!]!, $limit: Int!) {
  outputEventsByComponentIdPatterns(outputsPatterns: $patterns, limit: $limit, interval: 500) {
    __typename
    ... on Log {
      componentId
      timestamp
      message
      string(encoding: JSON)
    }
    ... on Metric {
      componentId
      timestamp
      name
      kind
      string(encoding: JSON)
    }
    ... on Trace {
      componentId
      string(encoding: JSON)
    }
    ... on EventNotification {
      message
    }
  }
}
"""


class VectorClientError(Exception):
    pass


async def get_health(
    api_url: str,
    tls_verify: bool = True,
    tls_ca_cert: Optional[str] = None,
) -> dict[str, Any]:
    """
    Fetch Vector health endpoint. Returns:
      { reachable: bool, vector_version: str|None, uptime_seconds: float|None, error: str|None }
    """
    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, verify=_ssl_context(tls_verify, tls_ca_cert)
        ) as client:
            r = await client.get(f"{api_url}/health")
            r.raise_for_status()
            data = r.json()
            return {
                "reachable": True,
                "vector_version": data.get("version"),
                "uptime_seconds": data.get("uptimeSecs"),
                "error": None,
            }
    except httpx.TimeoutException:
        return {
            "reachable": False,
            "vector_version": None,
            "uptime_seconds": None,
            "error": "Connection timed out",
        }
    except httpx.ConnectError:
        return {
            "reachable": False,
            "vector_version": None,
            "uptime_seconds": None,
            "error": "Connection refused",
        }
    except Exception as e:
        return {
            "reachable": False,
            "vector_version": None,
            "uptime_seconds": None,
            "error": str(e),
        }


async def get_topology(
    api_url: str,
    tls_verify: bool = True,
    tls_ca_cert: Optional[str] = None,
) -> dict[str, Any]:
    """
    Fetch component topology from Vector GraphQL API.
    Returns raw components list or raises VectorClientError.
    """
    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, verify=_ssl_context(tls_verify, tls_ca_cert)
        ) as client:
            r = await client.post(
                f"{api_url}/graphql",
                json={"query": _TOPOLOGY_QUERY},
                headers={"Content-Type": "application/json"},
            )
            r.raise_for_status()
            body = r.json()
            if "errors" in body:
                raise VectorClientError(f"GraphQL errors: {body['errors']}")
            return body.get("data", {})
    except VectorClientError:
        raise
    except httpx.TimeoutException as e:
        raise VectorClientError("Vector API timed out") from e
    except httpx.ConnectError as e:
        raise VectorClientError("Cannot connect to Vector API") from e
    except Exception as e:
        raise VectorClientError(str(e)) from e


async def get_component_metrics(
    api_url: str,
    component_id: str,
    tls_verify: bool = True,
    tls_ca_cert: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """
    Fetch per-component throughput metrics. Returns None if unreachable.
    """
    query = """
    query ComponentMetrics($id: String!) {
      component(componentId: $id) {
        ... on Source {
          componentId
          outputs { receivedEventsThroughput sentEventsThroughput sentBytesThroughput }
        }
        ... on Transform {
          componentId
          outputs { receivedEventsThroughput sentEventsThroughput }
        }
        ... on Sink {
          componentId
          receivedEventsThroughput
        }
      }
    }
    """
    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, verify=_ssl_context(tls_verify, tls_ca_cert)
        ) as client:
            r = await client.post(
                f"{api_url}/graphql",
                json={"query": query, "variables": {"id": component_id}},
                headers={"Content-Type": "application/json"},
            )
            r.raise_for_status()
            body = r.json()
            return body.get("data", {}).get("component")
    except Exception as e:
        log.warning("Failed to fetch metrics for %s: %s", component_id, e)
        return None


def _api_url_to_ws(api_url: str) -> str:
    """Convert http(s)://host:port → ws(s)://host:port."""
    parsed = urlparse(api_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return f"{scheme}://{parsed.netloc}"


async def tap_component(
    api_url: str,
    component_id: str,
    limit: int = 50,
    tls_verify: bool = True,
    tls_ca_cert: Optional[str] = None,
) -> AsyncGenerator[dict[str, Any], None]:
    """
    Stream live output events from a Vector component via GraphQL subscription.

    Uses the graphql-ws sub-protocol. Yields parsed event dicts.
    Stops after `limit` events or when the caller closes the generator.
    Raises VectorClientError if the connection cannot be established.
    """
    ws_url = f"{_api_url_to_ws(api_url)}/graphql"
    ssl_ctx: ssl.SSLContext | bool | None = _ssl_context(tls_verify, tls_ca_cert)
    received = 0

    try:
        ws_kwargs: dict[str, Any] = {
            "subprotocols": ["graphql-ws"],
            "open_timeout": 5,
            "close_timeout": 3,
        }
        if ws_url.startswith("wss://"):
            ws_kwargs["ssl"] = ssl_ctx
        async with websockets.connect(ws_url, **ws_kwargs) as ws:
            # graphql-ws handshake
            await ws.send(json.dumps({"type": "connection_init"}))
            ack = json.loads(await ws.recv())
            if ack.get("type") != "connection_ack":
                raise VectorClientError(
                    f"graphql-ws: expected connection_ack, got {ack.get('type')}"
                )

            # Start subscription
            await ws.send(
                json.dumps(
                    {
                        "type": "start",
                        "id": "tap-1",
                        "payload": {
                            "query": _TAP_SUBSCRIPTION,
                            # component_id may be a comma-separated list (e.g. a
                            # transform's inputs for a before/after compare tap) —
                            # each becomes its own glob pattern.
                            "variables": {
                                "patterns": [
                                    p.strip()
                                    for p in component_id.split(",")
                                    if p.strip()
                                ]
                                or [component_id],
                                "limit": limit,
                            },
                        },
                    }
                )
            )

            while received < limit:
                raw = await ws.recv()
                msg = json.loads(raw)
                msg_type = msg.get("type")

                if msg_type == "data":
                    payload = msg.get("payload", {})
                    if "errors" in payload:
                        yield {"error": str(payload["errors"])}
                        break
                    # The field returns a *list* of union events per push.
                    # `data` may be explicitly null on some frames, so coalesce
                    # before indexing.
                    data = payload.get("data") or {}
                    events = data.get("outputEventsByComponentIdPatterns") or []
                    for event in events:
                        if received >= limit:
                            break
                        yield event
                        # The "[tap] pattern matched" EventNotification is an
                        # info frame, not a sampled event — don't charge it
                        # against the user's max-events budget.
                        if event.get("__typename") != "EventNotification":
                            received += 1
                elif msg_type == "error":
                    yield {"error": str(msg.get("payload"))}
                    break
                elif msg_type == "complete":
                    break
                # ka (keepalive) — ignore

            # Cancel the subscription cleanly
            await ws.send(json.dumps({"type": "stop", "id": "tap-1"}))

    except websockets.exceptions.WebSocketException as e:
        raise VectorClientError(f"WebSocket error: {e}") from e
    except OSError as e:
        raise VectorClientError(f"Cannot connect to Vector API: {e}") from e
