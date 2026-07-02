// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

import { useCallback, useEffect, useState } from 'react'
import { fleetsApi, instancesApi } from '@/lib/api'
import type { Instance, InstanceInFleet, FleetWithInstances } from '@/lib/types'
import { useAuth } from '@/lib/auth'
import { btnPrimary, btnSecondary, btnGhost, inputCls } from '@/lib/ui'
import DangerConfirm from '@/components/shared/DangerConfirm'

// ── Modal shell ─────────────────────────────────────────────────────────────
function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div className="bg-card border border-border rounded-xl w-full max-w-md shadow-xl max-h-[90vh] flex flex-col">
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

// ── New / Rename Fleet modal ────────────────────────────────────────────────
function FleetFormModal({
  initial,
  onSave,
  onClose,
}: {
  initial?: { name: string; description: string }
  onSave: (name: string, description: string) => Promise<void>
  onClose: () => void
}) {
  const [name, setName] = useState(initial?.name ?? '')
  const [description, setDescription] = useState(initial?.description ?? '')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim()) { setError('Name is required'); return }
    setSaving(true)
    try {
      await onSave(name.trim(), description.trim())
    } catch {
      setError('Failed to save fleet')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal title={initial ? 'Rename fleet' : 'New fleet'} onClose={onClose}>
      <form onSubmit={handleSubmit} className="p-6 space-y-4">
        <div className="space-y-1.5">
          <label className="text-xs font-medium text-muted-foreground">
            Name <span className="text-destructive">*</span>
          </label>
          <input
            className={inputCls}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="production"
            autoFocus
          />
        </div>
        <div className="space-y-1.5">
          <label className="text-xs font-medium text-muted-foreground">Description</label>
          <input
            className={inputCls}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Production Vector fleet"
          />
        </div>
        {error && <p className="text-xs text-destructive">{error}</p>}
        <div className="flex justify-end gap-3 pt-1">
          <button type="button" onClick={onClose} className={btnSecondary}>Cancel</button>
          <button type="submit" disabled={saving} className={btnPrimary}>
            {saving ? 'Saving…' : initial ? 'Rename' : 'Create fleet'}
          </button>
        </div>
      </form>
    </Modal>
  )
}

// ── Vector version modal ──────────────────────────────────────────────────────
function VectorVersionModal({
  initial,
  onSave,
  onClose,
}: {
  initial: string
  onSave: (version: string) => Promise<void>
  onClose: () => void
}) {
  const [version, setVersion] = useState(initial)
  const [saving, setSaving] = useState(false)
  const submit = async (v: string) => {
    setSaving(true)
    try {
      await onSave(v)
    } finally {
      setSaving(false)
    }
  }
  return (
    <Modal title="Fleet Vector version" onClose={onClose}>
      <div className="p-6 space-y-4">
        <p className="text-xs text-muted-foreground">
          Pin a Vector version for this fleet's agents — overrides the global default and lets
          you roll a version to one fleet at a time. Agents reconcile to it on their next poll.
          Leave empty to inherit the global default (Settings → General).
        </p>
        <input
          className={inputCls}
          value={version}
          onChange={(e) => setVersion(e.target.value)}
          placeholder="e.g. 0.42.0 — empty inherits global"
          autoFocus
        />
        <div className="flex justify-end gap-3 pt-1">
          <button type="button" onClick={() => void submit('')} disabled={saving} className={btnSecondary}>
            Clear (inherit)
          </button>
          <button type="button" onClick={() => void submit(version.trim())} disabled={saving} className={btnPrimary}>
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </Modal>
  )
}

