# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""
Generic OIDC authentication service.

Covers: Google Workspace, Okta, Auth0, Keycloak, JumpCloud, Ping (OIDC mode),
        Dex, Authentik, and any RFC 8414-compliant IdP.

Authorization-code flow with PKCE (S256):
  1. ``get_discovery``  — fetch + cache the IdP's OpenID configuration.
  2. ``build_auth_url`` — build the authorization-endpoint redirect (state + PKCE
     challenge + nonce). state/verifier/nonce are held server-side (Redis) by the
     calling route, NOT in this stateless module.
  3. ``exchange_and_verify`` — exchange the code for tokens, then **cryptographically
     verify the ID token against the IdP's JWKS** (signature, issuer, audience,
     expiry) and check the nonce. Only then are the claims trusted.
  4. Resolve a VortexFlow role from the groups claim + role_mappings.

Security note: a previous version base64-decoded the ID token WITHOUT verifying
its signature — any party able to reach the callback could forge identity. We now
verify against JWKS. Do not reintroduce unverified decoding.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
from jose import jwt
from jose.exceptions import JOSEError, JWTError

from app.core.config import OIDCConfig

# Allowed signature algorithms per JWK key type. We never accept symmetric
# (HMAC) algorithms for an OIDC ID token — the IdP signs with an asymmetric key
# published in its JWKS — which structurally defeats RSA-pubkey-as-HMAC
# algorithm-confusion regardless of what the token header claims.
_ALGS_BY_KTY: dict[str, list[str]] = {
    "RSA": ["RS256", "RS384", "RS512", "PS256", "PS384", "PS512"],
    "EC": ["ES256", "ES384", "ES512"],
    "OKP": ["EdDSA"],
}

# In-process caches (cleared on process restart — config changes that move the
# issuer/JWKS take effect on restart, consistent with the rest of SSO settings).
_discovery_cache: dict[str, dict] = {}
_jwks_cache: dict[str, dict] = {}

_HTTP_TIMEOUT = 15


@dataclass
class OIDCAuthResult:
    username: str
    email: str
    display_name: str
    role: str
    external_id: str  # 'sub' claim from the verified ID token
    groups: list[str]
    # Tri-state: True/False if the IdP asserted email_verified, None if absent.
    # The callback uses email as a JIT identity key, so an explicit False is fatal.
    email_verified: bool | None


class OIDCAuthError(Exception):
    """Raised when the OIDC flow fails for any reason."""


def _resolve_role(groups: list[str], cfg: OIDCConfig) -> str:
    groups_lower = {g.lower() for g in groups}
    for mapping in cfg.role_mappings:
        target = (mapping.group or mapping.group_id or "").lower()
        if target and target in groups_lower:
            return mapping.role
    return cfg.default_role


async def get_discovery(cfg: OIDCConfig) -> dict:
    """Fetch and cache the IdP OpenID Connect discovery document."""
    if not cfg.issuer:
        raise OIDCAuthError("OIDC issuer is not configured")
    url = cfg.issuer.rstrip("/") + "/.well-known/openid-configuration"
    if url in _discovery_cache:
        return _discovery_cache[url]
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(url, timeout=_HTTP_TIMEOUT)
            r.raise_for_status()
            meta = r.json()
    except httpx.HTTPError as exc:
        raise OIDCAuthError(f"Failed to fetch OIDC discovery document: {exc}")
    for required in ("authorization_endpoint", "token_endpoint", "jwks_uri", "issuer"):
        if required not in meta:
            raise OIDCAuthError(f"OIDC discovery document missing '{required}'")
    _discovery_cache[url] = meta
    return meta


async def _get_jwks(jwks_uri: str) -> dict:
    if jwks_uri in _jwks_cache:
        return _jwks_cache[jwks_uri]
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(jwks_uri, timeout=_HTTP_TIMEOUT)
            r.raise_for_status()
            jwks = r.json()
    except httpx.HTTPError as exc:
        raise OIDCAuthError(f"Failed to fetch IdP JWKS: {exc}")
    _jwks_cache[jwks_uri] = jwks
    return jwks


def build_pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) for PKCE S256."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


