// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

/**
 * ComponentConfigForm — the guided source/sink config form (schema-driven fields,
 * TLS cert wiring, generated-YAML preview, save to fleet). Extracted from the
 * Catalog page so it can be reused in the Flow node drawer (build-in-place).
 *
 * Give it a catalog `component` (the schema for a component type) and, to edit an
 * existing node, the saved `existing` Component; it persists create/update itself.
 */

import { useEffect, useState } from 'react'
import { generateYaml, coerceFieldValues, isSecretKey } from '@/lib/catalog'
import type { CatalogComponent, CatalogField } from '@/lib/catalog'
import { componentsApi, certsApi } from '@/lib/api'
import type { Component } from '@/lib/types'
import { useFleet } from '@/lib/fleet'
import { useAuth } from '@/lib/auth'

const inputCls =
  'w-full bg-background border border-border rounded-lg px-3 py-2 text-sm text-foreground ' +
  'placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary focus:border-primary'
const selectCls =
  'w-full bg-background border border-border rounded-lg px-3 py-2 text-sm text-foreground ' +
  'focus:outline-none focus:ring-1 focus:ring-primary focus:border-primary'

// ─── Category / generated badges (shared with the Catalog cards) ───────────────
const CATEGORY_COLORS: Record<string, string> = {
  'File & System': 'bg-zinc-500/15 text-zinc-400',
  Containers: 'bg-sky-500/15 text-sky-500',
  Network: 'bg-violet-500/15 text-violet-500',
  Messaging: 'bg-amber-500/15 text-amber-500',
  Cloud: 'bg-blue-500/15 text-blue-500',
  Metrics: 'bg-teal-500/15 text-teal-500',
  Observability: 'bg-orange-500/15 text-orange-500',
  Analytics: 'bg-rose-500/15 text-rose-500',
  Pipeline: 'bg-primary/15 text-primary',
}

export function CategoryBadge({ category }: { category: string }) {
  const cls = CATEGORY_COLORS[category] ?? 'bg-secondary text-muted-foreground'
  return (
    <span className={`inline-flex items-center text-xs font-medium px-2 py-0.5 rounded-full ${cls}`}>
      {category}
    </span>
  )
}

export function GeneratedBadge() {
  return (
    <span
      title="Auto-generated from the Vector schema — fields are best-effort, not hand-tuned."
      className="inline-flex items-center text-[10px] font-medium px-1.5 py-0.5 rounded-full bg-secondary text-muted-foreground/70 border border-border/60"
    >
      generated
    </span>
  )
}

// ─── Field input ──────────────────────────────────────────────────────────────
function FieldInput({
  field,
  value,
  onChange,
  hasError,
}: {
  field: CatalogField
  value: string
  onChange: (v: string) => void
  hasError?: boolean
}) {
  const errorRing = hasError ? ' border-destructive focus:ring-destructive focus:border-destructive' : ''
  if (field.type === 'select') {
    return (
      <select className={selectCls + errorRing} value={value} onChange={(e) => onChange(e.target.value)}>
        {field.options?.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    )
  }

  if (field.type === 'boolean') {
    return (
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => onChange(value === 'true' ? 'false' : 'true')}
          className={`relative inline-flex h-5 w-9 flex-shrink-0 rounded-full border-2 border-transparent transition-colors ${
            value === 'true' ? 'bg-primary' : 'bg-secondary'
          }`}
        >
          <span
            className={`inline-block h-4 w-4 rounded-full bg-background border border-border shadow-sm transition-transform ${
              value === 'true' ? 'translate-x-4' : 'translate-x-0'
            }`}
          />
        </button>
        <span className="text-xs text-muted-foreground">{value === 'true' ? 'Enabled' : 'Disabled'}</span>
      </div>
    )
  }

  if (field.type === 'array' || field.type === 'textarea') {
    return (
      <textarea
        className={`${inputCls}${errorRing} resize-y min-h-[64px]`}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={field.placeholder}
        rows={3}
      />
    )
  }

  const isSecret = isSecretKey(field.key)
  return (
    <input
      type={isSecret ? 'password' : field.type === 'number' ? 'number' : 'text'}
      autoComplete={isSecret ? 'new-password' : undefined}
      className={inputCls + errorRing}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={field.placeholder ?? (field.default !== undefined ? String(field.default) : '')}
    />
  )
}

