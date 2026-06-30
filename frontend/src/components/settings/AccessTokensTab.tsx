// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

import { useCallback, useEffect, useState } from 'react'
import { tokensApi, type ApiTokenMeta } from '@/lib/api'

const inputCls =
  'bg-background border border-border rounded-lg px-3 py-1.5 text-sm text-foreground placeholder-muted-foreground focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary transition-colors'

const EXPIRY_OPTIONS: { label: string; days: number | null }[] = [
  { label: '30 days', days: 30 },
  { label: '90 days', days: 90 },
  { label: '1 year', days: 365 },
  { label: 'No expiry', days: null },
]

function fmt(ts: string | null): string {
  if (!ts) return '—'
  return new Date(ts).toLocaleString()
}

export default function AccessTokensTab() {
  const [tokens, setTokens] = useState<ApiTokenMeta[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [name, setName] = useState('')
  const [expiryDays, setExpiryDays] = useState<number | null>(90)
  const [creating, setCreating] = useState(false)
  // The freshly-created secret, shown exactly once.
  const [newToken, setNewToken] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setTokens((await tokensApi.list()).data)
    } catch {
      setError('Failed to load tokens.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const create = async () => {
    if (!name.trim()) return
    setCreating(true)
    setError(null)
    try {
      const res = await tokensApi.create(name.trim(), expiryDays)
      setNewToken(res.data.token)
      setName('')
      await load()
    } catch {
      setError('Failed to create token.')
    } finally {
      setCreating(false)
    }
  }

  const revoke = async (t: ApiTokenMeta) => {
    if (!confirm(`Revoke "${t.name}"? Any client using it will immediately lose access.`)) return
    try {
      await tokensApi.revoke(t.id)
      await load()
    } catch {
      setError('Failed to revoke token.')
    }
  }

  const copy = async () => {
    if (!newToken) return
    await navigator.clipboard.writeText(newToken)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="space-y-6 max-w-2xl">
      <div>
        <h3 className="text-sm font-medium text-foreground mb-1">Personal access tokens</h3>
        <p className="text-xs text-muted-foreground">
          Use a token for programmatic API access (CI, scripts, automation). It acts as you
          and inherits your role. Send it as <code>Authorization: Bearer &lt;token&gt;</code>.
          Token management itself requires an interactive login, not a token.
        </p>
      </div>

      {/* one-time secret reveal */}
      {newToken && (
        <div className="bg-primary/5 border border-primary/30 rounded-lg p-4 space-y-2">
          <p className="text-xs font-medium text-foreground">
            Copy your token now — you won&apos;t be able to see it again.
          </p>
          <div className="flex items-center gap-2">
            <code className="flex-1 bg-background border border-border rounded-lg px-3 py-2 text-xs text-foreground break-all">
              {newToken}
            </code>
            <button
              onClick={() => void copy()}
              className="shrink-0 bg-primary hover:bg-primary/90 text-primary-foreground text-xs font-medium px-3 py-2 rounded-lg transition-colors"
            >
              {copied ? 'Copied' : 'Copy'}
            </button>
          </div>
          <button
            onClick={() => setNewToken(null)}
            className="text-xs text-muted-foreground hover:text-foreground transition-colors"
          >
            Done
          </button>
        </div>
      )}

      {/* create */}
      <div className="flex items-end gap-2">
        <div className="flex-1">
          <label className="block text-xs font-medium text-muted-foreground mb-1">Token name</label>
          <input
            className={`${inputCls} w-full py-2`}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. ci-pipeline"
            maxLength={80}
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-muted-foreground mb-1">Expires</label>
          <select
            className={`${inputCls} py-2`}
            value={expiryDays === null ? 'null' : String(expiryDays)}
            onChange={(e) => setExpiryDays(e.target.value === 'null' ? null : Number(e.target.value))}
          >
            {EXPIRY_OPTIONS.map((o) => (
              <option key={o.label} value={o.days === null ? 'null' : String(o.days)}>
                {o.label}
              </option>
            ))}
          </select>
        </div>
        <button
          onClick={() => void create()}
          disabled={creating || !name.trim()}
          className="bg-primary hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed text-primary-foreground text-sm font-medium px-4 py-2 rounded-lg transition-colors"
        >
          {creating ? 'Creating…' : 'Create token'}
        </button>
      </div>

      {error && <p className="text-xs text-destructive">{error}</p>}

      {/* list */}
      {loading ? (
        <p className="text-xs text-muted-foreground">Loading…</p>
      ) : tokens.length === 0 ? (
        <p className="text-xs text-muted-foreground">No tokens yet.</p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-muted-foreground border-b border-border">
              <th className="py-2 font-medium">Name</th>
              <th className="py-2 font-medium">Created</th>
              <th className="py-2 font-medium">Last used</th>
              <th className="py-2 font-medium">Expires</th>
              <th className="py-2"></th>
            </tr>
          </thead>
          <tbody>
            {tokens.map((t) => (
              <tr key={t.id} className="border-b border-border/50">
                <td className="py-2.5 text-foreground">
                  {t.name}
                  <span className="ml-2 text-[10px] text-muted-foreground font-mono">
                    vf_pat_{t.token_id}…
                  </span>
                </td>
                <td className="py-2.5 text-muted-foreground text-xs">{fmt(t.created_at)}</td>
                <td className="py-2.5 text-muted-foreground text-xs">{fmt(t.last_used_at)}</td>
                <td className="py-2.5 text-muted-foreground text-xs">{fmt(t.expires_at)}</td>
                <td className="py-2.5 text-right">
                  <button
                    onClick={() => void revoke(t)}
                    className="text-xs text-muted-foreground hover:text-destructive transition-colors"
                  >
                    Revoke
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
