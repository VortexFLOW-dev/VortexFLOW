// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

import { useEffect, useState } from 'react'
import { instancesApi, fleetsApi } from '@/lib/api'
import type { FleetInstance, FleetState, Instance, Fleet } from '@/lib/types'
import { useAuth } from '@/lib/auth'
import { btnPrimary, btnSecondary, btnDanger, inputCls } from '@/lib/ui'
import PageHeader from '@/components/ui/PageHeader'
import EmptyState from '@/components/ui/EmptyState'

// ─── Fleet-view helpers ───────────────────────────────────────────────────────

const STATE_COLOR: Record<FleetState, string> = {
  healthy: 'bg-emerald-400',
  degraded: 'bg-amber-400',
  offline: 'bg-destructive',
  inactive: 'bg-muted-foreground/40',
  unknown: 'bg-muted-foreground/40',
}

function StatusDot({ state, reason }: { state: FleetState; reason: string }) {
  return (
    <span
      className={`h-2.5 w-2.5 rounded-full flex-shrink-0 ${STATE_COLOR[state] ?? 'bg-muted-foreground/40'}`}
      title={reason}
    />
  )
}

function timeAgo(iso: string | null): string {
  if (!iso) return '—'
  const s = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
  if (s < 0) return 'just now'
  if (s < 60) return `${s}s ago`
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  return `${Math.floor(s / 86400)}d ago`
}