// Reverse of coerceFieldValues: stored typed config → string form-state.
function valuesFromConfig(
  component: CatalogComponent,
  config: Record<string, unknown>,
): Record<string, string> {
  const init: Record<string, string> = {}
  for (const f of component.fields) {
    const v = config[f.key]
    if (v === undefined || v === null) {
      init[f.key] = f.default !== undefined ? String(f.default) : ''
    } else if (Array.isArray(v)) {
      init[f.key] = (v as unknown[]).join('\n')
    } else if (typeof v === 'boolean') {
      init[f.key] = v ? 'true' : 'false'
    } else {
      init[f.key] = String(v)
    }
  }
  return init
}

const IDENTITY_FIELDS = new Set(['tls.crt_file', 'tls.key_file', 'tls.key_pass'])
const CA_FIELDS = new Set(['tls.ca_file'])

type CertOption = {
  id: string
  label: string
  cert_type: string
  has_key: boolean
  cn?: string | null
}

function CertSelect({
  label,
  hint,
  certs,
  value,
  onChange,
}: {
  label: string
  hint: string
  certs: CertOption[]
  value: string
  onChange: (id: string) => void
}) {
  return (
    <div className="space-y-1">
      <label className="text-xs font-medium text-muted-foreground">{label}</label>
      <select className={selectCls} value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">— set file path manually —</option>
        {certs.map((c) => (
          <option key={c.id} value={c.id}>
            {c.label}
            {c.cn ? ` (${c.cn})` : ''}
          </option>
        ))}
      </select>
      <p className="text-xs text-muted-foreground/60">{hint}</p>
    </div>
  )
}

