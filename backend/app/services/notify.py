# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Outbound notification delivery — Stage 3.

Turns event *transitions* (opened / resolved) into durable outbox rows
(``enqueue_deliveries``) and drains them to external channels with retry
(``dispatch_pending``). Per-type send: webhook / Slack / Teams / email.

Only the background worker calls
``dispatch_pending`` — single delivery driver, no double-sends.
"""

import asyncio
import json
import logging
import smtplib
import ssl
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Optional

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.event import Event
from app.models.notification import NotificationChannel, NotificationDelivery
from app.services import cert_crypto

logger = logging.getLogger(__name__)

HTTP_TIMEOUT = 10.0  # seconds
SMTP_TIMEOUT = 15.0
DISPATCH_BATCH = 50
MAX_ATTEMPTS = 5
# Backoff per *failed* attempt number (1-indexed). After MAX_ATTEMPTS → failed.
_BACKOFF = [
    timedelta(seconds=30),
    timedelta(minutes=2),
    timedelta(minutes=10),
    timedelta(minutes=30),
]

_SEVERITY_RANK = {"info": 0, "warning": 1, "critical": 2}


@dataclass
class EventView:
    """The event fields a channel renders — decoupled from the ORM so the test
    path can synthesize one without touching the events table."""

    event_id: str
    kind: str
    severity: str
    title: str
    body: Optional[str]
    resource_type: Optional[str]
    resource_id: Optional[str]

    @classmethod
    def from_event(cls, e: Event) -> "EventView":
        return cls(
            event_id=e.id,
            kind=e.kind,
            severity=e.severity,
            title=e.title,
            body=e.body,
            resource_type=e.resource_type,
            resource_id=e.resource_id,
        )


def _severity_meets(event_severity: str, min_severity: str) -> bool:
    return _SEVERITY_RANK.get(event_severity, 1) >= _SEVERITY_RANK.get(min_severity, 1)


def _decode_secret(channel: NotificationChannel) -> dict:
    if not channel.secret_encrypted:
        return {}
    try:
        return json.loads(
            cert_crypto.decrypt(channel.secret_encrypted, settings.secret_key)
        )
    except Exception:
        logger.error("notify: failed to decode secret for channel %s", channel.id)
        return {}


def _decode_config(channel: NotificationChannel) -> dict:
    try:
        return json.loads(channel.config_json or "{}")
    except json.JSONDecodeError:
        return {}


# ─── Enqueue ──────────────────────────────────────────────────────────────────


async def enqueue_deliveries(
    db: AsyncSession,
    opened: list[Event],
    resolved: list[Event],
) -> None:
    """Create outbox rows for transitions. Idempotent — the unique index on
    (event_id, channel_id, transition) + ON CONFLICT DO NOTHING dedups across
    concurrent callers (worker + dashboard poll)."""
    if not opened and not resolved:
        return

    channels = (
        (
            await db.execute(
                select(NotificationChannel).where(NotificationChannel.enabled.is_(True))
            )
        )
        .scalars()
        .all()
    )
    if not channels:
        return

    for ev in opened:
        for ch in channels:
            if _severity_meets(ev.severity, ch.min_severity):
                await _insert_delivery(db, ev.id, ch.id, "opened")

    for ev in resolved:
        for ch in channels:
            if not ch.notify_on_resolve:
                continue
            # Enqueue the all-clear iff we enqueued an open for this pair (any
            # status). Whether to actually *send* it — gated on the open having
            # been delivered — is decided at dispatch time, so an open that is
            # still pending/retrying when the condition clears doesn't lose its
            # recovery notification (it just waits for the open to land first).
            has_open = await db.scalar(
                select(NotificationDelivery.id).where(
                    NotificationDelivery.event_id == ev.id,
                    NotificationDelivery.channel_id == ch.id,
                    NotificationDelivery.transition == "opened",
                )
            )
            if has_open:
                await _insert_delivery(db, ev.id, ch.id, "resolved")

    await db.commit()


async def _insert_delivery(
    db: AsyncSession, event_id: str, channel_id: str, transition: str
) -> None:
    stmt = (
        pg_insert(NotificationDelivery)
        .values(event_id=event_id, channel_id=channel_id, transition=transition)
        .on_conflict_do_nothing(index_elements=["event_id", "channel_id", "transition"])
    )
    await db.execute(stmt)


# ─── Dispatch ─────────────────────────────────────────────────────────────────


async def dispatch_pending(db: AsyncSession) -> int:
    """Drain due pending deliveries. Returns the number attempted.

    Each row is claimed with SELECT ... FOR UPDATE SKIP LOCKED before its send, so
    running more than one dispatcher (e.g. multiple backend replicas) cannot
    double-send: a row locked by one worker is skipped by the others, and the
    per-row commit both persists the outcome and releases the lock.
    """
    now = datetime.now(timezone.utc)
    candidate_ids = (
        (
            await db.execute(
                select(NotificationDelivery.id)
                .where(
                    NotificationDelivery.status == "pending",
                    NotificationDelivery.next_attempt_at <= now,
                )
                .order_by(NotificationDelivery.next_attempt_at)
                .limit(DISPATCH_BATCH)
            )
        )
        .scalars()
        .all()
    )
    if not candidate_ids:
        return 0

    attempted = 0
    for d_id in candidate_ids:
        # Claim the row exclusively for the duration of this send. SKIP LOCKED
        # makes a concurrent dispatcher move on rather than block or double-send;
        # the status filter drops rows already processed since the candidate list
        # was read.
        d = (
            await db.execute(
                select(NotificationDelivery)
                .where(
                    NotificationDelivery.id == d_id,
                    NotificationDelivery.status == "pending",
                )
                .with_for_update(skip_locked=True)
            )
        ).scalar_one_or_none()
        if d is None:
            continue
        attempted += 1

        channel = await db.get(NotificationChannel, d.channel_id)
        event = await db.get(Event, d.event_id)
        if channel is None or event is None:
            d.status = "failed"
            d.last_error = "channel or event no longer exists"
        elif not channel.enabled:
            d.status = "failed"
            d.last_error = "channel disabled"
        elif d.transition == "resolved" and not await _resolve_ready(db, d):
            # Open hasn't landed yet — defer the all-clear without burning an
            # attempt. _resolve_ready may itself mark this failed (open gave up).
            pass
        else:
            try:
                await _send(channel, EventView.from_event(event), d.transition)
            except Exception as e:  # noqa: BLE001 — any send failure is retryable
                await _record_failure(d, channel, str(e), now)
            else:
                now2 = datetime.now(timezone.utc)
                d.status = "sent"
                d.sent_at = now2
                channel.last_success_at = now2
                channel.last_attempt_at = now2
                channel.last_error = None
        # Commit per row: releases the FOR UPDATE lock and persists the outcome
        # immediately, so an external _send that already went out is not repeated
        # if the worker is cancelled (shutdown) mid-batch.
        await db.commit()

    return attempted


async def _resolve_ready(db: AsyncSession, d: NotificationDelivery) -> bool:
    """A 'resolved' delivery may send only once its matching 'opened' delivery
    was sent. If the open is still pending, defer (return False, leave pending).
    If the open ultimately failed, the alert never fired — drop the all-clear."""
    open_status = await db.scalar(
        select(NotificationDelivery.status).where(
            NotificationDelivery.event_id == d.event_id,
            NotificationDelivery.channel_id == d.channel_id,
            NotificationDelivery.transition == "opened",
        )
    )
    if open_status == "sent":
        return True
    if open_status == "failed" or open_status is None:
        d.status = "failed"
        d.last_error = "open notification was never delivered"
        return False
    # open still pending/retrying — check back next tick
    d.next_attempt_at = datetime.now(timezone.utc) + _BACKOFF[0]
    return False


async def _record_failure(
    d: NotificationDelivery, channel: NotificationChannel, err: str, now: datetime
) -> None:
    err = err[:500]
    d.attempts += 1
    d.last_error = err
    channel.last_attempt_at = now
    channel.last_error = err
    if d.attempts >= MAX_ATTEMPTS:
        d.status = "failed"
        logger.warning(
            "notify: delivery %s to channel %s gave up after %d attempts: %s",
            d.id,
            channel.id,
            d.attempts,
            err,
        )
    else:
        d.next_attempt_at = now + _BACKOFF[min(d.attempts - 1, len(_BACKOFF) - 1)]


# ─── Send (per channel type) ──────────────────────────────────────────────────


async def send_test(channel: NotificationChannel) -> None:
    """Drive the real send path with a synthetic event (Send test button)."""
    ev = EventView(
        event_id="test",
        kind="test",
        severity="warning",
        title=f"VortexFlow test notification — {channel.name}",
        body="If you can see this, the channel is configured correctly.",
        resource_type=None,
        resource_id=None,
    )
    await _send(channel, ev, "test")


async def _send(channel: NotificationChannel, ev: EventView, transition: str) -> None:
    secret = _decode_secret(channel)
    config = _decode_config(channel)
    if channel.type == "webhook":
        await _send_webhook(secret, config, ev, transition)
    elif channel.type == "slack":
        await _send_slack(secret, ev, transition)
    elif channel.type == "teams":
        await _send_teams(secret, ev, transition)
    elif channel.type == "email":
        await _send_email(secret, config, ev, transition)
    else:
        raise ValueError(f"unknown channel type: {channel.type}")
    logger.info(
        "notify: sent %s/%s for event %s via %s channel %s",
        ev.kind,
        transition,
        ev.event_id,
        channel.type,
        channel.id,
    )


def _status_word(transition: str) -> str:
    return "resolved" if transition == "resolved" else "firing"


async def _post_json(url: str, payload: dict, headers: Optional[dict] = None) -> None:
    """POST JSON, raising a URL-free error on failure. Slack/Teams/webhook URLs
    embed the auth token, so we never let httpx's URL-bearing exception strings
    propagate into stored ``last_error`` or the test response."""
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            r = await client.post(url, json=payload, headers=headers or {})
            r.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise RuntimeError(f"HTTP {e.response.status_code} from endpoint") from None
    except httpx.RequestError as e:
        raise RuntimeError(f"request failed: {type(e).__name__}") from None


async def _send_webhook(
    secret: dict, config: dict, ev: EventView, transition: str
) -> None:
    url = secret.get("url")
    if not url:
        raise ValueError("webhook channel has no URL")
    payload = {
        "event_id": ev.event_id,
        "kind": ev.kind,
        "severity": ev.severity,
        "title": ev.title,
        "body": ev.body,
        "transition": transition,
        "status": _status_word(transition),
        "resource_type": ev.resource_type,
        "resource_id": ev.resource_id,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    await _post_json(url, payload, secret.get("headers") or {})


def _emoji(severity: str, transition: str) -> str:
    if transition == "resolved":
        return "✅"
    return "🔴" if severity == "critical" else "🟠"


async def _send_slack(secret: dict, ev: EventView, transition: str) -> None:
    url = secret.get("url")
    if not url:
        raise ValueError("slack channel has no URL")
    prefix = "Resolved: " if transition == "resolved" else ""
    text = f"{_emoji(ev.severity, transition)} *{prefix}{ev.title}*"
    if ev.body:
        text += f"\n{ev.body}"
    await _post_json(url, {"text": text})


async def _send_teams(secret: dict, ev: EventView, transition: str) -> None:
    url = secret.get("url")
    if not url:
        raise ValueError("teams channel has no URL")
    color = (
        "2EB67D"
        if transition == "resolved"
        else ("E01E5A" if ev.severity == "critical" else "ECB22E")
    )
    prefix = "Resolved: " if transition == "resolved" else ""
    card = {
        "@type": "MessageCard",
        "@context": "http://schema.org/extensions",
        "themeColor": color,
        "summary": ev.title,
        "title": f"{prefix}{ev.title}",
        "text": ev.body or "",
    }
    await _post_json(url, card)


async def _send_email(
    secret: dict, config: dict, ev: EventView, transition: str
) -> None:
    host = config.get("host")
    to_addrs = config.get("to_addrs") or []
    from_addr = config.get("from_addr")
    if not host or not to_addrs or not from_addr:
        raise ValueError("email channel needs host, from_addr, and to_addrs")
    port = int(config.get("port") or 587)
    use_tls = bool(config.get("use_tls", True))
    username = config.get("username") or from_addr
    password = secret.get("password")

    prefix = "Resolved: " if transition == "resolved" else ""
    msg = EmailMessage()
    msg["Subject"] = f"[VortexFlow] {prefix}{ev.title}"
    msg["From"] = from_addr
    msg["To"] = ", ".join(to_addrs)
    body = ev.body or ev.title
    msg.set_content(f"{prefix}{ev.title}\n\n{body}\n\nSeverity: {ev.severity}")

    # smtplib is blocking — run it off the event loop.
    await asyncio.to_thread(_smtp_send, host, port, use_tls, username, password, msg)


def _smtp_send(
    host: str,
    port: int,
    use_tls: bool,
    username: Optional[str],
    password: Optional[str],
    msg: EmailMessage,
) -> None:
    with smtplib.SMTP(host, port, timeout=SMTP_TIMEOUT) as server:
        if use_tls:
            # Verify the mail server's certificate + hostname (default context)
            # so SMTP credentials can't be MITM'd on the path to the relay.
            server.starttls(context=ssl.create_default_context())
        if username and password:
            server.login(username, password)
        server.send_message(msg)
