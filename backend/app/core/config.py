# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from dataclasses import dataclass, field
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator
from typing import Optional


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="VORTEXFLOW_",
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )

    # App
    app_name: str = "VortexFlow"
    debug: bool = False
    secret_key: str  # required — set VORTEXFLOW_SECRET_KEY; generate with: python -c "import secrets; print(secrets.token_hex(32))"

    # Optional dedicated key for AT-REST encryption (component/SSO/AI secrets,
    # cert private keys, the deploy snapshot). When set, it decouples at-rest
    # encryption from JWT signing (secret_key), so the JWT secret can be rotated
    # without re-encrypting every stored secret, and a disclosure of one key does
    # not compromise the other. Leave UNSET to derive at-rest encryption from
    # secret_key (the historical behavior — no migration needed). Adopting it on
    # an EXISTING install requires re-encrypting stored secrets (see ADR-002);
    # a fresh install can just set it. JWT signing always uses secret_key.
    encryption_key: Optional[str] = None

    # Public base URL of this VortexFlow server (e.g. https://vf.example.com).
    # Used to generate the agent install one-liner and the metrics endpoint.
    # Required behind a reverse proxy — request.base_url would otherwise be the
    # internal backend address, which agents can't reach.
    public_url: Optional[str] = None

    # Extra browser origins allowed to call the API with credentials (CORS),
    # comma-separated. The standard deployment serves the UI from the same origin
    # as the API (nginx in front of this backend), which needs no entry here; set
    # this only when the UI is hosted on a different origin. `public_url` is
    # allowed automatically, and localhost dev origins are added when debug=True.
    cors_origins: str = ""

    # Database
    database_url: str = (
        "postgresql+asyncpg://vortexflow:vortexflow@localhost:5432/vortexflow"
    )

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # MCP server (Model Context Protocol). Off by default — when enabled, the
    # backend serves a read-only MCP endpoint at /mcp (streamable HTTP),
    # authenticated with personal access tokens. Writes are a separate, gated
    # follow-up. Enable with VORTEXFLOW_MCP_ENABLED=true.
    mcp_enabled: bool = False

    # VictoriaMetrics
    vm_url: str = "http://localhost:8428"

    # Directory holding prebuilt vortexflow-agent binaries, named
    # vortexflow-agent-{goos}-{goarch}. Served by GET /install/agent/{os}/{arch}
    # and downloaded by the install script. Populated by the image build
    # (agent `make release`).
    agent_bin_dir: str = "/app/agent-bin"

    # Path to the `vector` binary used for server-side `vector validate` (the
    # pre-deploy gate + the Config modal's Validate action). The backend image
    # bundles Vector; on dev boxes without it, validation degrades to
    # "unavailable" (non-blocking) rather than failing.
    vector_bin: str = "vector"

    # TLS cert dir shared with nginx. When set, the backend generates a
    # self-signed CA + server cert here on first boot (unless one exists) and
    # serves the CA at /install/ca.crt so agents can trust it. Leave unset to
    # disable (e.g. when TLS is terminated elsewhere).
    tls_cert_dir: Optional[str] = None

    # Auth
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 30
    algorithm: str = "HS256"

    # Session safeguards. Idle: a session is dropped after this many minutes with
    # no requests (sliding window, Redis-backed). Absolute: a session must
    # re-authenticate after this many hours regardless of activity. Enforcement
    # fails open if Redis is unavailable (tokens still expire normally).
    session_idle_timeout_minutes: int = 45
    session_absolute_hours: int = 12
    # `Secure` flag on the refresh-token cookie. Defaults True (production is
    # HTTPS): the cookie is then only ever sent over TLS. Set False ONLY for a
    # local dev server reached over plain http (otherwise the browser withholds
    # the cookie and refresh breaks). Deliberately NOT tied to `debug` — transport
    # security is orthogonal to debug logging.
    session_cookie_secure: bool = True
    # Trusted reverse proxies in front of the app (nginx = 1). The client IP is
    # read this many hops from the right of X-Forwarded-For so a spoofed header
    # can't forge it. Set 0 if the app is directly exposed (ignore XFF).
    trusted_proxy_count: int = 1

    # Bootstrap admin
    bootstrap_admin_email: str = "admin@example.com"
    bootstrap_admin_password: str = "ChangeMe123!"
    bootstrap_admin_name: str = "Admin"

    # Break-glass recovery. The one-time setup/recovery token is normally armed
    # only on a fresh install (no admin yet). Set this true to force-arm it for
    # a genuine locked-out-admin recovery, then unset it — otherwise a fresh
    # admin-granting token is printed to the logs on every restart.
    enable_recovery_token: bool = False

    # Demo mode (docker-compose.demo.yml only). Skips the forced bootstrap-admin
    # password rotation so the auto-registering demo agent — and a human poking
    # the UI with the documented demo creds — can use RBAC endpoints out of the
    # box. NEVER set this in production; the password-change gate is a real
    # security control there.
    demo_mode: bool = False

    # Optional bearer token required to POST metrics to the public /vm write proxy.
    # Unset (default) = the write path is open (historical behavior). When set,
    # nginx gates /vm/api/v1/write via an auth_request to /api/v1/vm/authorize,
    # and the agent presents this token (embedded in its Vector remote_write
    # sink) — closing anonymous metric-poisoning of the alerting pipeline.
    metrics_write_token: Optional[str] = None

    # Brute-force protection
    max_login_attempts: int = 5
    lockout_duration_seconds: int = 900
    ip_block_threshold: int = 20
    ip_block_duration_seconds: int = 3600
    # When Redis is unreachable the rate limiters can't count. Default False
    # (fail open) keeps the app usable during a Redis outage — a local Redis
    # outage usually means the whole stack is down anyway. Set True to fail
    # closed (deny the rate-limited action) for high-security deployments that
    # would rather reject requests than lose abuse protection. Either way, the
    # degradation is logged so an outage that drops protection is visible.
    rate_limit_fail_closed: bool = False

    # Data retention — a daily background sweep deletes rows older than N days
    # from the unbounded operational tables. 0 = keep forever (default; audit
    # logs are compliance-sensitive, so nothing is pruned unless you opt in).
    audit_retention_days: int = 0
    event_retention_days: int = 0
    notification_retention_days: int = 0
    retention_sweep_hours: int = 24  # how often the sweep runs

    # SSO — Azure Entra ID
    azure_tenant_id: Optional[str] = None
    azure_client_id: Optional[str] = None
    azure_client_secret: Optional[str] = None

    # SSO — Generic OIDC
    oidc_issuer: Optional[str] = None
    oidc_client_id: Optional[str] = None
    oidc_client_secret: Optional[str] = None
    oidc_display_name: str = "SSO"

    # SSO — SAML 2.0
    saml_idp_metadata_url: Optional[str] = None
    saml_idp_entity_id: Optional[str] = None
    saml_idp_sso_url: Optional[str] = None
    saml_idp_x509_cert: Optional[str] = None
    saml_sp_entity_id: Optional[str] = None
    saml_display_name: str = "SAML SSO"

    # SSO — LDAP
    ldap_url: Optional[str] = None
    ldap_bind_dn: Optional[str] = None
    ldap_bind_password: Optional[str] = None
    ldap_base_dn: Optional[str] = None
    ldap_user_filter: str = "(mail={username})"
    ldap_group_base_dn: Optional[str] = None

    @field_validator("secret_key")
    @classmethod
    def secret_key_must_be_set(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError(
                "VORTEXFLOW_SECRET_KEY must be at least 32 characters. "
                'Generate one with: python -c "import secrets; print(secrets.token_hex(32))"'
            )
        return v

    @field_validator("encryption_key")
    @classmethod
    def encryption_key_length(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and len(v) < 32:
            raise ValueError(
                "VORTEXFLOW_ENCRYPTION_KEY must be at least 32 characters."
            )
        return v

    @field_validator("metrics_write_token")
    @classmethod
    def metrics_write_token_charset(cls, v: Optional[str]) -> Optional[str]:
        # Embedded into the agent's Vector config (a YAML value inside a shell
        # heredoc). Constrain to a URL-safe token charset so a quote, backtick, or
        # `$` can never break the YAML or trigger shell expansion at (root) install
        # time. Generate: python -c "import secrets; print(secrets.token_urlsafe(32))"
        import re as _re

        if v is not None and not _re.fullmatch(r"[A-Za-z0-9._~+/=-]{16,}", v):
            raise ValueError(
                "VORTEXFLOW_METRICS_WRITE_TOKEN must be >=16 chars of "
                "[A-Za-z0-9._~+/=-] (a URL-safe token)."
            )
        return v

    @property
    def at_rest_key(self) -> str:
        """The key used for AT-REST encryption (Fernet). Prefers a dedicated
        ``encryption_key`` when set, else falls back to ``secret_key`` (historical
        behavior). JWT signing always uses ``secret_key`` directly — never this."""
        return self.encryption_key or self.secret_key


settings = Settings()


# ─── SSO provider configs (runtime dataclasses) ──────────────────────────────
#
# The SSO *settings* (what an admin saves in the Settings UI) live in the DB
# `system_settings` table as JSON. The auth *services* consume these typed
# dataclasses, built from that JSON by ``load_*_config`` (see app.services.sso_config).
# Keeping them here — not in the Pydantic settings models — means the services
# have a single, stable config contract independent of how the values are stored.


@dataclass
class RoleMappingEntry:
    """Map an IdP group (by name or object-id) to a VortexFlow role."""

    role: str
    group: Optional[str] = None  # group name / path (OIDC, SAML, LDAP)
    group_id: Optional[str] = None  # group object id (Azure)


@dataclass
class OIDCConfig:
    enabled: bool = False
    display_name: str = "SSO"
    issuer: str = ""  # e.g. https://idp.example.com/realms/main
    client_id: str = ""
    client_secret: str = ""
    redirect_uri: str = ""  # must exactly match an IdP-registered redirect URI
    scopes: list[str] = field(default_factory=lambda: ["openid", "profile", "email"])
    email_claim: str = "email"
    username_claim: str = "preferred_username"
    groups_claim: str = "groups"
    role_mappings: list[RoleMappingEntry] = field(default_factory=list)
    default_role: str = "viewer"

    @property
    def discovery_url(self) -> str:
        # The OIDC issuer IS the discovery base; the service appends
        # /.well-known/openid-configuration.
        return self.issuer


@dataclass
class SAMLConfig:
    enabled: bool = False
    # SP (us) — derived from public_url by the loader.
    sp_entity_id: str = ""
    acs_url: str = ""  # Assertion Consumer Service: where the IdP POSTs back
    name_id_format: str = "urn:oasis:names:tc:SAML:1.1:nameid-format:unspecified"
    # IdP — either a metadata URL (auto) or the manual trio below.
    idp_metadata_url: str = ""
    idp_entity_id: str = ""
    idp_sso_url: str = ""
    idp_x509_cert: str = ""  # PEM body — used to verify the assertion signature
    # Attribute names in the assertion to read identity + groups from.
    attr_username: str = "username"
    attr_email: str = "email"
    attr_display_name: str = "displayName"
    attr_groups: str = "groups"
    role_mappings: list[RoleMappingEntry] = field(default_factory=list)
    default_role: str = "viewer"


@dataclass
class LDAPConfig:
    enabled: bool = False
    host: str = ""
    port: int = 389
    use_ssl: bool = False  # ldaps://
    starttls: bool = False
    bind_dn: str = ""  # service account for the user search
    bind_password: str = ""
    base_dn: str = ""
    user_filter: str = "(mail={username})"  # {username} ← submitted login
    email_attr: str = "mail"
    display_name_attr: str = "displayName"
    group_base_dn: str = ""
    group_filter: str = "(member={user_dn})"  # {user_dn} ← found user's DN
    role_mappings: list[RoleMappingEntry] = field(default_factory=list)
    default_role: str = "viewer"
