// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

import { useCallback, useEffect, useMemo, useState } from 'react'
import { componentsApi, routesApi, transformStagesApi } from '@/lib/api'
import type { Component, Route, TransformStage } from '@/lib/types'
import { useFleet } from '@/lib/fleet'
import { useAuth } from '@/lib/auth'
import { RouteListItem } from '@/components/routes/RouteEditor'
import { btnPrimary } from '@/lib/ui'

// Fleet-scoped transform list — remap stages AND route transforms in one place,
// each tagged by type. This is the browse/find surface (like the Catalog inventory
// is for sources/sinks); the actual editing happens in the Flow node drawer, so a
// row opens that node on the canvas (`/flow?node=<id>`).
const openInFlow = (id: string) => window.location.assign(`/flow?node=${encodeURIComponent(id)}`)

function RemapRow({
  stage,
  inputsLabel,
  onOpen,
}: {
  stage: TransformStage
  inputsLabel: string
  onOpen: () => void
}) {
  return (
    <button
      onClick={onOpen}
      className="w-full text-left rounded-xl border border-border bg-card hover:border-border/80 px-3 py-2.5 transition-colors"
    >
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-sm font-medium text-foreground">{stage.name}</span>
        <span className="text-[10px] uppercase tracking-wide font-semibold text-sky-500/80 bg-sky-500/10 px-1.5 py-0.5 rounded">remap</span>
        <span className="ml-auto text-[11px] text-muted-foreground/60">Open in Flow →</span>
      </div>
      <div className="text-xs text-muted-foreground mt-0.5 truncate">{inputsLabel} → remap</div>
    </button>
  )
}

export default function FleetTransforms() {
  const { activeFleet } = useFleet()
  const { user } = useAuth()
  const canEdit = user?.role === 'admin' || user?.role === 'editor'

  const [stages, setStages] = useState<TransformStage[]>([])
  const [routes, setRoutes] = useState<Route[]>([])
  const [components, setComponents] = useState<Component[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    if (!activeFleet) {
      setLoading(false)
      return
    }
    setLoading(true)
    setError(null)
    Promise.all([
      transformStagesApi.list(activeFleet.id).then((r) => setStages(r.data.stages)),
      routesApi.list(activeFleet.id).then((r) => setRoutes(r.data.routes ?? [])).catch(() => setRoutes([])),
      componentsApi.list({ fleet_id: activeFleet.id }).then((r) => setComponents(r.data.components)),
    ])
      .catch(() => setError('Failed to load transforms'))
      .finally(() => setLoading(false))
  }, [activeFleet])

  useEffect(() => { load() }, [load])

  const nameOf = useMemo(() => {
    const m = new Map<string, string>([
      ...components.map((c) => [c.id, c.name] as const),
      ...stages.map((s) => [s.id, s.name] as const),
    ])
    return (id: string) => m.get(id) ?? id
  }, [components, stages])

  const toggleExpand = (id: string) =>
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  if (!activeFleet) {
    return (
      <div className="flex-1 flex items-center justify-center text-sm text-muted-foreground">
        Select a fleet to manage its transforms.
      </div>
    )
  }

  const q = search.trim().toLowerCase()
  const matchStage = (s: TransformStage) =>
    !q || s.name.toLowerCase().includes(q) || s.inputs.map(nameOf).join(' ').toLowerCase().includes(q)
  const matchRoute = (r: Route) =>
    !q ||
    [r.name, r.description ?? '', ...r.branches.map((b) => `${b.name} ${b.condition}`), ...r.source_ids.map(nameOf)]
      .join(' ')
      .toLowerCase()
      .includes(q)

  const visibleStages = stages.filter(matchStage)
  const visibleRoutes = routes.filter(matchRoute)
  const empty = visibleStages.length === 0 && visibleRoutes.length === 0

  return (
    <div className="flex flex-1 min-h-0">
      <div className="flex-1 min-w-0 flex flex-col overflow-hidden">
        <div className="flex-shrink-0 px-4 pt-4 pb-2 flex items-center gap-3">
          <input
            className="flex-1 max-w-md bg-background border border-border rounded-lg px-3 py-1.5 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
            placeholder="Search transforms — name, condition, input…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          {canEdit && (
            <button onClick={() => window.location.assign('/flow')} className={btnPrimary}>
              Build in Flow →
            </button>
          )}
        </div>

        <p className="px-4 pb-2 text-xs text-muted-foreground/60">
          Vector transforms in <span className="text-foreground font-medium">{activeFleet.name}</span> — a{' '}
          <span className="text-sky-500/80">remap</span> reshapes events (VRL); a{' '}
          <span className="text-primary">route</span> splits them by condition. Click one to add, wire, and edit it
          on the <span className="text-foreground">Flow</span> canvas.
        </p>

        <div className="flex-1 overflow-y-auto px-4 pb-4 space-y-2">
          {loading ? (
            [...Array(3)].map((_, i) => <div key={i} className="h-16 bg-card border border-border rounded-xl animate-pulse" />)
          ) : error ? (
            <p className="text-sm text-destructive py-6">{error}</p>
          ) : empty ? (
            <div className="flex flex-col items-center justify-center py-20 gap-3 text-center">
              <p className="text-sm text-muted-foreground">
                {search ? 'No transforms match your search.' : 'No transforms in this fleet yet.'}
              </p>
              {canEdit && !search && (
                <button onClick={() => window.location.assign('/flow')} className={btnPrimary}>
                  Build in Flow →
                </button>
              )}
            </div>
          ) : (
            <>
              {visibleStages.map((s) => (
                <RemapRow
                  key={s.id}
                  stage={s}
                  inputsLabel={s.inputs.length ? s.inputs.map(nameOf).join(', ') : 'no inputs'}
                  onOpen={() => openInFlow(s.id)}
                />
              ))}
              {visibleRoutes.map((r) => (
                <RouteListItem
                  key={r.id}
                  route={r}
                  fleetName={activeFleet.name}
                  showFleet={false}
                  active={false}
                  expanded={expanded.has(r.id)}
                  onSelect={() => openInFlow(r.id)}
                  onToggle={() => toggleExpand(r.id)}
                  nameOf={nameOf}
                />
              ))}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