// ── Add Instance modal ───────────────────────────────────────────────────────
function AddInstanceModal({
  fleetId,
  existingIds,
  onAdded,
  onClose,
}: {
  fleetId: string
  existingIds: Set<string>
  onAdded: () => void
  onClose: () => void
}) {
  const [instances, setInstances] = useState<Instance[]>([])
  const [loading, setLoading] = useState(true)
  const [selectedId, setSelectedId] = useState<string>('')
  const [role, setRole] = useState<'agent' | 'aggregator'>('agent')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    instancesApi
      .list()
      .then((r) => {
        const all: Instance[] = r.data ?? []
        setInstances(all.filter((i) => !existingIds.has(i.id)))
      })
      .catch(() => setError('Failed to load instances'))
      .finally(() => setLoading(false))
  }, [existingIds])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!selectedId) { setError('Select an instance'); return }
    setSaving(true)
    try {
      await fleetsApi.addInstance(fleetId, selectedId, role)
      onAdded()
    } catch {
      setError('Failed to add instance')
    } finally {
      setSaving(false)
    }
  }

  const selectCls =
    'w-full bg-background border border-border rounded-lg px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary focus:border-primary'

  return (
    <Modal title="Add instance to fleet" onClose={onClose}>
      <form onSubmit={handleSubmit} className="p-6 space-y-4">
        {loading ? (
          <div className="space-y-2">
            {[...Array(3)].map((_, i) => (
              <div key={i} className="h-9 bg-secondary rounded-lg animate-pulse" />
            ))}
          </div>
        ) : instances.length === 0 ? (
          <p className="text-sm text-muted-foreground">All instances are already in this fleet.</p>
        ) : (
          <>
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-muted-foreground">
                Instance <span className="text-destructive">*</span>
              </label>
              <select
                className={selectCls}
                value={selectedId}
                onChange={(e) => setSelectedId(e.target.value)}
              >
                <option value="">Select an instance…</option>
                {instances.map((i) => (
                  <option key={i.id} value={i.id}>{i.label}</option>
                ))}
              </select>
            </div>
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-muted-foreground">Role</label>
              <select
                className={selectCls}
                value={role}
                onChange={(e) => setRole(e.target.value as 'agent' | 'aggregator')}
              >
                <option value="agent">Agent</option>
                <option value="aggregator">Aggregator</option>
              </select>
            </div>
          </>
        )}
        {error && <p className="text-xs text-destructive">{error}</p>}
        <div className="flex justify-end gap-3 pt-1">
          <button type="button" onClick={onClose} className={btnSecondary}>Cancel</button>
          <button
            type="submit"
            disabled={saving || loading || instances.length === 0}
            className={btnPrimary}
          >
            {saving ? 'Adding…' : 'Add instance'}
          </button>
        </div>
      </form>
    </Modal>
  )
}

// ── Bootstrap token modal ────────────────────────────────────────────────────
function BootstrapModal({
  fleetId,
  onClose,
}: {
  fleetId: string
  onClose: () => void
}) {
  const [token, setToken] = useState<string | null>(null)
  const [command, setCommand] = useState<string | null>(null)
  const [generating, setGenerating] = useState(false)
  const [copiedToken, setCopiedToken] = useState(false)
  const [copiedCommand, setCopiedCommand] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fleetsApi
      .getBootstrapCommand(fleetId)
      .then((r) => {
        if (r.data.token_set) setCommand(r.data.command)
      })
      .catch(() => {
        // Command fetch is best-effort — shown after token generation
      })
  }, [fleetId])

  const buildInstallCommand = (t: string) => {
    const base = window.location.origin
    return `curl -sL -H "X-Bootstrap-Token: ${t}" "${base}/install/fleet/${fleetId}" | sudo bash`
  }

  const generateToken = async () => {
    setGenerating(true)
    setError(null)
    try {
      const r = await fleetsApi.generateBootstrapToken(fleetId)
      setToken(r.data.token)
      setCommand(buildInstallCommand(r.data.token))
    } catch {
      setError('Failed to generate bootstrap token')
    } finally {
      setGenerating(false)
    }
  }

  const copyToken = async () => {
    if (!token) return
    try {
      await navigator.clipboard.writeText(token)
      setCopiedToken(true)
      setTimeout(() => setCopiedToken(false), 2000)
    } catch {
      // clipboard unavailable
    }
  }

  const copyCommand = async () => {
    if (!command) return
    try {
      await navigator.clipboard.writeText(command)
      setCopiedCommand(true)
      setTimeout(() => setCopiedCommand(false), 2000)
    } catch {
      // clipboard unavailable
    }
  }

  return (
    <Modal title="Bootstrap fleet" onClose={onClose}>
      <div className="p-6 space-y-5">
        <p className="text-sm text-muted-foreground">
          Generate a one-time bootstrap token for this fleet. Agents use this token to
          self-register on first start.
        </p>

        {token && (
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-muted-foreground">Bootstrap token</span>
              <button onClick={copyToken} className={btnGhost}>
                {copiedToken ? 'Copied!' : 'Copy'}
              </button>
            </div>
            <div className="bg-background border border-border rounded-lg p-3 font-mono text-xs text-foreground break-all">
              {token}
            </div>
            <p className="text-xs text-destructive font-medium">
              This is the only time this token will be shown. Save it now.
            </p>
          </div>
        )}

        {command && (
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-muted-foreground">Install command</span>
              <button onClick={copyCommand} className={btnGhost}>
                {copiedCommand ? 'Copied!' : 'Copy'}
              </button>
            </div>
            <div className="bg-background border border-border rounded-lg p-3 font-mono text-xs text-foreground break-all whitespace-pre-wrap">
              {command}
            </div>
          </div>
        )}

        {error && <p className="text-xs text-destructive">{error}</p>}

        <div className="flex justify-end gap-3">
          <button onClick={onClose} className={btnSecondary}>Close</button>
          <button onClick={generateToken} disabled={generating} className={btnPrimary}>
            {generating ? 'Generating…' : 'Generate token'}
          </button>
        </div>
      </div>
    </Modal>
  )
}

