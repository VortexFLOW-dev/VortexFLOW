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

    # Public base URL of this VortexFlow server (e.g. https://vf.example.com).
    # Used to generate the agent install one-liner and the metrics endpoint.
    # Required behind a reverse proxy — request.base_url would otherwise be the
    # internal backend address, which agents can't reach.
    public_url: Optional[str] = None

    # Database
    database_url: str = (
        "postgresql+asyncpg://vortexflow:vortexflow@localhost:5432/vortexflow"
    )

    # Redis
    redis_url: str = "redis://localhost:6379/0"

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

    # Bootstrap admin
    bootstrap_admin_email: str = "admin@example.com"
    bootstrap_admin_password: str = "ChangeMe123!"
    bootstrap_admin_name: str = "Admin"

    # Demo mode (docker-compose.demo.yml only). Skips the forced bootstrap-admin
    # password rotation so the auto-registering demo agent — and a human poking
    # the UI with the documented demo creds — can use RBAC endpoints out of the
    # box. NEVER set this in production; the password-change gate is a real
    # security control there.
    demo_mode: bool = False

    # Brute-force protection
    max_login_attempts: int = 5
    lockout_duration_seconds: int = 900
    ip_block_threshold: int = 20
    ip_block_duration_seconds: int = 3600

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
