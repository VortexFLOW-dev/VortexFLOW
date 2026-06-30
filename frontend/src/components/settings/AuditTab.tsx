// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

import { useCallback, useEffect, useState } from 'react'
import { auditApi, type AuditEntry, type AuditQuery } from '@/lib/api'

const PAGE = 50

const inputCls =
  'bg-background border border-border rounded-lg px-3 py-1.5 text-xs text-foreground placeholder-muted-foreground focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary transition-colors'

// Colour the action chip by category so the log scans quickly.
function actionTone(action: string): string {
  if (action.startsWith('auth.login_failed') || action.includes('locked'))
    return 'bg-destructive/10 text-destructive'
  if (action.startsWith('auth.')) return 'bg-amber-400/10 text-amber-500'
  if (action.endsWith('.delete')) return 'bg-destructive/10 text-destructive'
  if (action.startsWith('fleet.deploy')) return 'bg-primary/10 text-primary'
  return 'bg-secondary text-muted-foreground'
}

export default function AuditTab() {
  const [entries, setEntries] = useState<AuditEntry[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(0)
  const [action, setAction] = useState('')
  const [q, setQ] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const filters = useCallback(
    (): AuditQuery => ({
      action: action || undefined,
      q: q || undefined,
    }),
    [action, q],
  )

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await auditApi.list({ ...filters(), limit: PAGE, offset: page * PAGE })
      setEntries(res.data.entries)
      setTotal(res.data.total)
    } catch {
      setError('Failed to load the audit log.')
    } finally {
      setLoading(false)
    }
  }, [filters, page])

  useEffect(() => {
    load()
  }, [load])

  const onExport = async () => {
    try {
      const res = await auditApi.exportCsv(filters())
      const url = URL.createObjectURL(res.data as Blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `audit-${new Date().toISOString().slice(0, 10)}.csv`
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      setError('Export failed.')
    }
  }

  const fmt = (iso: string | null) =>
    iso ? new Date(iso).toLocaleString() : '—'

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-foreground">Audit log</h2>
          <p className="text-xs text-muted-foreground mt-0.5">
            Security- and config-relevant actions: who did what, from where, and when.
          </p>
        </div>
        <button
          onClick={onExport}
          className="flex-shrink-0 text-xs px-3 py-1.5 rounded-lg border border-border text-foreground hover:bg-secondary transition-colors"
        >
          Export CSV
        </button>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2">
        <input
          className={inputCls}
          placeholder="Filter by action (e.g. fleet.deploy)"
          value={action}
          onChange={(e) => {
            setPage(0)
            setAction(e.target.value.trim())
          }}
        />
        <input
          className={`${inputCls} flex-1 min-w-[180px]`}
          placeholder="Search email or detail…"
          value={q}
          onChange={(e) => {
            setPage(0)
            setQ(e.target.value)
          }}
        />
      </div>

      {error && <p className="text-xs text-destructive">{error}</p>}

      {/* Table */}
      <div className="border border-border rounded-lg overflow-hidden">
        <table className="w-full text-xs">
          <thead className="bg-secondary/50 text-muted-foreground">
            <tr>
              <th className="text-left font-medium px-3 py-2">Time</th>
              <th className="text-left font-medium px-3 py-2">User</th>
              <th className="text-left font-medium px-3 py-2">Action</th>
              <th className="text-left font-medium px-3 py-2">Detail</th>
              <th className="text-left font-medium px-3 py-2">IP</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {loading ? (
              <tr>
                <td colSpan={5} className="px-3 py-6 text-center text-muted-foreground">
                  Loading…
                </td>
              </tr>
            ) : entries.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-3 py-6 text-center text-muted-foreground">
                  No matching audit entries.
                </td>
              </tr>
            ) : (
              entries.map((e) => (
                <tr key={e.id} className="hover:bg-secondary/30">
                  <td className="px-3 py-2 whitespace-nowrap text-muted-foreground">
                    {fmt(e.created_at)}
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap text-foreground">
                    {e.user_email ?? '—'}
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap">
                    <span
                      className={`inline-block rounded px-1.5 py-0.5 font-mono text-[11px] ${actionTone(e.action)}`}
                    >
                      {e.action}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-muted-foreground">{e.detail ?? ''}</td>
                  <td className="px-3 py-2 whitespace-nowrap font-mono text-muted-foreground/70">
                    {e.ip_address ?? '—'}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <span>
          {total === 0
            ? '0 entries'
            : `${page * PAGE + 1}–${Math.min((page + 1) * PAGE, total)} of ${total}`}
        </span>
        <div className="flex gap-2">
          <button
            disabled={page === 0}
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            className="px-2.5 py-1 rounded border border-border disabled:opacity-40 hover:bg-secondary transition-colors"
          >
            Prev
          </button>
          <button
            disabled={(page + 1) * PAGE >= total}
            onClick={() => setPage((p) => p + 1)}
            className="px-2.5 py-1 rounded border border-border disabled:opacity-40 hover:bg-secondary transition-colors"
          >
            Next
          </button>
        </div>
      </div>
    </div>
  )
}
