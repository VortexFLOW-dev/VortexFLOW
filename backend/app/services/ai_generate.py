# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""AI VRL generation — the generate → validate → self-repair loop (VRL/AI plan B3).

Flow per the plan: take a natural-language intent + a sample event, ask the model
for VRL, **compile it with the bundled `vector` binary** (P2's ``run_vrl``), and on
a compile/runtime error feed Vector's diagnostic back and regenerate — bounded.
Only VRL that provably compiles is returned, with before/after on the real event.

**Security — this is the first code that sends *sampled event data* off-box.** Two
things matter here and are unit-testable:

1. :func:`redact_event` strips the operator-configured ``redact_fields`` (dotted
   paths) from the copy of the event that goes **to the model** — replacing the
   value with ``[REDACTED]`` so the model sees the field exists but not its data.
   The decision (B1) is send-raw-by-default + opt-in redaction; this enforces it.
2. Validation (`run_vrl`) runs against the **original, unredacted** event — the
   redaction gates egress only, never the local compile-check or the before/after
   the user sees.

Upstream errors arrive already sanitized from :mod:`app.services.ai_client`.
"""

import copy
import json
import re
from dataclasses import dataclass

from app.services import ai_client
from app.services.vrl_runner import run_vrl

REDACTED = "[REDACTED]"

# Bound the prompt: a giant event would balloon cost/latency and context.
MAX_EVENT_CHARS = 50_000


def redact_event(event: dict, fields: list[str]) -> dict:
    """Return a deep copy with each dotted ``fields`` path's value masked.

    A path that doesn't exist is silently skipped. Only the value is replaced
    (with ``[REDACTED]``) so the model still learns the field's shape/presence.

    Limitation (by design, opt-in feature): descends **dicts only** — a path
    through a list (e.g. ``items.0.ssn``) is not masked. Array/wildcard paths are
    a future enhancement; this is best-effort redaction, not a guarantee. The
    default posture is send-raw (no redaction).
    """
    out = copy.deepcopy(event)
    for path in fields:
        parts = [p for p in path.split(".") if p]
        if not parts:
            continue
        node = out
        ok = True
        for key in parts[:-1]:
            if isinstance(node, dict) and key in node:
                node = node[key]
            else:
                ok = False
                break
        if ok and isinstance(node, dict) and parts[-1] in node:
            node[parts[-1]] = REDACTED
    return out


_FENCE_RE = re.compile(r"```(?:vrl|ruby|text)?\s*\n?(.*?)```", re.DOTALL)


def extract_vrl(text: str) -> str:
    """Pull VRL out of a model response — unwrap a ``` fence if present."""
    if not text:
        return ""
    m = _FENCE_RE.search(text)
    if m:
        return m.group(1).strip()
    return text.strip()


_SYSTEM = (
    "You are an expert in Vector Remap Language (VRL), the transform language used "
    "by Vector (vector.dev). Write VRL that transforms the given sample event to "
    "satisfy the user's intent.\n"
    "Rules:\n"
    "- Output ONLY the VRL program. No prose, no explanation, no markdown fences.\n"
    "- The event is available as the root object (use `.field` to access).\n"
    "- Prefer fallible operators with error handling (e.g. `, err =` or `??`).\n"
    "- Keep it minimal and correct; do not invent fields not implied by the intent."
)


def _build_user_prompt(
    intent: str,
    sample_json: str,
    current_vrl: str,
    last_vrl: str,
    last_error: str,
) -> str:
    parts = [f"Intent: {intent}", "", f"Sample event (JSON):\n{sample_json}"]
    if current_vrl.strip():
        parts += ["", "Refine this existing VRL:", current_vrl.strip()]
    if last_error:
        parts += [
            "",
            "Your previous VRL failed to compile/run. Fix it.",
            f"Previous VRL:\n{last_vrl}",
            f"Vector error:\n{last_error}",
        ]
    parts += ["", "Return the corrected VRL program only."]
    return "\n".join(parts)


@dataclass
class GenerateResult:
    ok: bool
    vrl: str
    before: dict | None
    after: dict | None
    attempts: int
    error: str | None
    source: str


async def generate(
    *,
    raw: dict,
    secret_key: str,
    intent: str,
    event: dict,
    current_vrl: str = "",
    max_retries: int = 3,
) -> GenerateResult:
    """Run the bounded generate→validate→repair loop. Never raises for normal
    failures — returns ``ok=False`` with the last candidate + sanitized error."""
    retries = max(1, min(int(max_retries), 3))

    # Redact ONLY the copy sent to the model; validate against the real event.
    redact_fields = [str(f) for f in raw.get("redact_fields", []) if str(f).strip()]
    sample_for_model = redact_event(event, redact_fields)
    sample_json = json.dumps(sample_for_model, ensure_ascii=False, default=str)[
        :MAX_EVENT_CHARS
    ]

    last_vrl = ""
    last_error = ""
    source = "unavailable"

    for attempt in range(1, retries + 1):
        user = _build_user_prompt(
            intent, sample_json, current_vrl, last_vrl, last_error
        )
        try:
            raw_text = await ai_client.complete(
                raw=raw,
                secret_key=secret_key,
                system=_SYSTEM,
                user=user,
                max_tokens=2048,
                timeout_s=60.0,
            )
        except ai_client.AiNotConfigured as exc:
            return GenerateResult(
                False, last_vrl, None, None, attempt, str(exc), source
            )
        except ai_client.AiError as exc:
            return GenerateResult(
                False, last_vrl, None, None, attempt, str(exc), source
            )

        vrl = extract_vrl(raw_text)
        last_vrl = vrl
        if not vrl:
            last_error = "the model returned no VRL"
            continue

        result = await run_vrl(vrl, event)  # original, unredacted event
        source = result.source
        if result.ok:
            return GenerateResult(
                ok=True,
                vrl=vrl,
                before=event,
                after=result.output,
                attempts=attempt,
                error=None,
                source=source,
            )
        last_error = (result.error or "")[:4000]

    return GenerateResult(
        ok=False,
        vrl=last_vrl,
        before=event,
        after=None,
        attempts=retries,
        error=last_error or "generation failed",
        source=source,
    )
