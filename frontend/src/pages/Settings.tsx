// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

import { useEffect, useState } from 'react'
import { settingsApi, usersApi } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import type { User } from '@/lib/types'
import CertificatesTab from '@/components/settings/CertificatesTab'
import NotificationsTab from '@/components/settings/NotificationsTab'
import AccessTokensTab from '@/components/settings/AccessTokensTab'
import AuditTab from '@/components/settings/AuditTab'
import AiTab from '@/components/settings/AiTab'
import { ChangePasswordModal } from '@/components/ChangePassword'
import Modal from '@/components/ui/Modal'
import { btnPrimary, btnSecondary, inputCls } from '@/lib/ui'

// ─── Styles ───────────────────────────────────────────────────────────────────

const labelCls = 'block text-xs font-medium text-muted-foreground mb-1'

// ─── Shared components ────────────────────────────────────────────────────────

function Toggle({
  checked,
  onChange,
}: {
  checked: boolean
  onChange: (v: boolean) => void
}) {
  return (
    <button
      type="button"
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-5 w-9 flex-shrink-0 rounded-full border-2 border-transparent transition-colors focus:outline-none ${
        checked ? 'bg-primary' : 'bg-secondary'
      }`}
    >
      <span
        className={`inline-block h-4 w-4 rounded-full bg-background border border-border shadow-sm transition-transform ${
          checked ? 'translate-x-4' : 'translate-x-0'
        }`}
      />
    </button>
  )
}

function Field({
  label,
  name,
  value,
  onChange,
  placeholder,
  type = 'text',
  hint,
  maxLength,
}: {
  label: string
  name: string
  value: string
  onChange: (v: string) => void
  placeholder?: string
  type?: string
  hint?: string
  maxLength?: number
}) {
  return (
    <div>
      <label htmlFor={name} className={labelCls}>{label}</label>
      {type === 'textarea' ? (
        <textarea
          id={name}
          className={`${inputCls} font-mono text-xs leading-relaxed resize-y min-h-[80px]`}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          rows={4}
        />
      ) : (
        <input
          id={name}
          type={type}
          className={type === 'password' ? `${inputCls} font-mono` : inputCls}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          maxLength={maxLength}
          autoComplete={type === 'password' ? 'new-password' : undefined}
        />
      )}
      {hint && <p className="text-xs text-muted-foreground/60 mt-1">{hint}</p>}
    </div>
  )
}

function RoleSelect({
  value,
  onChange,
  label = 'Default role (users with no group match)',
}: {
  value: string
  onChange: (v: string) => void
  label?: string
}) {
  return (
    <div>
      <label className={labelCls}>{label}</label>
      <select
        className="w-full bg-background border border-border rounded-lg px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        <option value="viewer">Viewer</option>
        <option value="editor">Editor</option>
        <option value="admin">Admin</option>
      </select>
    </div>
  )
}

interface RoleMappingRow { group: string; group_id: string; role: string }

function RoleMappingsEditor({
  mappings,
  onChange,
  groupLabel = 'IdP group',
  groupPlaceholder = 'platform-admins',
  useGroupId = false,
}: {
  mappings: RoleMappingRow[]
  onChange: (m: RoleMappingRow[]) => void
  groupLabel?: string
  groupPlaceholder?: string
  useGroupId?: boolean
}) {
  const update = (i: number, patch: Partial<RoleMappingRow>) =>
    onChange(mappings.map((m, idx) => (idx === i ? { ...m, ...patch } : m)))
  const add = () =>
    onChange([...mappings, { group: '', group_id: '', role: 'viewer' }])
  const remove = (i: number) => onChange(mappings.filter((_, idx) => idx !== i))

  return (
    <div>
      <label className={labelCls}>Group → role mappings</label>
      <p className="text-[11px] text-muted-foreground mb-2">
        First matching group wins. Users with no matching group get the default role below.
      </p>
      <div className="space-y-2">
        {mappings.map((m, i) => (
          <div key={i} className="flex items-center gap-2">
            <input
              className="flex-1 bg-background border border-border rounded-lg px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
              value={useGroupId ? (m.group_id ?? '') : m.group}
              onChange={(e) => update(i, useGroupId ? { group_id: e.target.value } : { group: e.target.value })}
              placeholder={groupPlaceholder}
              aria-label={groupLabel}
            />
            <span className="text-muted-foreground text-xs">→</span>
            <select
              className="w-28 bg-background border border-border rounded-lg px-2 py-2 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
              value={m.role}
              onChange={(e) => update(i, { role: e.target.value })}
            >
              <option value="viewer">Viewer</option>
              <option value="editor">Editor</option>
              <option value="admin">Admin</option>
            </select>
            <button
              type="button"
              onClick={() => remove(i)}
              className="text-muted-foreground hover:text-destructive text-sm px-2 py-1 rounded transition-colors"
              aria-label="Remove mapping"
            >
              ✕
            </button>
          </div>
        ))}
      </div>
      <button
        type="button"
        onClick={add}
        className="mt-2 text-xs text-primary hover:text-primary/80 transition-colors"
      >
        + Add mapping
      </button>
    </div>
  )
}

function SaveRow({
  onSave,
  saving,
  saved,
  error,
}: {
  onSave: () => void
  saving: boolean
  saved: boolean
  error: string | null
}) {
  return (
    <div className="flex items-center gap-3 pt-2">
      <button onClick={onSave} disabled={saving} className={btnPrimary}>
        {saving ? 'Saving…' : 'Save'}
      </button>
      {saved && <span className="text-xs text-emerald-400">✓ Saved</span>}
      {error && <span className="text-xs text-destructive">{error}</span>}
    </div>
  )
}

// ─── Provider card ────────────────────────────────────────────────────────────

function ProviderCard({
  title,
  badge,
  description,
  enabled,
  onToggleEnabled,
  saving,
  saved,
  error,
  onSave,
  children,
}: {
  title: string
  badge: string
  description: string
  enabled: boolean
  onToggleEnabled: (v: boolean) => void
  saving: boolean
  saved: boolean
  error: string | null
  onSave: () => void
  children: React.ReactNode
}) {
  const [open, setOpen] = useState(false)

  return (
    <div className={`border rounded-xl overflow-hidden transition-colors ${enabled ? 'border-primary/40 bg-primary/3' : 'border-border bg-card'}`}>
      <div className="flex items-center gap-4 px-5 py-4">
        <Toggle checked={enabled} onChange={onToggleEnabled} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-foreground">{title}</span>
            <span className="text-xs text-muted-foreground/60 bg-secondary px-2 py-0.5 rounded-full">{badge}</span>
            {enabled && (
              <span className="text-xs text-emerald-400 bg-emerald-400/10 px-2 py-0.5 rounded-full">Enabled</span>
            )}
          </div>
          <p className="text-xs text-muted-foreground mt-0.5">{description}</p>
        </div>
        <button
          onClick={() => setOpen((o) => !o)}
          className="flex-shrink-0 text-muted-foreground hover:text-foreground transition-colors flex items-center gap-1.5 text-xs"
        >
          Configure
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className={`h-3.5 w-3.5 transition-transform ${open ? 'rotate-180' : ''}`}>
            <path d="M6 9l6 6 6-6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      </div>
      {open && (
        <div className="border-t border-border px-5 py-4 bg-background/40 space-y-4">
          {children}
          <SaveRow onSave={onSave} saving={saving} saved={saved} error={error} />
        </div>
      )}
    </div>
  )
}

// ─── SSO form types ───────────────────────────────────────────────────────────

interface AzureForm { enabled: boolean; tenant_id: string; client_id: string; client_secret: string; redirect_uri: string; role_mappings: RoleMappingForm[]; default_role: string }
interface RoleMappingForm { group: string; group_id: string; role: string }
interface OidcForm  { enabled: boolean; display_name: string; issuer: string; client_id: string; client_secret: string; redirect_uri: string; scopes: string[]; email_claim: string; username_claim: string; groups_claim: string; role_mappings: RoleMappingForm[]; default_role: string }
interface SamlForm  { enabled: boolean; display_name: string; sp_entity_id: string; idp_metadata_url: string; idp_entity_id: string; idp_sso_url: string; idp_x509_cert: string; attr_username: string; attr_email: string; attr_display_name: string; attr_groups: string; role_mappings: RoleMappingForm[]; default_role: string }
interface LdapForm  { enabled: boolean; url: string; starttls: boolean; bind_dn: string; bind_password: string; base_dn: string; user_filter: string; email_attr: string; display_name_attr: string; group_base_dn: string; group_filter: string; role_mappings: RoleMappingForm[]; default_role: string }

const defaultAzure: AzureForm = { enabled: false, tenant_id: '', client_id: '', client_secret: '', redirect_uri: '', role_mappings: [], default_role: 'viewer' }
const defaultOidc: OidcForm   = { enabled: false, display_name: 'SSO', issuer: '', client_id: '', client_secret: '', redirect_uri: '', scopes: ['openid', 'profile', 'email'], email_claim: 'email', username_claim: 'preferred_username', groups_claim: 'groups', role_mappings: [], default_role: 'viewer' }
const defaultSaml: SamlForm   = { enabled: false, display_name: 'SAML SSO', sp_entity_id: '', idp_metadata_url: '', idp_entity_id: '', idp_sso_url: '', idp_x509_cert: '', attr_username: 'username', attr_email: 'email', attr_display_name: 'displayName', attr_groups: 'groups', role_mappings: [], default_role: 'viewer' }
const defaultLdap: LdapForm   = { enabled: false, url: '', starttls: false, bind_dn: '', bind_password: '', base_dn: '', user_filter: '(mail={username})', email_attr: 'mail', display_name_attr: 'displayName', group_base_dn: '', group_filter: '(member={user_dn})', role_mappings: [], default_role: 'viewer' }

// ─── Tabs ─────────────────────────────────────────────────────────────────────

type Tab = 'general' | 'authentication' | 'users' | 'tls' | 'certificates' | 'notifications' | 'ai' | 'tokens' | 'audit'

// ─── General tab ─────────────────────────────────────────────────────────────

function GeneralTab() {
  const [appName, setAppName] = useState('VortexFlow')
  const [sessionTimeout, setSessionTimeout] = useState('60')
  const [lockoutAttempts, setLockoutAttempts] = useState('5')
  const [lockoutDuration, setLockoutDuration] = useState('900')
  const [desiredVector, setDesiredVector] = useState('')
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    settingsApi.getGeneral().then((r) => {
      const d = r.data
      if (d.app_name)          setAppName(String(d.app_name))
      if (d.session_timeout)   setSessionTimeout(String(d.session_timeout))
      if (d.lockout_attempts)  setLockoutAttempts(String(d.lockout_attempts))
      if (d.lockout_duration)  setLockoutDuration(String(d.lockout_duration))
      if (d.desired_vector_version != null) setDesiredVector(String(d.desired_vector_version))
    }).catch(() => {})
  }, [])

  const save = async () => {
    setSaving(true); setError(null)
    try {
      await settingsApi.putGeneral({
        app_name: appName,
        session_timeout: parseInt(sessionTimeout) || 60,
        lockout_attempts: parseInt(lockoutAttempts) || 5,
        lockout_duration: parseInt(lockoutDuration) || 900,
        desired_vector_version: desiredVector.trim(),
      })
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    } catch { setError('Save failed') }
    finally { setSaving(false) }
  }

  return (
    <div className="space-y-5 max-w-lg">
      <div>
        <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">Application</h3>
        <div className="space-y-3">
          <Field label="Application name" name="app_name" value={appName} onChange={setAppName}
            maxLength={40} hint="Shown in the sidebar, browser title, and login page (max 40 characters)." />
          <Field label="Session timeout (minutes)" name="session_timeout" value={sessionTimeout} onChange={setSessionTimeout}
            placeholder="60" hint="How long before an idle session is signed out." />
        </div>
      </div>
      <div>
        <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">Brute-force protection</h3>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Max login attempts" name="lockout_attempts" value={lockoutAttempts} onChange={setLockoutAttempts} placeholder="5" />
          <Field label="Lockout duration (seconds)" name="lockout_duration" value={lockoutDuration} onChange={setLockoutDuration} placeholder="900" />
        </div>
      </div>
      <div>
        <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">Fleet</h3>
        <Field label="Desired Vector version" name="desired_vector_version" value={desiredVector} onChange={setDesiredVector}
          placeholder="e.g. 0.41.1 — blank to leave unmanaged"
          hint="Agents reconcile their host to this version (when VECTOR_INSTALL_CMD is set) before applying config; drift shows on the home Attention panel." />
      </div>
      <SaveRow onSave={() => { void save() }} saving={saving} saved={saved} error={error} />
    </div>
  )
}

// ─── Authentication tab ───────────────────────────────────────────────────────

function AuthenticationTab() {
  const [azure, setAzure] = useState<AzureForm>(defaultAzure)
  const [oidc, setOidc]   = useState<OidcForm>(defaultOidc)
  const [saml, setSaml]   = useState<SamlForm>(defaultSaml)
  const [ldap, setLdap]   = useState<LdapForm>(defaultLdap)
  const [loadError, setLoadError] = useState<string | null>(null)

  type P = 'azure' | 'oidc' | 'saml' | 'ldap'
  const [saving, setSaving] = useState<Record<P, boolean>>({ azure: false, oidc: false, saml: false, ldap: false })
  const [saved,  setSaved]  = useState<Record<P, boolean>>({ azure: false, oidc: false, saml: false, ldap: false })
  const [errors, setErrors] = useState<Record<P, string | null>>({ azure: null, oidc: null, saml: null, ldap: null })

  useEffect(() => {
    Promise.all([settingsApi.getAzure(), settingsApi.getOidc(), settingsApi.getSaml(), settingsApi.getLdap()])
      .then(([a, o, s, l]) => {
        setAzure({ ...defaultAzure, ...a.data })
        setOidc({ ...defaultOidc, ...o.data })
        setSaml({ ...defaultSaml, ...s.data })
        setLdap({ ...defaultLdap, ...l.data })
      })
      .catch(() => setLoadError('Failed to load SSO settings'))
  }, [])

  const markSaved = (key: P) => {
    setSaved((p) => ({ ...p, [key]: true }))
    setTimeout(() => setSaved((p) => ({ ...p, [key]: false })), 3000)
  }

  const save = async (key: P, data: object, apiFn: (d: object) => Promise<unknown>) => {
    setSaving((p) => ({ ...p, [key]: true }))
    setErrors((p) => ({ ...p, [key]: null }))
    try { await apiFn(data); markSaved(key) }
    catch { setErrors((p) => ({ ...p, [key]: 'Save failed' })) }
    finally { setSaving((p) => ({ ...p, [key]: false })) }
  }

  return (
    <div className="space-y-3">
      <p className="text-xs text-muted-foreground mb-4">
        Changes take effect on next restart. Multiple providers can be enabled simultaneously.
      </p>
      {loadError && <p className="text-xs text-destructive">{loadError}</p>}

      <ProviderCard title="Azure Entra ID" badge="OIDC"
        description="Sign in with Microsoft — Azure AD, Entra ID. Supports group-based role mapping."
        enabled={azure.enabled} onToggleEnabled={(v) => setAzure((p) => ({ ...p, enabled: v }))}
        saving={saving.azure} saved={saved.azure} error={errors.azure}
        onSave={() => { void save('azure', azure, settingsApi.putAzure) }}>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Tenant ID" name="az_tenant" value={azure.tenant_id} onChange={(v) => setAzure((p) => ({ ...p, tenant_id: v }))} placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" />
          <Field label="Client ID" name="az_client" value={azure.client_id} onChange={(v) => setAzure((p) => ({ ...p, client_id: v }))} placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" />
        </div>
        <Field label="Client Secret" name="az_secret" type="password" value={azure.client_secret} onChange={(v) => setAzure((p) => ({ ...p, client_secret: v }))} placeholder="••••••••" />
        <Field label="Redirect URI" name="az_redirect" value={azure.redirect_uri} onChange={(v) => setAzure((p) => ({ ...p, redirect_uri: v }))} placeholder="https://vortexflow.example.com/api/v1/auth/azure/callback" />
        <RoleMappingsEditor
          mappings={azure.role_mappings}
          onChange={(m) => setAzure((p) => ({ ...p, role_mappings: m }))}
          useGroupId
          groupLabel="Group object ID"
          groupPlaceholder="00000000-0000-0000-0000-000000000000"
        />
        <p className="text-[11px] text-muted-foreground -mt-1">
          Azure emits group <em>object IDs</em>. Set <code>groupMembershipClaims</code> on the app registration so the <code>groups</code> claim is present.
        </p>
        <RoleSelect label="Default role (no group match)" value={azure.default_role} onChange={(v) => setAzure((p) => ({ ...p, default_role: v }))} />
      </ProviderCard>

      <ProviderCard title="Generic OIDC" badge="OIDC"
        description="Any OIDC-compliant provider — Google Workspace, Okta, Auth0, Keycloak, Dex."
        enabled={oidc.enabled} onToggleEnabled={(v) => setOidc((p) => ({ ...p, enabled: v }))}
        saving={saving.oidc} saved={saved.oidc} error={errors.oidc}
        onSave={() => { void save('oidc', oidc, settingsApi.putOidc) }}>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Display name" name="oidc_name" value={oidc.display_name} onChange={(v) => setOidc((p) => ({ ...p, display_name: v }))} placeholder="Sign in with Okta" hint="Shown on login button" />
          <Field label="Issuer URL" name="oidc_issuer" value={oidc.issuer} onChange={(v) => setOidc((p) => ({ ...p, issuer: v }))} placeholder="https://accounts.google.com" />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Client ID" name="oidc_client" value={oidc.client_id} onChange={(v) => setOidc((p) => ({ ...p, client_id: v }))} placeholder="client_id" />
          <Field label="Client Secret" name="oidc_secret" type="password" value={oidc.client_secret} onChange={(v) => setOidc((p) => ({ ...p, client_secret: v }))} placeholder="••••••••" />
        </div>
        <Field label="Redirect URI" name="oidc_redirect" value={oidc.redirect_uri} onChange={(v) => setOidc((p) => ({ ...p, redirect_uri: v }))} placeholder="https://vortexflow.example.com/api/v1/auth/oidc/callback" />
        <Field label="Scopes" name="oidc_scopes" value={oidc.scopes.join(' ')} onChange={(v) => setOidc((p) => ({ ...p, scopes: v.split(/\s+/).filter(Boolean) }))} placeholder="openid profile email groups" hint="Space-separated. 'openid' is always included." />
        <div className="grid grid-cols-3 gap-3">
          <Field label="Email claim" name="oidc_email_claim" value={oidc.email_claim} onChange={(v) => setOidc((p) => ({ ...p, email_claim: v }))} placeholder="email" />
          <Field label="Username claim" name="oidc_username_claim" value={oidc.username_claim} onChange={(v) => setOidc((p) => ({ ...p, username_claim: v }))} placeholder="preferred_username" />
          <Field label="Groups claim" name="oidc_groups_claim" value={oidc.groups_claim} onChange={(v) => setOidc((p) => ({ ...p, groups_claim: v }))} placeholder="groups" />
        </div>
        <RoleMappingsEditor
          mappings={oidc.role_mappings}
          onChange={(m) => setOidc((p) => ({ ...p, role_mappings: m }))}
        />
        <RoleSelect label="Default role (no group match)" value={oidc.default_role} onChange={(v) => setOidc((p) => ({ ...p, default_role: v }))} />
      </ProviderCard>

      <ProviderCard title="SAML 2.0" badge="SAML"
        description="Enterprise IdPs — ADFS, Ping Identity, Shibboleth, Okta SAML, any SAML 2.0 provider."
        enabled={saml.enabled} onToggleEnabled={(v) => setSaml((p) => ({ ...p, enabled: v }))}
        saving={saving.saml} saved={saved.saml} error={errors.saml}
        onSave={() => { void save('saml', saml, settingsApi.putSaml) }}>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Display name" name="saml_name" value={saml.display_name} onChange={(v) => setSaml((p) => ({ ...p, display_name: v }))} placeholder="SAML SSO" />
          <Field label="SP Entity ID" name="saml_sp" value={saml.sp_entity_id} onChange={(v) => setSaml((p) => ({ ...p, sp_entity_id: v }))} placeholder="https://vortexflow.example.com" hint="Your SP entity ID" />
        </div>
        <Field label="IdP Metadata URL" name="saml_meta" value={saml.idp_metadata_url} onChange={(v) => setSaml((p) => ({ ...p, idp_metadata_url: v }))} placeholder="https://idp.example.com/saml2/metadata" hint="Fetched automatically — overrides manual fields below" />
        <div className="grid grid-cols-2 gap-3">
          <Field label="IdP Entity ID" name="saml_idp_entity" value={saml.idp_entity_id} onChange={(v) => setSaml((p) => ({ ...p, idp_entity_id: v }))} placeholder="https://idp.example.com" />
          <Field label="IdP SSO URL" name="saml_sso" value={saml.idp_sso_url} onChange={(v) => setSaml((p) => ({ ...p, idp_sso_url: v }))} placeholder="https://idp.example.com/sso" />
        </div>
        <Field label="IdP X.509 Certificate" name="saml_cert" type="textarea" value={saml.idp_x509_cert} onChange={(v) => setSaml((p) => ({ ...p, idp_x509_cert: v }))} placeholder="MIICxxx..." hint="PEM body without -----BEGIN CERTIFICATE----- headers. Verifies the signed assertion." />
        <div className="grid grid-cols-2 gap-3">
          <Field label="Email attribute" name="saml_attr_email" value={saml.attr_email} onChange={(v) => setSaml((p) => ({ ...p, attr_email: v }))} placeholder="email" />
          <Field label="Groups attribute" name="saml_attr_groups" value={saml.attr_groups} onChange={(v) => setSaml((p) => ({ ...p, attr_groups: v }))} placeholder="groups" />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Username attribute" name="saml_attr_user" value={saml.attr_username} onChange={(v) => setSaml((p) => ({ ...p, attr_username: v }))} placeholder="username" />
          <Field label="Display-name attribute" name="saml_attr_dn" value={saml.attr_display_name} onChange={(v) => setSaml((p) => ({ ...p, attr_display_name: v }))} placeholder="displayName" />
        </div>
        <RoleMappingsEditor
          mappings={saml.role_mappings}
          onChange={(m) => setSaml((p) => ({ ...p, role_mappings: m }))}
          groupLabel="Group attribute value"
          groupPlaceholder="platform-admins"
        />
        <p className="text-[11px] text-muted-foreground -mt-1">
          SP metadata for your IdP is served at <code>/api/v1/auth/saml/metadata</code> (requires <code>public_url</code> set).
        </p>
        <RoleSelect label="Default role (no group match)" value={saml.default_role} onChange={(v) => setSaml((p) => ({ ...p, default_role: v }))} />
      </ProviderCard>

      <ProviderCard title="LDAP / Active Directory" badge="LDAP"
        description="Bind-based authentication against an LDAP directory or Microsoft Active Directory."
        enabled={ldap.enabled} onToggleEnabled={(v) => setLdap((p) => ({ ...p, enabled: v }))}
        saving={saving.ldap} saved={saved.ldap} error={errors.ldap}
        onSave={() => { void save('ldap', ldap, settingsApi.putLdap) }}>
        <Field label="LDAP URL" name="ldap_url" value={ldap.url} onChange={(v) => setLdap((p) => ({ ...p, url: v }))} placeholder="ldaps://ldap.example.com:636" />
        <div className="grid grid-cols-2 gap-3">
          <Field label="Bind DN" name="ldap_dn" value={ldap.bind_dn} onChange={(v) => setLdap((p) => ({ ...p, bind_dn: v }))} placeholder="CN=svc-vortex,OU=ServiceAccounts,DC=example,DC=com" />
          <Field label="Bind Password" name="ldap_pass" type="password" value={ldap.bind_password} onChange={(v) => setLdap((p) => ({ ...p, bind_password: v }))} placeholder="••••••••" />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <Field label="User Base DN" name="ldap_base" value={ldap.base_dn} onChange={(v) => setLdap((p) => ({ ...p, base_dn: v }))} placeholder="OU=Users,DC=example,DC=com" />
          <Field label="Group Base DN" name="ldap_group" value={ldap.group_base_dn} onChange={(v) => setLdap((p) => ({ ...p, group_base_dn: v }))} placeholder="OU=Groups,DC=example,DC=com" />
        </div>
        <Field label="User filter" name="ldap_filter" value={ldap.user_filter} onChange={(v) => setLdap((p) => ({ ...p, user_filter: v }))} placeholder="(mail={username})" hint="{username} is replaced with the value the user typed at login" />
        <div className="grid grid-cols-2 gap-3">
          <Field label="Email attribute" name="ldap_email_attr" value={ldap.email_attr} onChange={(v) => setLdap((p) => ({ ...p, email_attr: v }))} placeholder="mail" />
          <Field label="Display-name attribute" name="ldap_dn_attr" value={ldap.display_name_attr} onChange={(v) => setLdap((p) => ({ ...p, display_name_attr: v }))} placeholder="displayName" />
        </div>
        <Field label="Group filter" name="ldap_group_filter" value={ldap.group_filter} onChange={(v) => setLdap((p) => ({ ...p, group_filter: v }))} placeholder="(member={user_dn})" hint="{user_dn} is replaced with the authenticated user's DN" />
        <label className="flex items-center gap-2 text-xs text-muted-foreground">
          <input type="checkbox" checked={ldap.starttls} onChange={(e) => setLdap((p) => ({ ...p, starttls: e.target.checked }))} className="accent-primary" />
          Use StartTLS (upgrade a plain ldap:// connection to TLS)
        </label>
        <RoleMappingsEditor
          mappings={ldap.role_mappings}
          onChange={(m) => setLdap((p) => ({ ...p, role_mappings: m }))}
          groupLabel="Group DN"
          groupPlaceholder="CN=Platform Admins,OU=Groups,DC=example,DC=com"
        />
        <RoleSelect label="Default role (no group match)" value={ldap.default_role} onChange={(v) => setLdap((p) => ({ ...p, default_role: v }))} />
      </ProviderCard>
    </div>
  )
}

// ─── Users tab ────────────────────────────────────────────────────────────────

const ROLES: User['role'][] = ['admin', 'editor', 'viewer']
const roleColor = (r: string) =>
  r === 'admin' ? 'text-primary bg-primary/10' : r === 'editor' ? 'text-amber-400 bg-amber-400/10' : 'text-muted-foreground bg-secondary'

function UsersTab({ currentUserId }: { currentUserId: string }) {
  const [users, setUsers] = useState<User[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [showInvite, setShowInvite] = useState(false)
  const [invite, setInvite] = useState({ email: '', name: '', role: 'viewer' as User['role'], password: '' })
  const [inviting, setInviting] = useState(false)
  const [inviteError, setInviteError] = useState<string | null>(null)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editRole, setEditRole] = useState<User['role']>('viewer')
  const [updating, setUpdating] = useState(false)
  const [resetUser, setResetUser] = useState<User | null>(null)
  const [showChangePw, setShowChangePw] = useState(false)

  const load = () => {
    setLoading(true)
    usersApi.list().then((r) => {
      setUsers(r.data.items ?? r.data)
      setLoadError(null)
    }).catch(() => setLoadError('Failed to load users'))
    .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [])

  const doInvite = async () => {
    setInviting(true); setInviteError(null)
    try {
      await usersApi.create({ email: invite.email, name: invite.name, role: invite.role, password: invite.password || undefined })
      setInvite({ email: '', name: '', role: 'viewer', password: '' })
      setShowInvite(false)
      load()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setInviteError(detail ?? 'Failed to create user')
    } finally { setInviting(false) }
  }

  const saveRole = async (userId: string) => {
    setUpdating(true)
    try {
      await usersApi.update(userId, { role: editRole })
      setUsers((prev) => prev.map((u) => u.id === userId ? { ...u, role: editRole } : u))
      setEditingId(null)
    } catch { /* swallow */ }
    finally { setUpdating(false) }
  }

  const toggleActive = async (u: User) => {
    try {
      await usersApi.update(u.id, { is_active: !u.is_active })
      setUsers((prev) => prev.map((x) => x.id === u.id ? { ...x, is_active: !u.is_active } : x))
    } catch { /* swallow */ }
  }

  return (
    <div className="space-y-4 max-w-2xl">
      <div className="flex items-center justify-between">
        <p className="text-xs text-muted-foreground">{users.length} user{users.length !== 1 ? 's' : ''}</p>
        <button onClick={() => setShowInvite((o) => !o)} className={btnPrimary}>
          {showInvite ? 'Cancel' : '+ Invite user'}
        </button>
      </div>

      {showInvite && (
        <div className="border border-border rounded-xl p-4 bg-card space-y-3">
          <h3 className="text-sm font-medium text-foreground">Invite user</h3>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={labelCls}>Email</label>
              <input className={inputCls} type="email" value={invite.email} onChange={(e) => setInvite((p) => ({ ...p, email: e.target.value }))} placeholder="user@example.com" />
            </div>
            <div>
              <label className={labelCls}>Name</label>
              <input className={inputCls} value={invite.name} onChange={(e) => setInvite((p) => ({ ...p, name: e.target.value }))} placeholder="Jane Smith" />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={labelCls}>Password</label>
              <input className={`${inputCls} font-mono`} type="password" value={invite.password} onChange={(e) => setInvite((p) => ({ ...p, password: e.target.value }))} placeholder="••••••••" autoComplete="new-password" />
            </div>
            <div>
              <label className={labelCls}>Role</label>
              <select className="w-full bg-background border border-border rounded-lg px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary" value={invite.role} onChange={(e) => setInvite((p) => ({ ...p, role: e.target.value as User['role'] }))}>
                {ROLES.map((r) => <option key={r} value={r}>{r.charAt(0).toUpperCase() + r.slice(1)}</option>)}
              </select>
            </div>
          </div>
          {inviteError && <p className="text-xs text-destructive">{inviteError}</p>}
          <div className="flex gap-2">
            <button onClick={() => { void doInvite() }} disabled={inviting || !invite.email || !invite.name} className={btnPrimary}>
              {inviting ? 'Creating…' : 'Create user'}
            </button>
            <button onClick={() => setShowInvite(false)} className={btnSecondary}>Cancel</button>
          </div>
        </div>
      )}

      {loadError && <p className="text-xs text-destructive">{loadError}</p>}

      {loading ? (
        <div className="space-y-2">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="h-14 bg-card border border-border rounded-xl animate-pulse" />
          ))}
        </div>
      ) : (
        <div className="border border-border rounded-xl overflow-hidden">
          {users.map((u, idx) => (
            <div
              key={u.id}
              className={`flex items-center gap-4 px-4 py-3 ${idx < users.length - 1 ? 'border-b border-border' : ''} ${!u.is_active ? 'opacity-50' : ''}`}
            >
              <div className="h-7 w-7 rounded-full bg-primary/15 text-primary text-xs font-semibold flex items-center justify-center flex-shrink-0">
                {u.name.charAt(0).toUpperCase()}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-foreground truncate">{u.name}</span>
                  {!u.is_active && <span className="text-xs text-muted-foreground/60 bg-secondary px-1.5 py-0.5 rounded">Inactive</span>}
                  <span className="text-xs text-muted-foreground/60 bg-secondary px-1.5 py-0.5 rounded">{u.auth_method}</span>
                </div>
                <p className="text-xs text-muted-foreground truncate">{u.email}</p>
              </div>

              {editingId === u.id ? (
                <div className="flex items-center gap-2 flex-shrink-0">
                  <select
                    className="bg-background border border-border rounded-lg px-2 py-1 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
                    value={editRole}
                    onChange={(e) => setEditRole(e.target.value as User['role'])}
                  >
                    {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                  </select>
                  <button onClick={() => { void saveRole(u.id) }} disabled={updating} className="text-xs text-primary hover:text-primary/80 font-medium">
                    {updating ? '…' : 'Save'}
                  </button>
                  <button onClick={() => setEditingId(null)} className="text-xs text-muted-foreground hover:text-foreground">Cancel</button>
                </div>
              ) : (
                <div className="flex items-center gap-2 flex-shrink-0">
                  <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${roleColor(u.role)}`}>{u.role}</span>
                  {u.id === currentUserId && u.auth_method === 'local' && (
                    <button
                      onClick={() => setShowChangePw(true)}
                      className="text-xs text-muted-foreground hover:text-foreground transition-colors"
                    >
                      Change password
                    </button>
                  )}
                  {u.id !== currentUserId && (
                    <>
                      <button
                        onClick={() => { setEditingId(u.id); setEditRole(u.role) }}
                        className="text-xs text-muted-foreground hover:text-foreground transition-colors"
                      >
                        Edit
                      </button>
                      <button
                        onClick={() => { void toggleActive(u) }}
                        className={`text-xs transition-colors ${u.is_active ? 'text-muted-foreground hover:text-amber-400' : 'text-muted-foreground hover:text-emerald-400'}`}
                      >
                        {u.is_active ? 'Deactivate' : 'Reactivate'}
                      </button>
                      {u.auth_method === 'local' && (
                        <button
                          onClick={() => setResetUser(u)}
                          className="text-xs text-muted-foreground hover:text-foreground transition-colors"
                        >
                          Reset password
                        </button>
                      )}
                    </>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {resetUser && (
        <ResetPasswordModal user={resetUser} onClose={() => setResetUser(null)} />
      )}
      {showChangePw && <ChangePasswordModal onClose={() => setShowChangePw(false)} />}
    </div>
  )
}

function ResetPasswordModal({ user, onClose }: { user: User; onClose: () => void }) {
  const [mode, setMode] = useState<'generate' | 'set'>('generate')
  const [pw, setPw] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  const submit = async () => {
    setBusy(true)
    setError(null)
    try {
      const r = await usersApi.resetPassword(user.id, mode === 'set' ? pw : undefined)
      if (r.data.generated && r.data.password) setResult(r.data.password)
      else onClose()
    } catch (err: unknown) {
      setError(
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
          'Reset failed',
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal title={`Reset password — ${user.name}`} onClose={onClose}>
      <div className="p-5 space-y-4">
        {result ? (
          <>
            <p className="text-sm text-muted-foreground">
              New password for <span className="text-foreground font-medium">{user.email}</span> —
              copy it now, it won't be shown again.
            </p>
            <div className="flex items-center gap-2">
              <code className="flex-1 bg-secondary rounded-lg px-3 py-2 text-sm font-mono text-foreground break-all">
                {result}
              </code>
              <button
                onClick={() => {
                  void navigator.clipboard.writeText(result)
                  setCopied(true)
                  setTimeout(() => setCopied(false), 1500)
                }}
                className={btnSecondary}
              >
                {copied ? 'Copied' : 'Copy'}
              </button>
            </div>
            <div className="flex justify-end">
              <button onClick={onClose} className={btnPrimary}>Done</button>
            </div>
          </>
        ) : (
          <>
            <div className="flex gap-2">
              <button
                onClick={() => setMode('generate')}
                className={`text-xs px-3 py-1.5 rounded-lg transition-colors ${mode === 'generate' ? 'bg-primary/10 text-primary' : 'text-muted-foreground hover:bg-secondary'}`}
              >
                Generate
              </button>
              <button
                onClick={() => setMode('set')}
                className={`text-xs px-3 py-1.5 rounded-lg transition-colors ${mode === 'set' ? 'bg-primary/10 text-primary' : 'text-muted-foreground hover:bg-secondary'}`}
              >
                Set manually
              </button>
            </div>
            {mode === 'set' && (
              <input
                type="text"
                className={inputCls}
                placeholder="New password (min 8 chars)"
                value={pw}
                onChange={(e) => setPw(e.target.value)}
              />
            )}
            {error && <p className="text-xs text-destructive">{error}</p>}
            <div className="flex justify-end gap-2">
              <button onClick={onClose} className={btnSecondary}>Cancel</button>
              <button
                onClick={() => void submit()}
                disabled={busy || (mode === 'set' && pw.length < 8)}
                className={btnPrimary}
              >
                {busy ? 'Resetting…' : 'Reset password'}
              </button>
            </div>
          </>
        )}
      </div>
    </Modal>
  )
}

// ─── TLS tab ──────────────────────────────────────────────────────────────────

interface CertOption { id: string; label: string; cn: string | null; expires_in_days: number | null; has_key: boolean; cert_type: string }

function TlsTab() {
  const [certId, setCertId] = useState<string>('')
  const [appliedCertPath, setAppliedCertPath] = useState('')
  const [appliedKeyPath, setAppliedKeyPath] = useState('')
  const [appliedCaPath, setAppliedCaPath] = useState('')
  const [certs, setCerts] = useState<CertOption[]>([])
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [applying, setApplying] = useState(false)
  const [applyMsg, setApplyMsg] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    settingsApi.getTls().then((r) => {
      const d = r.data
      if (d.cert_id)   setCertId(d.cert_id)
      if (d.cert_path) setAppliedCertPath(d.cert_path)
      if (d.key_path)  setAppliedKeyPath(d.key_path)
      if (d.ca_path)   setAppliedCaPath(d.ca_path)
    }).catch(() => {})
    // Load cert list (only server certs with a key are useful for TLS termination)
    import('@/lib/api').then(({ certsApi }) =>
      certsApi.list().then((r) => {
        setCerts((r.data as CertOption[]).filter((c) =>
          c.cert_type === 'server' || c.has_key
        ))
      }).catch(() => {})
    )
  }, [])

  const save = async () => {
    setSaving(true); setError(null)
    try {
      await settingsApi.putTls({ cert_id: certId || null })
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    } catch { setError('Save failed') }
    finally { setSaving(false) }
  }

  const apply = async () => {
    setApplying(true); setApplyMsg(null); setError(null)
    try {
      const r = await settingsApi.applyTls()
      const d = r.data
      setAppliedCertPath(d.cert_path)
      setAppliedKeyPath(d.key_path)
      setAppliedCaPath(d.ca_path ?? '')
      setApplyMsg(d.message)
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail ?? 'Apply failed')
    } finally { setApplying(false) }
  }

  const selected = certs.find((c) => c.id === certId)

  return (
    <div className="space-y-5 max-w-lg">
      <div className="p-3 bg-secondary/50 rounded-lg text-xs text-muted-foreground">
        TLS termination is handled by nginx. Select a certificate from the store — clicking
        "Apply to disk" writes the PEM files to <code className="font-mono">/etc/vortexflow/certs/</code>,
        then reload nginx to pick them up.
      </div>

      <div>
        <label className={labelCls}>Certificate</label>
        <select
          className="w-full bg-background border border-border rounded-lg px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
          value={certId}
          onChange={(e) => { setCertId(e.target.value); setSaved(false) }}
        >
          <option value="">— select a certificate —</option>
          {certs.map((c) => (
            <option key={c.id} value={c.id}>
              {c.label}{c.cn ? ` (${c.cn})` : ''}{c.expires_in_days !== null ? ` · ${c.expires_in_days}d` : ''}
            </option>
          ))}
        </select>
        {certs.length === 0 && (
          <p className="text-xs text-muted-foreground/60 mt-1">
            No server certificates uploaded yet. Add one in the Certificates tab.
          </p>
        )}
        {selected && !selected.has_key && (
          <p className="text-xs text-amber-400 mt-1">
            This cert has no private key — it cannot be used for TLS termination.
          </p>
        )}
      </div>

      <div className="flex items-center gap-2">
        <button
          onClick={() => { void save() }}
          disabled={saving}
          className={btnSecondary + ' disabled:opacity-50'}
        >
          {saving ? 'Saving…' : saved ? 'Saved ✓' : 'Save selection'}
        </button>
        <button
          onClick={() => { void apply() }}
          disabled={applying || !certId || (!!selected && !selected.has_key)}
          className={btnPrimary + ' disabled:opacity-50'}
        >
          {applying ? 'Applying…' : 'Apply to disk'}
        </button>
      </div>

      {applyMsg && <p className="text-xs text-emerald-400">{applyMsg}</p>}
      {error && <p className="text-xs text-destructive">{error}</p>}

      {(appliedCertPath || appliedKeyPath) && (
        <div className="rounded-lg border border-border bg-background/40 p-3 space-y-1.5 text-xs">
          <p className="text-muted-foreground font-medium mb-1">Applied paths</p>
          {appliedCertPath && (
            <div className="flex gap-2">
              <span className="text-muted-foreground w-8 flex-shrink-0">Cert</span>
              <span className="font-mono text-foreground/80">{appliedCertPath}</span>
            </div>
          )}
          {appliedKeyPath && (
            <div className="flex gap-2">
              <span className="text-muted-foreground w-8 flex-shrink-0">Key</span>
              <span className="font-mono text-foreground/80">{appliedKeyPath}</span>
            </div>
          )}
          {appliedCaPath && (
            <div className="flex gap-2">
              <span className="text-muted-foreground w-8 flex-shrink-0">CA</span>
              <span className="font-mono text-foreground/80">{appliedCaPath}</span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function Settings() {
  const { user } = useAuth()
  const [tab, setTab] = useState<Tab>('general')

  if (!user || user.role !== 'admin') {
    return (
      <div className="p-8 text-sm text-muted-foreground">
        Settings are only accessible to admins.
      </div>
    )
  }

  const tabs: { key: Tab; label: string }[] = [
    { key: 'general',        label: 'General' },
    { key: 'authentication', label: 'Authentication' },
    { key: 'users',          label: 'Users' },
    { key: 'tls',            label: 'TLS' },
    { key: 'certificates',   label: 'Certificates' },
    { key: 'notifications',  label: 'Notifications' },
    { key: 'ai',             label: 'AI Assistant' },
    { key: 'tokens',         label: 'Access Tokens' },
    { key: 'audit',          label: 'Audit' },
  ]

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex-shrink-0 border-b border-border bg-card px-6 py-4">
        <h1 className="text-base font-semibold text-foreground">Settings</h1>
        <p className="text-xs text-muted-foreground mt-0.5">
          System configuration. Most changes take effect on next restart.
        </p>
      </div>

      {/* Tab bar */}
      <div className="flex-shrink-0 border-b border-border bg-card px-6">
        <div className="flex gap-1">
          {tabs.map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`px-4 py-2.5 text-xs font-medium border-b-2 transition-colors -mb-px ${
                tab === t.key
                  ? 'border-primary text-primary'
                  : 'border-transparent text-muted-foreground hover:text-foreground'
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-y-auto p-6">
        {tab === 'general'        && <GeneralTab />}
        {tab === 'authentication' && <AuthenticationTab />}
        {tab === 'users'          && <UsersTab currentUserId={user.id} />}
        {tab === 'tls'            && <TlsTab />}
        {tab === 'certificates'   && <CertificatesTab />}
        {tab === 'notifications'  && <NotificationsTab />}
        {tab === 'ai'             && <AiTab />}
        {tab === 'tokens'         && <AccessTokensTab />}
        {tab === 'audit'          && <AuditTab />}
      </div>
    </div>
  )
}