// ── Role badge ───────────────────────────────────────────────────────────────
function ConfigModal({
  fleet,
  isAdmin,
  onClose,
}: {
  fleet: FleetWithInstances
  isAdmin: boolean
  onClose: () => void
}) {
  const [yamlText, setYamlText] = useState<string | null>(null)
  const [warnings, setWarnings] = useState<string[]>([])
  const [errors, setErrors] = useState<string[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const [deploying, setDeploying] = useState(false)
  const [deployResult, setDeployResult] = useState<
    Awaited<ReturnType<typeof fleetsApi.deploy>>['data'] | null
  >(null)
  const [validating, setValidating] = useState(false)
  const [validation, setValidation] = useState<
    Awaited<ReturnType<typeof fleetsApi.validate>>['data'] | null
  >(null)

  useEffect(() => {
    fleetsApi
      .getConfig(fleet.id)
      .then((r) => {
        setYamlText(r.data.yaml)
        setWarnings(r.data.warnings)
        setErrors(r.data.errors ?? [])
      })
      .catch(() => setError('Failed to render config'))
      .finally(() => setLoading(false))
  }, [fleet.id])

  const isEmpty = !yamlText || yamlText.trim() === '{}' || yamlText.trim() === ''

  const copy = async () => {
    if (!yamlText) return
    await navigator.clipboard.writeText(yamlText)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  const validate = async () => {
    setValidating(true)
    setValidation(null)
    setError(null)
    try {
      const r = await fleetsApi.validate(fleet.id)
      setValidation(r.data)
    } catch {
      setError('Validation request failed')
    } finally {
      setValidating(false)
    }
  }

  const deploy = async () => {
    setDeploying(true)
    setError(null)
    try {
      const r = await fleetsApi.deploy(fleet.id)
      setDeployResult(r.data)
    } catch (e) {
      // A 409 carries the blocking errors that gated the deploy server-side.
      const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data
        ?.detail
      if (detail && typeof detail === 'object' && Array.isArray((detail as { errors?: unknown }).errors)) {
        setErrors((detail as { errors: string[] }).errors)
        setError('Deploy refused — fix the blocking errors below.')
      } else {
        setError('Deploy failed')
      }
    } finally {
      setDeploying(false)
    }
  }

  return (
    <Modal title={`Config — ${fleet.name}`} onClose={onClose}>
      {loading ? (
        <p className="text-sm text-muted-foreground">Rendering…</p>
      ) : error && !deployResult ? (
        <p className="text-sm text-destructive">{error}</p>
      ) : isEmpty ? (
        <p className="text-sm text-muted-foreground">
          This fleet has no wired components yet. Add sources and sinks in the Catalog and
          connect them with a Route, then deploy.
        </p>
      ) : (
        <div className="space-y-3">
          {errors.length > 0 && (
            <div className="rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2">
              <p className="text-xs font-medium text-destructive mb-1">
                {errors.length} blocking {errors.length === 1 ? 'error' : 'errors'} — deploy is
                disabled until resolved
              </p>
              <ul className="text-xs text-destructive/90 space-y-0.5 list-disc pl-4">
                {errors.map((e, i) => (
                  <li key={i}>{e}</li>
                ))}
              </ul>
            </div>
          )}

          {warnings.length > 0 && (
            <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2">
              <p className="text-xs font-medium text-amber-400 mb-1">
                {warnings.length} {warnings.length === 1 ? 'warning' : 'warnings'}
              </p>
              <ul className="text-xs text-amber-300/80 space-y-0.5 list-disc pl-4">
                {warnings.map((w, i) => (
                  <li key={i}>{w}</li>
                ))}
              </ul>
            </div>
          )}

          {validation && (
            <div
              className={
                validation.status === 'valid'
                  ? 'rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2'
                  : validation.status === 'invalid'
                    ? 'rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2'
                    : 'rounded-lg border border-border bg-secondary/40 px-3 py-2'
              }
            >
              <p
                className={
                  validation.status === 'valid'
                    ? 'text-xs font-medium text-emerald-400'
                    : validation.status === 'invalid'
                      ? 'text-xs font-medium text-destructive'
                      : 'text-xs font-medium text-muted-foreground'
                }
              >
                {validation.status === 'valid'
                  ? '✓ vector validate passed'
                  : validation.status === 'invalid'
                    ? '✗ vector validate failed'
                    : 'Validation unavailable — no Vector binary on the server'}
              </p>
              {validation.output && validation.status === 'invalid' && (
                <pre className="mt-1 text-xs font-mono text-destructive/90 whitespace-pre-wrap max-h-40 overflow-auto">
                  {validation.output}
                </pre>
              )}
            </div>
          )}

          <div className="relative">
            <button onClick={copy} className={`${btnGhost} absolute right-2 top-2`}>
              {copied ? 'Copied' : 'Copy'}
            </button>
            <pre className="bg-secondary/50 border border-border rounded-lg p-3 text-xs font-mono text-foreground/90 overflow-auto max-h-80 whitespace-pre">
              {yamlText}
            </pre>
          </div>

          {deployResult && (
            <div className="rounded-lg border border-border bg-secondary/40 px-3 py-2 space-y-1">
              <p className="text-xs font-medium text-foreground">
                Deployed to {deployResult.deployed}/{deployResult.total} instances
              </p>
              {deployResult.results.map((r) => (
                <div key={r.instance_id} className="flex items-center gap-2 text-xs">
                  <span
                    className={
                      r.status === 'deployed'
                        ? 'text-emerald-400'
                        : r.status === 'skipped'
                          ? 'text-muted-foreground'
                          : 'text-destructive'
                    }
                  >
                    {r.status === 'deployed' ? '✓' : r.status === 'skipped' ? '–' : '✗'}
                  </span>
                  <span className="text-foreground/80">{r.label}</span>
                  {r.detail && <span className="text-muted-foreground/70">— {r.detail}</span>}
                </div>
              ))}
            </div>
          )}

          <div className="flex items-center justify-end gap-2 pt-1">
            <button onClick={onClose} className={btnSecondary}>
              Close
            </button>
            <button onClick={validate} disabled={validating} className={btnSecondary}>
              {validating ? 'Validating…' : 'Validate'}
            </button>
            {isAdmin && (
              <button
                onClick={deploy}
                disabled={deploying || errors.length > 0}
                className={btnPrimary}
                title={
                  errors.length > 0 ? 'Resolve blocking errors before deploying' : undefined
                }
              >
                {deploying ? 'Deploying…' : 'Deploy to instances'}
              </button>
            )}
          </div>
        </div>
      )}
    </Modal>
  )
}

function timeAgo(iso: string | null): string {
  if (!iso) return 'never'
  const s = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
  if (s < 0) return 'just now'
  if (s < 60) return `${s}s ago`
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  return `${Math.floor(s / 86400)}d ago`
}

// Per-agent rollout state relative to the fleet's published generation.
// Local-mode instances are written directly on Deploy, so they have no rollout
// state to show.
function RolloutBadge({ inst, generation }: { inst: InstanceInFleet; generation: number }) {
  if (inst.config_push_mode !== 'agent') return null

  const applied = inst.applied_generation
  const failed =
    inst.agent_status === 'validate_failed' || inst.agent_status === 'reload_failed'

  let cls: string
  let label: string
  if (failed) {
    cls = 'bg-destructive/10 text-destructive'
    label = inst.agent_status === 'validate_failed' ? 'validate failed' : 'reload failed'
  } else if (applied != null && applied === generation) {
    cls = 'bg-primary/10 text-primary'
    label = `gen ${generation}`
  } else {
    cls = 'bg-amber-500/10 text-amber-500'
    label = `gen ${applied ?? '—'} → ${generation}`
  }

  const seen = inst.agent_last_seen ? `agent seen ${timeAgo(inst.agent_last_seen)}` : 'never reported'
  return (
    <span
      title={seen}
      className={`text-[10px] font-medium rounded px-1.5 py-0.5 flex-shrink-0 ${cls}`}
    >
      {label}
    </span>
  )
}

function RoleBadge({ role }: { role: 'agent' | 'aggregator' }) {
  return (
    <span className={`text-xs rounded px-1.5 py-0.5 font-medium ${
      role === 'aggregator'
        ? 'bg-primary/10 text-primary'
        : 'bg-secondary text-muted-foreground'
    }`}>
      {role === 'aggregator' ? 'Aggregator' : 'Agent'}
    </span>
  )
}

// ── Online dot ───────────────────────────────────────────────────────────────
function OnlineDot({ active }: { active: boolean }) {
  return (
    <span className={`h-1.5 w-1.5 rounded-full flex-shrink-0 ${active ? 'bg-primary' : 'bg-muted-foreground/40'}`} />
  )
}

// ── Fleet card ──────────────────────────────────────────────────────────────
function FleetCard({
  fleet,
  isAdmin,
  onRefresh,
}: {
  fleet: FleetWithInstances
  isAdmin: boolean
  onRefresh: () => void
}) {
  const [showRename, setShowRename] = useState(false)
  const [showVersion, setShowVersion] = useState(false)
  const [showAddInstance, setShowAddInstance] = useState(false)
  const [showBootstrap, setShowBootstrap] = useState(false)
  const [showConfig, setShowConfig] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [showDelete, setShowDelete] = useState(false)
  const [impact, setImpact] = useState<
    Awaited<ReturnType<typeof fleetsApi.deleteImpact>>['data'] | null
  >(null)
  const [error, setError] = useState<string | null>(null)

  const handleRename = async (name: string, description: string) => {
    await fleetsApi.update(fleet.id, { name, description: description || undefined })
    setShowRename(false)
    onRefresh()
  }

  const handleSetVersion = async (version: string) => {
    await fleetsApi.update(fleet.id, { desired_vector_version: version })
    setShowVersion(false)
    onRefresh()
  }

  const openDelete = async () => {
    setImpact(null)
    setShowDelete(true)
    try {
      setImpact((await fleetsApi.deleteImpact(fleet.id)).data)
    } catch {
      /* show the confirm without the impact breakdown */
    }
  }

  const confirmDelete = async () => {
    setDeleting(true)
    try {
      await fleetsApi.delete(fleet.id)
      setShowDelete(false)
      onRefresh()
    } catch {
      setError('Failed to delete fleet')
    } finally {
      setDeleting(false)
    }
  }

  const handleRemoveInstance = async (instanceId: string) => {
    try {
      await fleetsApi.removeInstance(fleet.id, instanceId)
      onRefresh()
    } catch {
      setError('Failed to remove instance')
    }
  }

  const existingIds = new Set(fleet.instances.map((i) => i.id))

  return (
    <>
      <div className="bg-card border border-border rounded-xl overflow-hidden">
        {/* Card header */}
        <div className="px-5 py-4 border-b border-border flex items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h3 className="text-sm font-semibold text-foreground truncate">{fleet.name}</h3>
              {fleet.is_default && (
                <span className="text-xs bg-primary/10 text-primary rounded px-1.5 py-0.5 font-medium flex-shrink-0">
                  Default
                </span>
              )}
              <span className="text-xs text-muted-foreground flex-shrink-0">
                {fleet.instances.length} {fleet.instances.length === 1 ? 'instance' : 'instances'}
              </span>
              {fleet.generation > 0 && (
                <span
                  className="text-[10px] text-muted-foreground/70 bg-secondary rounded px-1.5 py-0.5 flex-shrink-0"
                  title="Published config generation"
                >
                  gen {fleet.generation}
                </span>
              )}
              {fleet.desired_vector_version && (
                <span
                  className="text-[10px] text-amber-500 bg-amber-500/10 rounded px-1.5 py-0.5 flex-shrink-0"
                  title="Pinned Vector version for this fleet (overrides the global default)"
                >
                  Vector → {fleet.desired_vector_version}
                </span>
              )}
            </div>
            {fleet.description && (
              <p className="text-xs text-muted-foreground mt-0.5">{fleet.description}</p>
            )}
          </div>

          <div className="flex items-center gap-1.5 flex-shrink-0">
            <button
              onClick={() => setShowConfig(true)}
              className={btnGhost}
              title="View & deploy rendered Vector config"
            >
              Config
            </button>
            {isAdmin && (
            <>
              <button
                onClick={() => setShowRename(true)}
                className={btnGhost}
                title="Rename fleet"
              >
                Rename
              </button>
              <button
                onClick={() => setShowVersion(true)}
                className={btnGhost}
                title="Set this fleet's Vector version (staged rollout)"
              >
                Vector
              </button>
              <button
                onClick={() => setShowBootstrap(true)}
                className={btnGhost}
                title="Bootstrap token"
              >
                Bootstrap
              </button>
              <button
                onClick={() => setShowAddInstance(true)}
                className={btnGhost}
              >
                Add instance
              </button>
              <button
                onClick={openDelete}
                disabled={fleet.is_default || deleting}
                title={fleet.is_default ? 'Cannot delete the default fleet' : 'Delete fleet'}
                className="text-muted-foreground hover:text-destructive text-xs px-2 py-1.5 rounded transition-colors hover:bg-secondary disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {deleting ? 'Deleting…' : 'Delete'}
              </button>
            </>
            )}
          </div>
        </div>

        {/* Instance list */}
        <div className="divide-y divide-border">
          {fleet.instances.length === 0 ? (
            <p className="px-5 py-4 text-xs text-muted-foreground">No instances in this fleet.</p>
          ) : (
            fleet.instances.map((inst) => (
              <div key={inst.id} className="px-5 py-3 flex items-center gap-3">
                <OnlineDot active={inst.is_active} />
                <span className="text-sm text-foreground flex-1 truncate">{inst.label}</span>
                <span className="text-xs text-muted-foreground truncate hidden sm:block">{inst.api_url}</span>
                <RolloutBadge inst={inst} generation={fleet.generation} />
                <RoleBadge role={inst.role} />
                {isAdmin && (
                  <button
                    onClick={() => handleRemoveInstance(inst.id)}
                    className="text-muted-foreground/50 hover:text-destructive transition-colors flex-shrink-0"
                    title="Remove from fleet"
                  >
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="h-3.5 w-3.5">
                      <path d="M18 6L6 18M6 6l12 12" strokeLinecap="round" />
                    </svg>
                  </button>
                )}
              </div>
            ))
          )}
        </div>

        {error && (
          <div className="px-5 py-2 border-t border-border">
            <p className="text-xs text-destructive">{error}</p>
          </div>
        )}
      </div>

      {showRename && (
        <FleetFormModal
          initial={{ name: fleet.name, description: fleet.description ?? '' }}
          onSave={handleRename}
          onClose={() => setShowRename(false)}
        />
      )}

      {showDelete && (
        <DangerConfirm
          title={`Delete fleet "${fleet.name}"`}
          phrase="DELETE"
          confirmLabel="Delete fleet"
          loading={deleting}
          onConfirm={confirmDelete}
          onClose={() => setShowDelete(false)}
        >
          {impact ? (
            <>
              This permanently deletes the fleet and{' '}
              <span className="text-foreground font-medium">all of its configuration</span>:
              <ul className="mt-2 ml-1 space-y-0.5">
                <li>
                  • {impact.sources} source{impact.sources !== 1 ? 's' : ''}, {impact.sinks} sink
                  {impact.sinks !== 1 ? 's' : ''}, {impact.stages} transform
                  {impact.stages !== 1 ? 's' : ''}, {impact.routes} route
                  {impact.routes !== 1 ? 's' : ''} — deleted
                </li>
                {impact.instances.length > 0 && (
                  <li className="text-amber-500">
                    • {impact.instances.length} instance
                    {impact.instances.length !== 1 ? 's' : ''} unassigned:{' '}
                    {impact.instances.join(', ')}
                  </li>
                )}
              </ul>
              <p className="mt-2 text-foreground/80">This cannot be undone.</p>
            </>
          ) : (
            'Loading impact…'
          )}
        </DangerConfirm>
      )}

      {showVersion && (
        <VectorVersionModal
          initial={fleet.desired_vector_version ?? ''}
          onSave={handleSetVersion}
          onClose={() => setShowVersion(false)}
        />
      )}

      {showAddInstance && (
        <AddInstanceModal
          fleetId={fleet.id}
          existingIds={existingIds}
          onAdded={() => { setShowAddInstance(false); onRefresh() }}
          onClose={() => setShowAddInstance(false)}
        />
      )}

      {showBootstrap && (
        <BootstrapModal
          fleetId={fleet.id}
          onClose={() => setShowBootstrap(false)}
        />
      )}

      {showConfig && (
        <ConfigModal
          fleet={fleet}
          isAdmin={isAdmin}
          onClose={() => { setShowConfig(false); onRefresh() }}
        />
      )}
    </>
  )
}

// ── Page ─────────────────────────────────────────────────────────────────────
export default function Fleets() {
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'

  const [fleets, setFleets] = useState<FleetWithInstances[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showNewModal, setShowNewModal] = useState(false)

  const load = useCallback(() => {
    setLoading(true)
    fleetsApi
      .list()
      .then(async (r) => {
        const ids: string[] = (r.data.fleets ?? []).map((s) => s.id)
        const details = await Promise.all(ids.map((id) => fleetsApi.get(id).then((res) => res.data)))
        setFleets(details)
        setError(null)
      })
      .catch(() => setError('Failed to load fleets'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])

  const handleCreate = async (name: string, description: string) => {
    await fleetsApi.create({ name, description: description || undefined })
    setShowNewModal(false)
    load()
  }

  return (
    <div className="p-6 space-y-6">
      {/* Page header */}
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-lg font-semibold text-foreground">Fleets</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Manage Vector fleets and their instance members.
          </p>
        </div>
        {isAdmin && (
          <button onClick={() => setShowNewModal(true)} className={btnPrimary}>
            New fleet
          </button>
        )}
      </div>

      {/* Content */}
      {loading ? (
        <div className="space-y-4">
          {[...Array(2)].map((_, i) => (
            <div key={i} className="bg-card border border-border rounded-xl h-32 animate-pulse" />
          ))}
        </div>
      ) : error ? (
        <div className="bg-card border border-border rounded-xl p-6 text-sm text-destructive">
          {error}
        </div>
      ) : fleets.length === 0 ? (
        <div className="bg-card border border-border rounded-xl p-8 text-center">
          <p className="text-sm text-muted-foreground">No fleets yet.</p>
          {isAdmin && (
            <button onClick={() => setShowNewModal(true)} className={`${btnPrimary} mt-3`}>
              Create first fleet
            </button>
          )}
        </div>
      ) : (
        <div className="space-y-4">
          {fleets.map((s) => (
            <FleetCard key={s.id} fleet={s} isAdmin={isAdmin} onRefresh={load} />
          ))}
        </div>
      )}

      {showNewModal && (
        <FleetFormModal
          onSave={handleCreate}
          onClose={() => setShowNewModal(false)}
        />
      )}
    </div>
  )
}
