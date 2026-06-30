// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

import { useEffect, useState } from 'react'
import { certsApi } from '@/lib/api'

// ─── Types ────────────────────────────────────────────────────────────────────

interface CertMeta {
  fingerprint: string | null
  cn: string | null
  sans: string[]
  eku: string[]
  expires_at: string | null
  expires_in_days: number | null
}

interface CertRecord extends CertMeta {
  id: string
  label: string
  cert_type: string
  has_key: boolean
  ca_chain_pem: string | null
  notes: string | null
  created_at: string
}

// ─── Expiry badge ─────────────────────────────────────────────────────────────

function ExpiryBadge({ days }: { days: number | null }) {
  if (days === null) return null
  if (days <= 0)
    return <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-destructive/15 text-destructive">EXPIRED</span>
  if (days <= 7)
    return <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-destructive/15 text-destructive">Expires in {days}d</span>
  if (days <= 30)
    return <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-amber-400/15 text-amber-400">Expires in {days}d</span>
  return <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-emerald-400/10 text-emerald-400">Valid · {days}d</span>
}

// ─── Parsed preview ───────────────────────────────────────────────────────────

function ParsedPreview({ meta }: { meta: CertMeta }) {
  return (
    <div className="rounded-lg border border-border bg-background/40 p-3 space-y-1.5 text-xs">
      <div className="flex items-center gap-2">
        <span className="text-muted-foreground w-20 flex-shrink-0">CN</span>
        <span className="text-foreground font-mono">{meta.cn ?? '—'}</span>
      </div>
      {meta.sans.length > 0 && (
        <div className="flex items-start gap-2">
          <span className="text-muted-foreground w-20 flex-shrink-0">SANs</span>
          <span className="text-foreground font-mono">{meta.sans.join(', ')}</span>
        </div>
      )}
      {meta.eku.length > 0 && (
        <div className="flex items-start gap-2">
          <span className="text-muted-foreground w-20 flex-shrink-0">Key Usage</span>
          <span className="text-foreground">{meta.eku.join(', ')}</span>
        </div>
      )}
      <div className="flex items-center gap-2">
        <span className="text-muted-foreground w-20 flex-shrink-0">Expires</span>
        <span className="text-foreground">
          {meta.expires_at ? new Date(meta.expires_at).toLocaleDateString() : '—'}
          {' '}<ExpiryBadge days={meta.expires_in_days} />
        </span>
      </div>
      {meta.fingerprint && (
        <div className="flex items-start gap-2">
          <span className="text-muted-foreground w-20 flex-shrink-0">SHA-256</span>
          <span className="text-foreground/60 font-mono text-[10px] break-all leading-relaxed">
            {meta.fingerprint}
          </span>
        </div>
      )}
    </div>
  )
}

// ─── Upload form ──────────────────────────────────────────────────────────────

const inputCls =
  'w-full bg-background border border-border rounded-lg px-3 py-2 text-sm text-foreground ' +
  'placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary focus:border-primary'

