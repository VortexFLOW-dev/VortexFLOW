// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

import { useEffect, useState } from 'react'
import { notificationsApi, settingsApi } from '@/lib/api'
import type { ChannelInput, ChannelType, NotificationChannel } from '@/lib/types'
import { btnPrimary, btnSecondary, btnDanger, inputCls } from '@/lib/ui'

// ─── Shared bits ────────────────────────────────────────────────────────────

const labelCls = 'block text-xs font-medium text-muted-foreground mb-1'

const CHANNEL_TYPES: { value: ChannelType; label: string; hint: string }[] = [
  { value: 'webhook', label: 'Webhook', hint: 'POST JSON to any HTTP endpoint' },
  { value: 'slack', label: 'Slack', hint: 'Incoming webhook URL' },
  { value: 'teams', label: 'Microsoft Teams', hint: 'Incoming webhook URL' },
  { value: 'email', label: 'Email', hint: 'SMTP server' },
]

function Toggle({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
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

function LabeledInput({
  label, value, onChange, placeholder, type = 'text', hint,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  placeholder?: string
  type?: string
  hint?: string
}) {
  return (
    <div>
      <label className={labelCls}>{label}</label>
      <input
        type={type}
        className={type === 'password' ? `${inputCls} font-mono` : inputCls}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        autoComplete={type === 'password' ? 'new-password' : undefined}
      />
      {hint && <p className="text-xs text-muted-foreground/60 mt-1">{hint}</p>}
    </div>
  )
}

// ─── Editor form state ──────────────────────────────────────────────────────

interface FormState {
  type: ChannelType
  name: string
  enabled: boolean
  min_severity: 'warning' | 'critical'
  notify_on_resolve: boolean
  // webhook / slack / teams
  url: string
  headers: string // raw JSON text, webhook only
  // email
  host: string
  port: string
  use_tls: boolean
  from_addr: string
  to_addrs: string // comma-separated
  username: string
  password: string
}

const emptyForm: FormState = {
  type: 'webhook',
  name: '',
  enabled: true,
  min_severity: 'warning',
  notify_on_resolve: true,
  url: '',
  headers: '',
  host: '',
  port: '587',
  use_tls: true,
  from_addr: '',
  to_addrs: '',
  username: '',
  password: '',
}

function formFromChannel(c: NotificationChannel): FormState {
  const cfg = c.config as Record<string, unknown>
  return {
    ...emptyForm,
    type: c.type,
    name: c.name,
    enabled: c.enabled,
    min_severity: c.min_severity,
    notify_on_resolve: c.notify_on_resolve,
    host: String(cfg.host ?? ''),
    port: String(cfg.port ?? '587'),
    use_tls: cfg.use_tls !== false,
    from_addr: String(cfg.from_addr ?? ''),
    to_addrs: Array.isArray(cfg.to_addrs) ? (cfg.to_addrs as string[]).join(', ') : '',
    username: String(cfg.username ?? ''),
  }
}

/** Build the API payload from form state. Returns an error string if invalid. */
function buildPayload(f: FormState): { input: ChannelInput } | { error: string } {
  if (!f.name.trim()) return { error: 'Name is required' }

  let config: Record<string, unknown> = {}
  let secret: Record<string, unknown> = {}

  if (f.type === 'email') {
    if (!f.host.trim() || !f.from_addr.trim() || !f.to_addrs.trim())
      return { error: 'Email needs host, from address, and at least one recipient' }
    config = {
      host: f.host.trim(),
      port: parseInt(f.port) || 587,
      use_tls: f.use_tls,
      from_addr: f.from_addr.trim(),
      to_addrs: f.to_addrs.split(',').map((s) => s.trim()).filter(Boolean),
      username: f.username.trim() || undefined,
    }
    if (f.password) secret = { password: f.password }
  } else {
    // webhook / slack / teams — URL is the secret
    if (f.url.trim()) {
      secret = { url: f.url.trim() }
      if (f.type === 'webhook' && f.headers.trim()) {
        try {
          secret.headers = JSON.parse(f.headers)
        } catch {
          return { error: 'Headers must be valid JSON' }
        }
      }
    }
  }

  return {
    input: {
      type: f.type,
      name: f.name.trim(),
      enabled: f.enabled,
      config,
      secret,
      min_severity: f.min_severity,
      notify_on_resolve: f.notify_on_resolve,
    },
  }
}

// ─── Editor ─────────────────────────────────────────────────────────────────

function ChannelEditor({
  initial, existing, onSaved, onCancel,
}: {
  initial: FormState
  existing: NotificationChannel | null
  onSaved: () => void
  onCancel: () => void
}) {
  const [f, setF] = useState<FormState>(initial)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const set = <K extends keyof FormState>(k: K, v: FormState[K]) =>
    setF((p) => ({ ...p, [k]: v }))

  const save = async () => {
    const built = buildPayload(f)
    if ('error' in built) { setError(built.error); return }
    // On create, a destination is required; on edit, blank secret keeps the old one.
    if (!existing && Object.keys(built.input.secret).length === 0) {
      setError(f.type === 'email' ? 'SMTP password may be required' : 'Destination URL is required')
      if (f.type !== 'email') return
    }
    setSaving(true); setError(null)
    try {
      if (existing) {
        const { secret, ...rest } = built.input
        // Only send secret if the user typed a new one.
        const payload = Object.keys(secret).length ? built.input : rest
        await notificationsApi.update(existing.id, payload)
      } else {
        await notificationsApi.create(built.input)
      }
      onSaved()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail ?? 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  const isUrlType = f.type !== 'email'

  return (
    <div className="border border-primary/40 rounded-xl p-4 bg-primary/3 space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-foreground">
          {existing ? `Edit ${existing.name}` : 'New channel'}
        </h3>
        <button onClick={onCancel} className="text-xs text-muted-foreground hover:text-foreground">Cancel</button>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={labelCls}>Type</label>
          <select
            className="w-full bg-background border border-border rounded-lg px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary disabled:opacity-50"
            value={f.type}
            disabled={!!existing}
            onChange={(e) => set('type', e.target.value as ChannelType)}
          >
            {CHANNEL_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
          </select>
        </div>
        <LabeledInput label="Name" value={f.name} onChange={(v) => set('name', v)} placeholder="e.g. Ops Slack" />
      </div>

      {isUrlType && (
        <LabeledInput
          label={existing?.has_secret ? 'Destination URL (leave blank to keep current)' : 'Destination URL'}
          value={f.url}
          onChange={(v) => set('url', v)}
          placeholder="https://hooks.slack.com/services/…"
        />
      )}
      {f.type === 'webhook' && (
        <div>
          <label className={labelCls}>Custom headers (JSON, optional)</label>
          <textarea
            className={`${inputCls} font-mono text-xs resize-y min-h-[60px]`}
            value={f.headers}
            onChange={(e) => set('headers', e.target.value)}
            placeholder='{"Authorization": "Bearer …"}'
            rows={2}
          />
          <p className="text-xs text-muted-foreground/60 mt-1">Stored encrypted alongside the URL.</p>
        </div>
      )}

      {f.type === 'email' && (
        <div className="space-y-3">
          <div className="grid grid-cols-3 gap-3">
            <div className="col-span-2">
              <LabeledInput label="SMTP host" value={f.host} onChange={(v) => set('host', v)} placeholder="smtp.example.com" />
            </div>
            <LabeledInput label="Port" value={f.port} onChange={(v) => set('port', v)} placeholder="587" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <LabeledInput label="From address" value={f.from_addr} onChange={(v) => set('from_addr', v)} placeholder="alerts@example.com" />
            <LabeledInput label="Username (optional)" value={f.username} onChange={(v) => set('username', v)} placeholder="defaults to From" />
          </div>
          <LabeledInput label="Recipients (comma-separated)" value={f.to_addrs} onChange={(v) => set('to_addrs', v)} placeholder="oncall@example.com, sec@example.com" />
          <LabeledInput
            label={existing?.has_secret ? 'SMTP password (leave blank to keep current)' : 'SMTP password'}
            type="password" value={f.password} onChange={(v) => set('password', v)} placeholder="••••••••"
          />
          <label className="flex items-center gap-2 text-xs text-muted-foreground">
            <Toggle checked={f.use_tls} onChange={(v) => set('use_tls', v)} /> Use STARTTLS
          </label>
        </div>
      )}

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={labelCls}>Minimum severity</label>
          <select
            className="w-full bg-background border border-border rounded-lg px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
            value={f.min_severity}
            onChange={(e) => set('min_severity', e.target.value as 'warning' | 'critical')}
          >
            <option value="warning">Warning &amp; above</option>
            <option value="critical">Critical only</option>
          </select>
        </div>
        <div className="flex items-end gap-4 pb-1">
          <label className="flex items-center gap-2 text-xs text-muted-foreground">
            <Toggle checked={f.notify_on_resolve} onChange={(v) => set('notify_on_resolve', v)} /> Notify on recovery
          </label>
        </div>
      </div>

      {error && <p className="text-xs text-destructive">{error}</p>}
      <div className="flex gap-2">
        <button onClick={() => { void save() }} disabled={saving} className={btnPrimary}>
          {saving ? 'Saving…' : existing ? 'Save changes' : 'Create channel'}
        </button>
        <button onClick={onCancel} className={btnSecondary}>Cancel</button>
      </div>
    </div>
  )
}

// ─── Status dot ─────────────────────────────────────────────────────────────

function StatusDot({ c }: { c: NotificationChannel }) {
  let color = 'bg-muted-foreground/40'
  let title = 'No deliveries yet'
  if (c.last_error) { color = 'bg-destructive'; title = c.last_error }
  else if (c.last_success_at) { color = 'bg-emerald-400'; title = `Last delivered ${new Date(c.last_success_at).toLocaleString()}` }
  return <span className={`h-2 w-2 rounded-full flex-shrink-0 ${color}`} title={title} />
}

// ─── Tab ────────────────────────────────────────────────────────────────────

export default function NotificationsTab() {
  const [channels, setChannels] = useState<NotificationChannel[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [editing, setEditing] = useState<{ form: FormState; existing: NotificationChannel | null } | null>(null)
  const [testing, setTesting] = useState<string | null>(null)
  const [testResult, setTestResult] = useState<{ id: string; ok: boolean; msg: string } | null>(null)

  const [interval, setIntervalState] = useState('30')
  const [savingInterval, setSavingInterval] = useState(false)
  const [intervalSaved, setIntervalSaved] = useState(false)

  const load = () => {
    setLoading(true)
    notificationsApi.list()
      .then((r) => { setChannels(r.data); setLoadError(null) })
      .catch(() => setLoadError('Failed to load channels'))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    load()
    settingsApi.getNotifications().then((r) => {
      if (r.data?.tick_interval_secs) setIntervalState(String(r.data.tick_interval_secs))
    }).catch(() => {})
  }, [])

  const saveInterval = async () => {
    setSavingInterval(true)
    try {
      await settingsApi.putNotifications({ tick_interval_secs: parseInt(interval) || 30 })
      setIntervalSaved(true)
      setTimeout(() => setIntervalSaved(false), 3000)
    } catch { /* swallow */ }
    finally { setSavingInterval(false) }
  }

  const doTest = async (c: NotificationChannel) => {
    setTesting(c.id); setTestResult(null)
    try {
      await notificationsApi.test(c.id)
      setTestResult({ id: c.id, ok: true, msg: 'Test sent ✓' })
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setTestResult({ id: c.id, ok: false, msg: detail ?? 'Test failed' })
    } finally {
      setTesting(null)
      load() // refresh last_success / last_error
    }
  }

  const doDelete = async (c: NotificationChannel) => {
    if (!confirm(`Delete channel "${c.name}"?`)) return
    try { await notificationsApi.delete(c.id); load() } catch { /* swallow */ }
  }

  const toggleEnabled = async (c: NotificationChannel) => {
    try {
      await notificationsApi.update(c.id, { enabled: !c.enabled })
      setChannels((prev) => prev.map((x) => x.id === c.id ? { ...x, enabled: !c.enabled } : x))
    } catch { /* swallow */ }
  }

  return (
    <div className="space-y-5 max-w-2xl">
      <p className="text-xs text-muted-foreground">
        Deliver fleet events (agent offline, validation/reload failures, version drift, cert expiry)
        to external channels. Channels fire on the same events as the in-app notification center.
      </p>

      {/* Worker interval */}
      <div className="rounded-xl border border-border bg-card p-4 flex items-end gap-3 flex-wrap">
        <div className="flex-1 min-w-[200px]">
          <label className={labelCls}>Delivery check interval (seconds)</label>
          <input className={inputCls} value={interval} onChange={(e) => setIntervalState(e.target.value)} placeholder="30" />
          <p className="text-xs text-muted-foreground/60 mt-1">
            How often the background worker detects events and delivers pending notifications (min 5).
          </p>
        </div>
        <button onClick={() => { void saveInterval() }} disabled={savingInterval} className={btnSecondary}>
          {savingInterval ? 'Saving…' : intervalSaved ? 'Saved ✓' : 'Save'}
        </button>
      </div>

      {/* Channels */}
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Channels</h3>
        {!editing && (
          <button onClick={() => setEditing({ form: emptyForm, existing: null })} className={btnPrimary}>
            + Add channel
          </button>
        )}
      </div>

      {editing && (
        <ChannelEditor
          initial={editing.form}
          existing={editing.existing}
          onSaved={() => { setEditing(null); load() }}
          onCancel={() => setEditing(null)}
        />
      )}

      {loadError && <p className="text-xs text-destructive">{loadError}</p>}

      {loading ? (
        <div className="space-y-2">
          {[...Array(2)].map((_, i) => <div key={i} className="h-16 bg-card border border-border rounded-xl animate-pulse" />)}
        </div>
      ) : channels.length === 0 && !editing ? (
        <p className="text-xs text-muted-foreground/60 py-6 text-center border border-dashed border-border rounded-xl">
          No channels yet. Add one to start delivering alerts.
        </p>
      ) : (
        <div className="space-y-2">
          {channels.map((c) => (
            <div key={c.id} className={`border border-border rounded-xl p-4 bg-card ${!c.enabled ? 'opacity-60' : ''}`}>
              <div className="flex items-center gap-3">
                <StatusDot c={c} />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-foreground truncate">{c.name}</span>
                    <span className="text-xs text-muted-foreground/60 bg-secondary px-2 py-0.5 rounded-full capitalize">{c.type}</span>
                    <span className="text-xs text-muted-foreground/60">{c.min_severity === 'critical' ? 'critical only' : 'warning+'}</span>
                    {c.notify_on_resolve && <span className="text-xs text-muted-foreground/40">· recovery</span>}
                  </div>
                  {c.last_error && <p className="text-xs text-destructive truncate mt-0.5">{c.last_error}</p>}
                </div>
                <div className="flex items-center gap-3 flex-shrink-0">
                  <Toggle checked={c.enabled} onChange={() => { void toggleEnabled(c) }} />
                  <button onClick={() => { void doTest(c) }} disabled={testing === c.id} className="text-xs text-muted-foreground hover:text-foreground transition-colors">
                    {testing === c.id ? 'Testing…' : 'Test'}
                  </button>
                  <button onClick={() => setEditing({ form: formFromChannel(c), existing: c })} className="text-xs text-muted-foreground hover:text-foreground transition-colors">Edit</button>
                  <button onClick={() => { void doDelete(c) }} className={btnDanger + ' text-xs px-2 py-1'}>Delete</button>
                </div>
              </div>
              {testResult?.id === c.id && (
                <p className={`text-xs mt-2 ${testResult.ok ? 'text-emerald-400' : 'text-destructive'}`}>{testResult.msg}</p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