async def build_auth_url(
    cfg: OIDCConfig, state: str, code_verifier: str, nonce: str
) -> str:
    """Return the IdP authorization URL to redirect the user to."""
    if not cfg.enabled:
        raise OIDCAuthError("Generic OIDC provider is not enabled")
    if not cfg.client_id or not cfg.redirect_uri:
        raise OIDCAuthError("OIDC client_id and redirect_uri must be configured")
    meta = await get_discovery(cfg)

    digest = hashlib.sha256(code_verifier.encode()).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()

    params = {
        "response_type": "code",
        "client_id": cfg.client_id,
        "redirect_uri": cfg.redirect_uri,
        "scope": " ".join(cfg.scopes),
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return meta["authorization_endpoint"] + "?" + urlencode(params)


async def exchange_and_verify(
    cfg: OIDCConfig, code: str, code_verifier: str, nonce: str
) -> OIDCAuthResult:
    """Exchange the auth code for tokens, verify the ID token, return user info."""
    if not cfg.enabled:
        raise OIDCAuthError("Generic OIDC provider is not enabled")

    meta = await get_discovery(cfg)

    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                meta["token_endpoint"],
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": cfg.redirect_uri,
                    "client_id": cfg.client_id,
                    "client_secret": cfg.client_secret,
                    "code_verifier": code_verifier,
                },
                timeout=_HTTP_TIMEOUT,
            )
    except httpx.HTTPError as exc:
        raise OIDCAuthError(f"Token exchange request failed: {exc}")

    if r.status_code != 200:
        raise OIDCAuthError(f"Token exchange failed ({r.status_code})")

    tokens = r.json()
    if "error" in tokens:
        raise OIDCAuthError(
            f"Token error: {tokens.get('error_description', tokens['error'])}"
        )

    id_token = tokens.get("id_token")
    if not id_token:
        raise OIDCAuthError("IdP did not return an id_token")

    claims = await _verify_id_token(cfg, meta, id_token, nonce)

    # The verified ID token is authoritative. Optionally enrich with userinfo
    # (some IdPs put groups only there), but never let userinfo override identity
    # claims that were cryptographically bound in the ID token.
    access_token = tokens.get("access_token")
    if access_token and meta.get("userinfo_endpoint"):
        try:
            async with httpx.AsyncClient() as client:
                ur = await client.get(
                    meta["userinfo_endpoint"],
                    headers={"Authorization": f"Bearer {access_token}"},
                    timeout=_HTTP_TIMEOUT,
                )
            if ur.status_code == 200:
                info = ur.json()
                # userinfo 'sub' MUST match the ID token 'sub' (OIDC §5.3.2)
                if info.get("sub") and info.get("sub") != claims.get("sub"):
                    raise OIDCAuthError("userinfo 'sub' does not match ID token")
                for k, v in info.items():
                    claims.setdefault(k, v)
        except httpx.HTTPError:
            pass  # userinfo is best-effort enrichment; ID token already verified

    sub = str(claims.get("sub") or "")
    if not sub:
        raise OIDCAuthError("Verified token has no 'sub' claim")
    email = str(claims.get(cfg.email_claim) or claims.get("email") or "")
    username = str(claims.get(cfg.username_claim) or email or sub)
    display_name = str(
        claims.get("name") or claims.get("preferred_username") or username
    )

    groups_raw = claims.get(cfg.groups_claim, [])
    if isinstance(groups_raw, str):
        groups_raw = [groups_raw]
    groups = [str(g) for g in groups_raw] if isinstance(groups_raw, list) else []

    return OIDCAuthResult(
        username=username,
        email=email,
        display_name=display_name,
        role=_resolve_role(groups, cfg),
        external_id=sub,
        groups=groups,
        email_verified=_coerce_verified(claims.get("email_verified")),
    )


def _coerce_verified(raw: object) -> bool | None:
    """Normalize the email_verified claim (some IdPs send the string 'true')."""
    if raw is None:
        return None
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() == "true"


async def _verify_id_token(
    cfg: OIDCConfig, meta: dict, id_token: str, nonce: str
) -> dict:
    """Verify the ID token signature against JWKS + iss/aud/exp + nonce."""
    try:
        header = jwt.get_unverified_header(id_token)
    except JWTError as exc:
        raise OIDCAuthError(f"Malformed ID token: {exc}")

    alg = header.get("alg", "RS256")
    if alg == "none":
        raise OIDCAuthError("ID token uses 'alg: none' — rejected")

    jwks = await _get_jwks(meta["jwks_uri"])
    keys = jwks.get("keys", [])
    kid = header.get("kid")
    key = next((k for k in keys if k.get("kid") == kid), None)
    if key is None and len(keys) == 1:
        key = keys[0]  # single-key IdP without kid in header
    if key is None:
        # Key rotation: refresh JWKS once and retry.
        _jwks_cache.pop(meta["jwks_uri"], None)
        jwks = await _get_jwks(meta["jwks_uri"])
        key = next((k for k in jwks.get("keys", []) if k.get("kid") == kid), None)
    if key is None:
        raise OIDCAuthError("No matching JWKS key for ID token")

    # Pin the accepted algorithms to what the *selected key* supports, not the
    # attacker-controlled header. Defeats algorithm-confusion structurally.
    allowed = _ALGS_BY_KTY.get(str(key.get("kty", "")))
    if not allowed:
        raise OIDCAuthError(f"Unsupported JWKS key type: {key.get('kty')!r}")
    if key.get("alg"):
        allowed = [a for a in allowed if a == key["alg"]] or allowed
    if alg not in allowed:
        raise OIDCAuthError(f"ID token alg {alg!r} not permitted for this key")

    try:
        claims = jwt.decode(
            id_token,
            key,
            algorithms=allowed,
            audience=cfg.client_id,
            issuer=meta["issuer"],
            options={
                "verify_signature": True,
                "verify_aud": True,
                "verify_iss": True,
                "verify_exp": True,
                "verify_at_hash": False,  # we don't pass the access_token
            },
        )
    except JOSEError as exc:
        # JOSEError covers JWTError + JWKError (e.g. an HMAC-confusion attempt
        # raises JWKError, a sibling of JWTError) → one clean failure path.
        raise OIDCAuthError(f"ID token verification failed: {exc}")

    token_nonce = claims.get("nonce")
    if not token_nonce or not secrets.compare_digest(str(token_nonce), nonce):
        raise OIDCAuthError("ID token nonce mismatch")

    return claims