function UploadForm({ onDone }: { onDone: () => void }) {
  const [label, setLabel] = useState('')
  const [certType, setCertType] = useState('server')
  const [certPem, setCertPem] = useState('')
  const [keyPem, setKeyPem] = useState('')
  const [passphrase, setPassphrase] = useState('')
  const [caChainPem, setCaChainPem] = useState('')
  const [notes, setNotes] = useState('')
  const [parsed, setParsed] = useState<CertMeta | null>(null)
  const [parseError, setParseError] = useState<string | null>(null)
  const [parsing, setParsing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  const resetParsed = () => { setParsed(null); setParseError(null) }

  const handleParse = async () => {
    if (!certPem.trim()) return
    setParsing(true)
    setParseError(null)
    setParsed(null)
    try {
      const r = await certsApi.parse({
        cert_pem: certPem,
        key_pem: keyPem || undefined,
        passphrase: passphrase || undefined,
      })
      setParsed(r.data)
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setParseError(detail ?? 'Invalid certificate or key')
    } finally {
      setParsing(false)
    }
  }

  const handleSave = async () => {
    if (!label.trim() || !certPem.trim() || !parsed) return
    setSaving(true)
    setSaveError(null)
    try {
      await certsApi.upload({
        label,
        cert_type: certType,
        cert_pem: certPem,
        key_pem: keyPem || undefined,
        passphrase: passphrase || undefined,
        ca_chain_pem: caChainPem || undefined,
        notes: notes || undefined,
      })
      onDone()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setSaveError(detail ?? 'Upload failed')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="border border-border rounded-xl p-5 bg-card space-y-4">
      <h3 className="text-sm font-medium text-foreground">Upload certificate</h3>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-xs font-medium text-muted-foreground mb-1">Label</label>
          <input
            className={inputCls}
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="Production TLS cert"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-muted-foreground mb-1">Type</label>
          <select
            className="w-full bg-background border border-border rounded-lg px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
            value={certType}
            onChange={(e) => setCertType(e.target.value)}
          >
            <option value="server">Server (TLS termination)</option>
            <option value="ca">CA / Root cert</option>
            <option value="client">Client cert (mTLS)</option>
          </select>
        </div>
      </div>

      <div>
        <label className="block text-xs font-medium text-muted-foreground mb-1">
          Certificate (PEM)
        </label>
        <textarea
          className={`${inputCls} font-mono text-xs leading-relaxed resize-y min-h-[100px]`}
          value={certPem}
          onChange={(e) => { setCertPem(e.target.value); resetParsed() }}
          placeholder={'-----BEGIN CERTIFICATE-----\nMIICxxx...\n-----END CERTIFICATE-----'}
          rows={5}
        />
      </div>

      {certType !== 'ca' && (
        <>
          <div>
            <label className="block text-xs font-medium text-muted-foreground mb-1">
              Private key (PEM)
            </label>
            <textarea
              className={`${inputCls} font-mono text-xs leading-relaxed resize-y min-h-[80px]`}
              value={keyPem}
              onChange={(e) => { setKeyPem(e.target.value); resetParsed() }}
              placeholder={'-----BEGIN [PRIVATE KEY TYPE]-----\nMIIExxx...\n-----END [PRIVATE KEY TYPE]-----'}
              rows={4}
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-muted-foreground mb-1">
              Key passphrase <span className="text-muted-foreground/50">(if encrypted)</span>
            </label>
            <input
              type="password"
              className={`${inputCls} font-mono`}
              value={passphrase}
              onChange={(e) => { setPassphrase(e.target.value); resetParsed() }}
              placeholder="••••••••"
              autoComplete="new-password"
            />
          </div>
        </>
      )}

      <div>
        <label className="block text-xs font-medium text-muted-foreground mb-1">
          CA / intermediate chain (PEM) <span className="text-muted-foreground/50">(optional)</span>
        </label>
        <textarea
          className={`${inputCls} font-mono text-xs leading-relaxed resize-y`}
          value={caChainPem}
          onChange={(e) => setCaChainPem(e.target.value)}
          placeholder={'-----BEGIN CERTIFICATE-----\n(intermediate CA)\n-----END CERTIFICATE-----'}
          rows={3}
        />
        <p className="text-[11px] text-muted-foreground/60 mt-1">
          Include the full chain minus the leaf cert. Used when applying this cert for TLS termination.
        </p>
      </div>

      <div>
        <label className="block text-xs font-medium text-muted-foreground mb-1">
          Notes <span className="text-muted-foreground/50">(optional)</span>
        </label>
        <textarea
          className={`${inputCls} resize-y`}
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="Renewed Q1 2026 · used on prod load balancer"
          rows={2}
        />
      </div>

      {parseError && <p className="text-xs text-destructive">{parseError}</p>}

      {parsed && (
        <div className="space-y-2">
          <p className="text-xs font-medium text-emerald-400">✓ Certificate validated</p>
          <ParsedPreview meta={parsed} />
        </div>
      )}

      {saveError && <p className="text-xs text-destructive">{saveError}</p>}

      <div className="flex items-center gap-2">
        {!parsed ? (
          <button
            onClick={() => { void handleParse() }}
            disabled={parsing || !certPem.trim()}
            className="bg-secondary hover:bg-secondary/80 text-foreground font-medium text-sm px-4 py-2 rounded-lg transition-colors disabled:opacity-50"
          >
            {parsing ? 'Validating…' : 'Validate'}
          </button>
        ) : (
          <button
            onClick={() => { void handleSave() }}
            disabled={saving || !label.trim()}
            className="bg-primary hover:bg-primary/90 text-primary-foreground font-medium text-sm px-4 py-2 rounded-lg transition-colors disabled:opacity-50"
          >
            {saving ? 'Saving…' : 'Save certificate'}
          </button>
        )}
        <button
          onClick={onDone}
          className="text-sm text-muted-foreground hover:text-foreground transition-colors px-2"
        >
          Cancel
        </button>
      </div>
    </div>
  )
}

// ─── Certificate row ──────────────────────────────────────────────────────────

function CertRow({
  cert,
  onDelete,
}: {
  cert: CertRecord
  onDelete: () => void
}) {
  const [expanded, setExpanded] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [deleting, setDeleting] = useState(false)

  const handleDelete = async () => {
    setDeleting(true)
    try {
      await certsApi.delete(cert.id)
      onDelete()
    } catch {
      setDeleting(false)
      setConfirming(false)
    }
  }

  const typeLabel = cert.cert_type === 'ca' ? 'CA' : cert.cert_type === 'client' ? 'Client' : 'Server'

  return (
    <div className="border-b border-border last:border-0">
      <div className="flex items-center gap-3 px-4 py-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-medium text-foreground">{cert.label}</span>
            <span className="text-xs text-muted-foreground/60 bg-secondary px-1.5 py-0.5 rounded">
              {typeLabel}
            </span>
            {cert.has_key && (
              <span className="text-xs text-muted-foreground/60 bg-secondary px-1.5 py-0.5 rounded">
                + key
              </span>
            )}
            {cert.ca_chain_pem && (
              <span className="text-xs text-muted-foreground/60 bg-secondary px-1.5 py-0.5 rounded">
                + chain
              </span>
            )}
            <ExpiryBadge days={cert.expires_in_days} />
          </div>
          <p className="text-xs text-muted-foreground/70 font-mono mt-0.5">
            {cert.cn ?? cert.fingerprint?.slice(0, 29) ?? '—'}
          </p>
          {cert.notes && (
            <p className="text-xs text-muted-foreground/60 mt-0.5 italic">{cert.notes}</p>
          )}
        </div>

        <div className="flex items-center gap-2 flex-shrink-0">
          <button
            onClick={() => setExpanded((o) => !o)}
            className="text-xs text-muted-foreground hover:text-foreground transition-colors"
          >
            {expanded ? 'Hide' : 'Details'}
          </button>
          {confirming ? (
            <>
              <button
                onClick={() => { void handleDelete() }}
                disabled={deleting}
                className="text-xs text-destructive hover:text-destructive/80 font-medium"
              >
                {deleting ? 'Deleting…' : 'Confirm delete'}
              </button>
              <button
                onClick={() => setConfirming(false)}
                className="text-xs text-muted-foreground hover:text-foreground"
              >
                Cancel
              </button>
            </>
          ) : (
            <button
              onClick={() => setConfirming(true)}
              className="text-xs text-muted-foreground/60 hover:text-destructive transition-colors"
            >
              Delete
            </button>
          )}
        </div>
      </div>

      {expanded && (
        <div className="px-4 pb-3 space-y-3">
          <ParsedPreview meta={cert} />
          {cert.eku.length > 0 && (
            <div className="flex gap-1.5 flex-wrap">
              {cert.eku.map((e) => (
                <span key={e} className="text-xs px-2 py-0.5 rounded bg-primary/10 text-primary">
                  {e}
                </span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ─── Tab ──────────────────────────────────────────────────────────────────────

export default function CertificatesTab() {
  const [certs, setCerts] = useState<CertRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [showUpload, setShowUpload] = useState(false)

  const load = () => {
    setLoading(true)
    certsApi.list()
      .then((r) => { setCerts(r.data); setLoadError(null) })
      .catch(() => setLoadError('Failed to load certificates'))
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [])

  const serverCerts = certs.filter((c) => c.cert_type === 'server')
  const caCerts     = certs.filter((c) => c.cert_type === 'ca')
  const clientCerts = certs.filter((c) => c.cert_type === 'client')

  return (
    <div className="space-y-5 max-w-2xl">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs text-muted-foreground">
            Upload PEM certificates once — reference them from server TLS config and per-instance CA verification.
            Private keys are encrypted at rest.
          </p>
        </div>
        <button
          onClick={() => setShowUpload((o) => !o)}
          className="flex-shrink-0 bg-primary hover:bg-primary/90 text-primary-foreground font-medium text-sm px-4 py-2 rounded-lg transition-colors"
        >
          {showUpload ? 'Cancel' : '+ Upload cert'}
        </button>
      </div>

      {showUpload && (
        <UploadForm onDone={() => { setShowUpload(false); load() }} />
      )}

      {loadError && <p className="text-xs text-destructive">{loadError}</p>}

      {loading ? (
        <div className="space-y-2">
          {[...Array(2)].map((_, i) => (
            <div key={i} className="h-14 bg-card border border-border rounded-xl animate-pulse" />
          ))}
        </div>
      ) : certs.length === 0 ? (
        <div className="border border-dashed border-border rounded-xl py-12 text-center">
          <p className="text-sm text-muted-foreground">No certificates uploaded yet.</p>
          <p className="text-xs text-muted-foreground/60 mt-1">
            Upload a server cert for TLS termination, or a CA cert for instance verification.
          </p>
        </div>
      ) : (
        <div className="space-y-4">
          {[
            { label: 'Server certificates', items: serverCerts },
            { label: 'CA / Root certificates', items: caCerts },
            { label: 'Client certificates', items: clientCerts },
          ]
            .filter((g) => g.items.length > 0)
            .map((g) => (
              <div key={g.label}>
                <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
                  {g.label}
                </h3>
                <div className="border border-border rounded-xl overflow-hidden bg-card">
                  {g.items.map((c) => (
                    <CertRow
                      key={c.id}
                      cert={c}
                      onDelete={load}
                    />
                  ))}
                </div>
              </div>
            ))}
        </div>
      )}
    </div>
  )
}