function fmtRate(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`
  if (n >= 10) return n.toFixed(0)
  return n.toFixed(1)
}

interface InstanceFormData {
  label: string
  api_url: string
  config_push_mode: 'local' | 'agent'
  config_dir: string
  agent_url: string
  agent_token: string
  data_dir: string
  expire_metrics_secs: string
  tls_verify: boolean
  tls_ca_cert: string
}

const defaultForm: InstanceFormData = {
  label: '',
  api_url: 'http://localhost:8686',
  config_push_mode: 'local',
  config_dir: '',
  agent_url: '',
  agent_token: '',
  data_dir: '',
  expire_metrics_secs: '',
  tls_verify: true,
  tls_ca_cert: '',
}

function Modal({
  title,
  onClose,
  children,
}: {
  title: string
  onClose: () => void
  children: React.ReactNode
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div className="bg-card border border-border rounded-xl w-full max-w-lg shadow-xl max-h-[90vh] flex flex-col">
        <div className="flex items-center justify-between px-6 py-4 border-b border-border flex-shrink-0">
          <h2 className="text-sm font-semibold text-foreground">{title}</h2>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground transition-colors">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="h-4 w-4">
              <path d="M18 6L6 18M6 6l12 12" strokeLinecap="round" />
            </svg>
          </button>
        </div>
        <div className="overflow-y-auto">{children}</div>
      </div>
    </div>
  )
}

function InstanceForm({
  initial,
  onSubmit,
  onClose,
  submitLabel,
}: {
  initial: InstanceFormData
  onSubmit: (data: InstanceFormData) => Promise<void>
  onClose: () => void
  submitLabel: string
}) {
  const [form, setForm] = useState(initial)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const set = (field: keyof InstanceFormData, value: string | boolean) =>
    setForm((f) => ({ ...f, [field]: value }))

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaving(true)
    setError(null)
    try {
      await onSubmit(form)
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg ?? 'Something went wrong')
    } finally {
      setSaving(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="p-6 space-y-4">
      <Field label="Label" required>
        <input
          className={inputCls}
          value={form.label}
          onChange={(e) => set('label', e.target.value)}
          placeholder="Production Vector"
          required
        />
      </Field>
      <Field label="Vector API URL" required>
        <input
          className={inputCls}
          value={form.api_url}
          onChange={(e) => set('api_url', e.target.value)}
          placeholder="http://localhost:8686"
          required
        />
      </Field>
      <Field label="Config push mode">
        <select
          className={inputCls}
          value={form.config_push_mode}
          onChange={(e) => set('config_push_mode', e.target.value as 'local' | 'agent')}
        >
          <option value="local">Local (shared volume)</option>
          <option value="agent">Agent (remote push)</option>
        </select>
      </Field>
      {form.config_push_mode === 'local' && (
        <Field label="Config directory">
          <input
            className={inputCls}
            value={form.config_dir}
            onChange={(e) => set('config_dir', e.target.value)}
            placeholder="/etc/vector/config.d"
          />
        </Field>
      )}
      {form.config_push_mode === 'agent' && (
        <>
          <Field label="Agent URL">
            <input
              className={inputCls}
              value={form.agent_url}
              onChange={(e) => set('agent_url', e.target.value)}
              placeholder="http://10.0.0.5:9000"
            />
          </Field>
          <Field label="Agent token">
            <input
              className={inputCls}
              type="password"
              value={form.agent_token}
              onChange={(e) => set('agent_token', e.target.value)}
              placeholder="••••••••"
            />
          </Field>
        </>
      )}
      {/* Vector global options — applied to this host's config on deploy */}
      <Field label="Data directory">
        <input
          className={inputCls}
          value={form.data_dir}
          onChange={(e) => set('data_dir', e.target.value)}
          placeholder="/var/lib/vector"
        />
        <p className="text-xs text-muted-foreground/60 mt-1">
          Where Vector stores state and disk buffers on this host. Required for disk buffers.
        </p>
      </Field>
      <Field label="Expire metrics (seconds)">
        <input
          className={inputCls}
          type="number"
          min={0}
          value={form.expire_metrics_secs}
          onChange={(e) => set('expire_metrics_secs', e.target.value)}
          placeholder="e.g. 300"
        />
        <p className="text-xs text-muted-foreground/60 mt-1">
          Drop metrics not updated within this window — bounds cardinality. Leave blank for Vector's default.
        </p>
      </Field>
      {/* TLS */}
      {form.api_url.startsWith('https://') && (
        <>
          <Field label="TLS verification">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={form.tls_verify}
                onChange={(e) => set('tls_verify', e.target.checked)}
                className="accent-primary"
              />
              <span className="text-sm text-foreground">Verify TLS certificate</span>
            </label>
            {!form.tls_verify && (
              <p className="text-xs text-amber-400 mt-1">
                Disabling verification is insecure. Use a custom CA cert instead when possible.
              </p>
            )}
          </Field>
          <Field label="Custom CA certificate (PEM)">
            <textarea
              className={`${inputCls} font-mono text-xs leading-relaxed resize-y min-h-[80px]`}
              value={form.tls_ca_cert}
              onChange={(e) => set('tls_ca_cert', e.target.value)}
              placeholder="-----BEGIN CERTIFICATE-----&#10;MIICxxx...&#10;-----END CERTIFICATE-----"
              rows={4}
            />
            <p className="text-xs text-muted-foreground/60 mt-1">
              Paste your private CA's root cert if Vector uses a self-signed certificate.
            </p>
          </Field>
        </>
      )}
      {error && <p className="text-xs text-destructive">{error}</p>}
      <div className="flex justify-end gap-3 pt-2">
        <button type="button" onClick={onClose} className={btnSecondary}>
          Cancel
        </button>
        <button type="submit" disabled={saving} className={btnPrimary}>
          {saving ? 'Saving…' : submitLabel}
        </button>
      </div>
    </form>
  )
}

function Field({ label, required, children }: { label: string; required?: boolean; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <label className="text-xs font-medium text-muted-foreground">
        {label}
        {required && <span className="text-destructive ml-0.5">*</span>}
      </label>
      {children}
    </div>
  )
}

function AssignFleetModal({
  instance,
  fleets,
  onClose,
  onDone,
}: {
  instance: Instance
  fleets: Fleet[]
  onClose: () => void
  onDone: () => void
}) {
  const [fleetId, setFleetId] = useState(instance.fleet_id ?? '')
  const [role, setRole] = useState<'agent' | 'aggregator'>(
    (instance.role as 'agent' | 'aggregator') ?? 'agent'
  )
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSave = async () => {
    setSaving(true)
    setError(null)
    try {
      if (!fleetId) {
        // Unassign: remove from current fleet
        if (instance.fleet_id) {
          await fleetsApi.removeInstance(instance.fleet_id, instance.id)
        }
      } else {
        await fleetsApi.addInstance(fleetId, instance.id, role)
      }
      onDone()
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg ?? 'Something went wrong')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal title={`Assign fleet — ${instance.label}`} onClose={onClose}>
      <div className="p-6 space-y-4">
        <div className="space-y-1.5">
          <label className="text-xs font-medium text-muted-foreground">Fleet</label>
          <select
            className={inputCls}
            value={fleetId}
            onChange={(e) => setFleetId(e.target.value)}
          >
            <option value="">— Unassigned —</option>
            {fleets.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
                {s.is_default ? ' (default)' : ''}
              </option>
            ))}
          </select>
        </div>
        {fleetId && (
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-muted-foreground">Role</label>
            <select
              className={inputCls}
              value={role}
              onChange={(e) => setRole(e.target.value as 'agent' | 'aggregator')}
            >
              <option value="agent">Agent</option>
              <option value="aggregator">Aggregator</option>
            </select>
          </div>
        )}
        {error && <p className="text-xs text-destructive">{error}</p>}
        <div className="flex justify-end gap-3 pt-2">
          <button type="button" onClick={onClose} className={btnSecondary}>
            Cancel
          </button>
          <button onClick={handleSave} disabled={saving} className={btnPrimary}>
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </Modal>
  )
}

export default function Instances() {
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'
  const [instances, setInstances] = useState<Instance[]>([])
  const [fleets, setFleets] = useState<Fleet[]>([])
  const [fleet, setFleet] = useState<Record<string, FleetInstance>>({})
  const [fleetGenerations, setFleetGenerations] = useState<
    Record<string, { name: string; generation: number; is_default: boolean }>
  >({})
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState<'all' | FleetState>('all')
  const [showAdd, setShowAdd] = useState(false)
  const [editing, setEditing] = useState<Instance | null>(null)
  const [deleting, setDeleting] = useState<Instance | null>(null)
  const [assigning, setAssigning] = useState<Instance | null>(null)

  const refreshFleet = () =>
    instancesApi
      .fleet()
      .then((r) => {
        const map: Record<string, FleetInstance> = {}
        r.data.instances.forEach((f) => {
          map[f.id] = f
        })
        setFleet(map)
        setFleetGenerations(r.data.fleets)
      })
      .catch(() => {})

  const load = () =>
    Promise.all([
      instancesApi.list().then((r) => setInstances(r.data)),
      fleetsApi.list().then((r) => setFleets(r.data.fleets)),
      refreshFleet(),
    ]).finally(() => setLoading(false))

  useEffect(() => { load() }, [])

  // Live status/throughput refresh independent of CRUD reloads.
  useEffect(() => {
    const t = setInterval(() => { void refreshFleet() }, 20000)
    return () => clearInterval(t)
  }, [])

  const handleCreate = async (form: InstanceFormData) => {
    await instancesApi.create({
      ...form,
      config_dir: form.config_dir || null,
      agent_url: form.agent_url || null,
      agent_token: form.agent_token || null,
      data_dir: form.data_dir || null,
      expire_metrics_secs: form.expire_metrics_secs ? Number(form.expire_metrics_secs) : null,
      tls_ca_cert: form.tls_ca_cert || null,
    })
    setShowAdd(false)
    load()
  }

  const handleUpdate = async (form: InstanceFormData) => {
    if (!editing) return
    await instancesApi.update(editing.id, {
      ...form,
      config_dir: form.config_dir || null,
      agent_url: form.agent_url || null,
      agent_token: form.agent_token || undefined,
      data_dir: form.data_dir || null,
      expire_metrics_secs: form.expire_metrics_secs ? Number(form.expire_metrics_secs) : null,
      tls_ca_cert: form.tls_ca_cert || null,
    })
    setEditing(null)
    load()
  }

  const handleDelete = async () => {
    if (!deleting) return
    await instancesApi.delete(deleting.id)
    setDeleting(null)
    load()
  }

  // Filter + group instances by fleet for the fleet console view.
  const matches = (inst: Instance) => {
    const st = fleet[inst.id]?.status.state
    if (statusFilter !== 'all' && st !== statusFilter) return false
    if (search.trim()) {
      const q = search.toLowerCase()
      if (
        !inst.label.toLowerCase().includes(q) &&
        !inst.api_url.toLowerCase().includes(q)
      )
        return false
    }
    return true
  }
  const visible = instances.filter(matches)
  type Group = { id: string | null; name: string; generation: number | null; members: Instance[] }
  const groups: Group[] = []
  fleets.forEach((s) => {
    const members = visible.filter((i) => i.fleet_id === s.id)
    if (members.length)
      groups.push({ id: s.id, name: s.name, generation: fleetGenerations[s.id]?.generation ?? null, members })
  })
  const unassigned = visible.filter(
    (i) => !i.fleet_id || !fleets.some((s) => s.id === i.fleet_id),
  )
  if (unassigned.length)
    groups.push({ id: null, name: 'Unassigned', generation: null, members: unassigned })

  const counts = (members: Instance[]) => {
    let healthy = 0, degraded = 0, offline = 0
    members.forEach((m) => {
      const st = fleet[m.id]?.status.state
      if (st === 'healthy') healthy++
      else if (st === 'degraded') degraded++
      else if (st === 'offline') offline++
    })
    return { healthy, degraded, offline }
  }

  return (
    <div className="p-6 space-y-6">
      <PageHeader
        title="Instances"
        description="Vector nodes across your fleet — live status, version, and throughput"
        actions={
          <div className="flex items-center gap-2">
            <button onClick={() => { void refreshFleet() }} className={btnSecondary}>
              Refresh
            </button>
            {isAdmin && (
              <button onClick={() => setShowAdd(true)} className={btnPrimary}>
                Add instance
              </button>
            )}
          </div>
        }
      />

      {!loading && instances.length > 0 && (
        <div className="flex items-center gap-2">
          <input
            className={inputCls + ' max-w-xs'}
            placeholder="Search label or host…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <select
            className="bg-background border border-border rounded-lg px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as 'all' | FleetState)}
          >
            <option value="all">All statuses</option>
            <option value="healthy">Healthy</option>
            <option value="degraded">Degraded</option>
            <option value="offline">Offline</option>
            <option value="unknown">Unknown</option>
            <option value="inactive">Inactive</option>
          </select>
        </div>
      )}

      {loading ? (
        <div className="space-y-3">
          {[...Array(2)].map((_, i) => (
            <div key={i} className="bg-card border border-border rounded-xl h-20 animate-pulse" />
          ))}
        </div>
      ) : instances.length === 0 ? (
        <EmptyState>
          No instances yet.{' '}
          {isAdmin && (
            <button onClick={() => setShowAdd(true)} className="text-primary hover:text-primary/80 transition-colors">
              Add your first instance →
            </button>
          )}
        </EmptyState>
      ) : groups.length === 0 ? (
        <EmptyState>No instances match your filters.</EmptyState>
      ) : (
        <div className="space-y-5">
          {groups.map((g) => {
            const c = counts(g.members)
            return (
              <div key={g.id ?? 'unassigned'} className="space-y-2">
                <div className="flex items-center gap-3">
                  <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                    {g.name}
                    {g.generation != null && (
                      <span className="ml-2 text-muted-foreground/50 normal-case font-normal">gen {g.generation}</span>
                    )}
                  </h3>
                  <span className="text-xs text-muted-foreground/60">
                    {g.members.length} node{g.members.length !== 1 ? 's' : ''}
                  </span>
                  <div className="flex items-center gap-2 text-xs">
                    {c.healthy > 0 && <span className="text-emerald-400">{c.healthy}●</span>}
                    {c.degraded > 0 && <span className="text-amber-400">{c.degraded}●</span>}
                    {c.offline > 0 && <span className="text-destructive">{c.offline}●</span>}
                  </div>
                </div>
                <div className="border border-border rounded-xl overflow-hidden bg-card">
                  {g.members.map((inst, idx) => {
                    const f = fleet[inst.id]
                    const st: FleetState = f?.status.state ?? 'unknown'
                    return (
                      <div
                        key={inst.id}
                        className={`flex items-center gap-3 px-4 py-3 ${idx < g.members.length - 1 ? 'border-b border-border' : ''} ${!inst.is_active ? 'opacity-60' : ''}`}
                      >
                        <StatusDot state={st} reason={f?.status.reason ?? 'No data'} />
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="text-sm font-medium text-foreground">{inst.label}</span>
                            <span className="text-xs text-muted-foreground bg-secondary px-1.5 py-0.5 rounded">{inst.config_push_mode}</span>
                            <span className="text-xs text-muted-foreground/70">{inst.role}</span>
                            {f?.version_drift && (
                              <span className="text-xs text-amber-400 bg-amber-400/10 px-1.5 py-0.5 rounded">drift</span>
                            )}
                            {f?.config_synced === false && (
                              <span className="text-xs text-amber-400 bg-amber-400/10 px-1.5 py-0.5 rounded">pending → {f.fleet_generation}</span>
                            )}
                            {!inst.is_active && (
                              <span className="text-xs text-muted-foreground bg-secondary px-1.5 py-0.5 rounded">inactive</span>
                            )}
                          </div>
                          <div className="text-xs text-muted-foreground mt-0.5 truncate">
                            {inst.api_url}
                            <span className="text-muted-foreground/50"> · v{f?.vector_version ?? '—'}</span>
                            {inst.config_push_mode === 'agent' && (
                              <span className="text-muted-foreground/50"> · seen {timeAgo(f?.agent_last_seen ?? null)}</span>
                            )}
                          </div>
                        </div>
                        <div className="hidden sm:flex items-center gap-3 flex-shrink-0 text-xs text-muted-foreground/80 font-mono">
                          <span title="events in/sec">▲{fmtRate(f?.metrics.events_in_per_sec ?? 0)}</span>
                          <span title="events out/sec">▼{fmtRate(f?.metrics.events_out_per_sec ?? 0)}</span>
                          <span title="errors/sec" className={f && f.metrics.errors_per_sec > 0 ? 'text-destructive' : ''}>⚠{fmtRate(f?.metrics.errors_per_sec ?? 0)}</span>
                          {/* P2 health chips — only shown when unhealthy, so green rows stay clean */}
                          {(f?.metrics.sink_failed_per_sec ?? 0) > 0 && (
                            <span title="failed sink deliveries (4xx/5xx) per sec" className="text-destructive">✦{fmtRate(f!.metrics.sink_failed_per_sec ?? 0)}</span>
                          )}
                          {(f?.metrics.discarded_per_sec ?? 0) > 0 && (
                            <span title="dropped events per sec (data loss)" className="text-destructive">✕{fmtRate(f!.metrics.discarded_per_sec ?? 0)}</span>
                          )}
                          {(f?.metrics.buffer_events ?? 0) > 0 && (
                            <span title="events queued in buffer (backpressure)" className="text-amber-400">▮{Math.round(f!.metrics.buffer_events ?? 0)}</span>
                          )}
                        </div>
                        <div className="flex items-center gap-1 flex-shrink-0">
                          {isAdmin && (
                            <>
                              <button onClick={() => setAssigning(inst)} className="text-xs text-muted-foreground hover:text-foreground transition-colors px-2 py-1">Fleet</button>
                              <button onClick={() => setEditing(inst)} className="text-xs text-muted-foreground hover:text-foreground transition-colors px-2 py-1">Edit</button>
                              <button onClick={() => setDeleting(inst)} className="text-xs text-destructive/60 hover:text-destructive transition-colors px-2 py-1">Delete</button>
                            </>
                          )}
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            )
          })}
        </div>
      )}

      {showAdd && (
        <Modal title="Add instance" onClose={() => setShowAdd(false)}>
          <InstanceForm
            initial={defaultForm}
            onSubmit={handleCreate}
            onClose={() => setShowAdd(false)}
            submitLabel="Add instance"
          />
        </Modal>
      )}

      {editing && (
        <Modal title="Edit instance" onClose={() => setEditing(null)}>
          <InstanceForm
            initial={{
              label: editing.label,
              api_url: editing.api_url,
              config_push_mode: editing.config_push_mode,
              config_dir: editing.config_dir ?? '',
              agent_url: editing.agent_url ?? '',
              agent_token: '',
              data_dir: editing.data_dir ?? '',
              expire_metrics_secs:
                editing.expire_metrics_secs != null ? String(editing.expire_metrics_secs) : '',
              tls_verify: editing.tls_verify,
              tls_ca_cert: editing.tls_ca_cert ?? '',
            }}
            onSubmit={handleUpdate}
            onClose={() => setEditing(null)}
            submitLabel="Save changes"
          />
        </Modal>
      )}

      {deleting && (
        <Modal title="Delete instance" onClose={() => setDeleting(null)}>
          <div className="p-6 space-y-4">
            <p className="text-sm text-foreground">
              Delete <span className="font-medium">{deleting.label}</span>? This will also delete all
              pipelines associated with this instance. This cannot be undone.
            </p>
            <div className="flex justify-end gap-3">
              <button onClick={() => setDeleting(null)} className={btnSecondary}>
                Cancel
              </button>
              <button onClick={handleDelete} className={btnDanger}>
                Delete
              </button>
            </div>
          </div>
        </Modal>
      )}

      {assigning && (
        <AssignFleetModal
          instance={assigning}
          fleets={fleets}
          onClose={() => setAssigning(null)}
          onDone={() => { setAssigning(null); load() }}
        />
      )}
    </div>
  )
}