export function ComponentConfigForm({
  component,
  kind,
  onClose,
  existing,
  onSaved,
}: {
  component: CatalogComponent
  kind: 'sources' | 'sinks'
  onClose: () => void
  existing?: Component
  onSaved?: () => void
}) {
  const [name, setName] = useState(() => existing?.name ?? component.type.slice(0, 20))
  const [values, setValues] = useState<Record<string, string>>(() => {
    if (existing) return valuesFromConfig(component, existing.config)
    const init: Record<string, string> = {}
    for (const f of component.fields) {
      init[f.key] = f.default !== undefined ? String(f.default) : ''
    }
    return init
  })
  const [copied, setCopied] = useState(false)
  const [rawMode, setRawMode] = useState(false)
  const [rawYaml, setRawYaml] = useState('')
  const [saveState, setSaveState] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')
  const [saveError, setSaveError] = useState<string | null>(null)
  const [touched, setTouched] = useState<Record<string, boolean>>({})
  const [certRefs, setCertRefs] = useState<{ identity?: string; ca?: string }>(
    () => (existing?.cert_refs as { identity?: string; ca?: string }) ?? {},
  )
  const [certs, setCerts] = useState<CertOption[]>([])
  const hasTls = component.fields.some((f) => f.key.startsWith('tls.'))
  const firstTlsKey = component.fields.find((f) => f.key.startsWith('tls.'))?.key

  useEffect(() => {
    if (!hasTls) return
    certsApi
      .list()
      .then((r) => setCerts(r.data as CertOption[]))
      .catch(() => {})
  }, [hasTls])

  const { activeFleet } = useFleet()
  const { user } = useAuth()
  const canEdit = user?.role === 'admin' || user?.role === 'editor'

  const yaml = rawMode ? rawYaml : generateYaml(kind, component, values, name || component.type)

  const missingRequired = component.fields
    .filter((f) => f.required && !values[f.key])
    .map((f) => f.key)

  const saveToFleet = async () => {
    if (!activeFleet) return
    const allTouched: Record<string, boolean> = {}
    for (const f of component.fields) allTouched[f.key] = true
    setTouched(allTouched)
    if (missingRequired.length > 0) return

    setSaveState('saving')
    setSaveError(null)
    try {
      const config = coerceFieldValues(component, values)
      const cleanRefs: Record<string, string> = {}
      if (certRefs.identity) cleanRefs.identity = certRefs.identity
      if (certRefs.ca) cleanRefs.ca = certRefs.ca
      if (existing) {
        await componentsApi.update(existing.id, {
          name: name || component.type,
          config,
          cert_refs: cleanRefs,
        })
      } else {
        await componentsApi.create({
          fleet_id: activeFleet.id,
          kind: kind === 'sources' ? 'source' : 'sink',
          name: name || component.type,
          component_type: component.type,
          config,
          cert_refs: cleanRefs,
        })
      }
      setSaveState('saved')
      onSaved?.()
      setTimeout(() => setSaveState('idle'), 2500)
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setSaveError(detail ?? 'Save failed — check your connection and retry')
      setSaveState('error')
      setTimeout(() => {
        setSaveState('idle')
        setSaveError(null)
      }, 4000)
    }
  }

  const copyYaml = async () => {
    try {
      await navigator.clipboard.writeText(yaml)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // clipboard unavailable
    }
  }

  const handleRawToggle = () => {
    if (!rawMode) {
      setRawYaml(generateYaml(kind, component, values, name || component.type))
    }
    setRawMode((m) => !m)
  }

  return (
    <div className="flex flex-col h-full border-l border-border bg-card overflow-hidden">
      <div className="flex items-start justify-between gap-3 px-5 py-4 border-b border-border flex-shrink-0">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h2 className="text-sm font-semibold text-foreground">{component.name}</h2>
            <CategoryBadge category={component.category} />
            {component.generated && <GeneratedBadge />}
          </div>
          <p className="text-xs text-muted-foreground mt-1 leading-relaxed">{component.description}</p>
          <p className="text-xs font-mono text-muted-foreground/50 mt-1">{component.type}</p>
        </div>
        <button
          onClick={onClose}
          className="text-muted-foreground hover:text-foreground transition-colors flex-shrink-0 mt-0.5"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="h-4 w-4">
            <path d="M18 6L6 18M6 6l12 12" strokeLinecap="round" />
          </svg>
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
        <div className="space-y-1.5">
          <label className="text-xs font-medium text-muted-foreground">
            Component name <span className="text-destructive">*</span>
          </label>
          <input
            type="text"
            className={inputCls}
            value={name}
            onChange={(e) => setName(e.target.value.replace(/[^a-z0-9_]/gi, '_').toLowerCase())}
            placeholder={component.type}
          />
          <p className="text-xs text-muted-foreground/60">Used as the YAML key (alphanumeric + underscore).</p>
        </div>

        {component.fields.map((field, idx) => {
          const isError = field.required && touched[field.key] && !values[field.key]
          const prevGroup = idx > 0 ? component.fields[idx - 1].group : undefined
          const showGroupHeader = field.group && field.group !== prevGroup
          const isTlsAnchor = field.key === firstTlsKey
          const managed =
            (IDENTITY_FIELDS.has(field.key) && Boolean(certRefs.identity)) ||
            (CA_FIELDS.has(field.key) && Boolean(certRefs.ca))
          if (managed && !isTlsAnchor) return null
          return (
            <div key={field.key} className="space-y-1.5">
              {showGroupHeader && (
                <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground/50 pt-3 mt-1 border-t border-border/50">
                  {field.group}
                </p>
              )}
              {isTlsAnchor && (
                <div className="space-y-2 pb-1">
                  <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground/50 pt-3 mt-1 border-t border-border/50">
                    TLS certificates
                  </p>
                  <CertSelect
                    label="Certificate (cert + key)"
                    hint="From the cert store — provides crt_file + key_file, delivered to hosts on deploy."
                    certs={certs.filter((c) => c.has_key)}
                    value={certRefs.identity ?? ''}
                    onChange={(id) => {
                      setCertRefs((p) => ({ ...p, identity: id || undefined }))
                      if (id)
                        setValues((v) => ({
                          ...v,
                          'tls.crt_file': '',
                          'tls.key_file': '',
                          'tls.key_pass': '',
                        }))
                    }}
                  />
                  <CertSelect
                    label="CA certificate (verify peer)"
                    hint="From the cert store — provides ca_file."
                    certs={certs}
                    value={certRefs.ca ?? ''}
                    onChange={(id) => {
                      setCertRefs((p) => ({ ...p, ca: id || undefined }))
                      if (id) setValues((v) => ({ ...v, 'tls.ca_file': '' }))
                    }}
                  />
                </div>
              )}
              {!managed && (
                <>
                  <label className="text-xs font-medium text-muted-foreground">
                    {field.label}
                    {field.required && <span className="text-destructive ml-1">*</span>}
                  </label>
                  <FieldInput
                    field={field}
                    value={values[field.key] ?? ''}
                    onChange={(v) => {
                      setValues((prev) => ({ ...prev, [field.key]: v }))
                      setTouched((prev) => ({ ...prev, [field.key]: true }))
                    }}
                    hasError={isError}
                  />
                  {isError ? (
                    <p className="text-xs text-destructive">Required</p>
                  ) : field.hint ? (
                    <p className="text-xs text-muted-foreground/60">{field.hint}</p>
                  ) : null}
                </>
              )}
            </div>
          )
        })}
      </div>

      <div className="border-t border-border flex-shrink-0">
        <div className="flex items-center justify-between px-5 py-2.5 border-b border-border/50">
          <span className="text-xs font-medium text-muted-foreground">Generated YAML</span>
          <div className="flex items-center gap-2">
            <button
              onClick={handleRawToggle}
              className={`text-xs px-2 py-0.5 rounded transition-colors ${
                rawMode ? 'bg-primary/15 text-primary' : 'text-muted-foreground hover:text-foreground'
              }`}
            >
              Raw
            </button>
            <button
              onClick={copyYaml}
              className="text-xs text-muted-foreground hover:text-foreground transition-colors px-2 py-0.5 rounded hover:bg-secondary"
            >
              {copied ? 'Copied!' : 'Copy'}
            </button>
          </div>
        </div>
        {rawMode ? (
          <textarea
            className="w-full bg-background text-xs font-mono text-foreground px-5 py-3 resize-none focus:outline-none"
            value={rawYaml}
            onChange={(e) => setRawYaml(e.target.value)}
            rows={10}
            spellCheck={false}
          />
        ) : (
          <pre className="px-5 py-3 text-xs font-mono text-foreground/80 overflow-x-auto max-h-56 overflow-y-auto leading-relaxed">
            {yaml}
          </pre>
        )}
      </div>

      {canEdit && (
        <div className="border-t border-border flex-shrink-0 px-5 py-3 space-y-2">
          {saveError && <p className="text-xs text-destructive">{saveError}</p>}
          <div className="flex items-center justify-between gap-3">
            <span className="text-xs text-muted-foreground truncate">
              {existing ? (
                <>
                  Editing <span className="text-foreground font-medium">{existing.name}</span> in{' '}
                  {activeFleet?.name}
                </>
              ) : activeFleet ? (
                <>
                  Save as {kind === 'sources' ? 'source' : 'sink'} in{' '}
                  <span className="text-foreground font-medium">{activeFleet.name}</span>
                </>
              ) : (
                'Select a fleet to save this component'
              )}
            </span>
            <button
              onClick={saveToFleet}
              disabled={!activeFleet || saveState === 'saving' || rawMode}
              title={rawMode ? 'Switch off Raw mode to save a guided component' : undefined}
              className="flex-shrink-0 bg-primary hover:bg-primary/90 text-primary-foreground text-xs font-medium px-3 py-1.5 rounded-lg transition-colors disabled:opacity-50"
            >
              {saveState === 'saving'
                ? 'Saving…'
                : saveState === 'saved'
                  ? 'Saved ✓'
                  : saveState === 'error'
                    ? 'Failed'
                    : existing
                      ? 'Update'
                      : 'Save to fleet'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
