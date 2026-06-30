// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

import { useState, useEffect, useCallback } from 'react'
import type { CatalogComponent } from '@/lib/catalog'
import { useCatalog } from '@/lib/useCatalog'
import { componentsApi, routesApi } from '@/lib/api'
import { deleteGuarded } from '@/lib/deleteGuard'
import type { Component, Route } from '@/lib/types'
import { useFleet } from '@/lib/fleet'
import { useAuth } from '@/lib/auth'
import {
  ComponentConfigForm,
  CategoryBadge,
  GeneratedBadge,
} from '@/components/catalog/ComponentConfigForm'


// ─── Component card ───────────────────────────────────────────────────────────
function ComponentCard({
  component,
  active,
  onClick,
  usage,
  onUsageClick,
  fleetName,
}: {
  component: CatalogComponent
  active: boolean
  onClick: () => void
  usage: number
  onUsageClick?: () => void
  fleetName?: string
}) {
  return (
    <button
      onClick={onClick}
      className={`text-left w-full p-4 rounded-xl border transition-all ${
        active
          ? 'border-primary/50 bg-primary/5 ring-1 ring-primary/30'
          : usage > 0
            ? 'border-primary/25 bg-card hover:border-primary/40'
            : 'border-border bg-card hover:border-border/80 hover:bg-secondary/30'
      }`}
    >
      <div className="flex items-start justify-between gap-2 mb-2">
        <span className="text-sm font-medium text-foreground leading-tight">{component.name}</span>
        <div className="flex items-center gap-1 flex-shrink-0">
          {component.generated && <GeneratedBadge />}
          <CategoryBadge category={component.category} />
        </div>
      </div>
      <p className="text-xs text-muted-foreground leading-relaxed line-clamp-2">
        {component.description}
      </p>
      <div className="flex items-center justify-between gap-2 mt-2">
        <span className="text-xs text-muted-foreground/50 font-mono">{component.type}</span>
        {usage > 0 && (
          <span
            role="button"
            tabIndex={0}
            onClick={(e) => { e.stopPropagation(); onUsageClick?.() }}
            onKeyDown={(e) => { if (e.key === 'Enter') { e.stopPropagation(); onUsageClick?.() } }}
            title={`${usage} in ${fleetName ?? 'this fleet'} — view`}
            className="flex-shrink-0 text-xs text-primary bg-primary/10 border border-primary/20 px-1.5 py-0.5 rounded hover:bg-primary/20 transition-colors cursor-pointer"
          >
            {usage} in use
          </span>
        )}
      </div>
    </button>
  )
}


// ─── Fleet inventory (saved components, In/Out, with route usage) ─────────────
function InventoryRow({
  c, usedBy, canEdit, onEdit, onDelete, deleting,
}: {
  c: Component
  usedBy: string[]
  canEdit: boolean
  onEdit: (c: Component) => void
  onDelete: (id: string) => void
  deleting: boolean
}) {
  return (
    <div className="bg-card border border-border rounded-xl px-4 py-3 flex items-center gap-3">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm font-medium text-foreground">{c.name}</span>
          <span className="text-xs font-mono text-muted-foreground/60">{c.component_type}</span>
          {usedBy.length > 0 ? (
            <span
              className="text-xs text-primary bg-primary/10 border border-primary/20 px-1.5 py-0.5 rounded"
              title={usedBy.join(', ')}
            >
              {c.kind === 'source' ? 'feeds' : 'fed by'} {usedBy.length} route{usedBy.length !== 1 ? 's' : ''}
            </span>
          ) : (
            <span className="text-xs text-muted-foreground/50 bg-secondary/50 px-1.5 py-0.5 rounded">
              not in any route
            </span>
          )}
        </div>
        <p className="text-xs text-muted-foreground mt-0.5 truncate">
          {Object.keys(c.config as object).length} config key{Object.keys(c.config as object).length !== 1 ? 's' : ''}
          {usedBy.length > 0 && <span className="text-muted-foreground/50"> · {usedBy.join(', ')}</span>}
        </p>
      </div>
      {canEdit && (
        <div className="flex items-center gap-1 flex-shrink-0">
          <button
            onClick={() => onEdit(c)}
            className="text-xs text-muted-foreground hover:text-foreground transition-colors px-2 py-1"
          >
            Edit
          </button>
          <button
            onClick={() => onDelete(c.id)}
            disabled={deleting}
            className="text-xs text-destructive/60 hover:text-destructive transition-colors px-2 py-1 disabled:opacity-40"
          >
            {deleting ? '…' : 'Delete'}
          </button>
        </div>
      )}
    </div>
  )
}

function Inventory({
  components, routeUsage, loading, canEdit, fleetName, hasFleet, onEdit, onDelete, deletingId,
}: {
  components: Component[]
  routeUsage: Record<string, string[]>
  loading: boolean
  canEdit: boolean
  fleetName?: string
  hasFleet: boolean
  onEdit: (c: Component) => void
  onDelete: (id: string) => void
  deletingId: string | null
}) {
  if (!hasFleet) {
    return (
      <div className="flex items-center justify-center py-24 text-sm text-muted-foreground">
        Select a fleet to view its components.
      </div>
    )
  }
  if (loading) {
    return (
      <div className="p-4 space-y-3">
        {[...Array(3)].map((_, i) => (
          <div key={i} className="bg-card border border-border rounded-xl h-16 animate-pulse" />
        ))}
      </div>
    )
  }
  if (components.length === 0) {
    return (
      <div className="flex items-center justify-center py-24 text-sm text-muted-foreground">
        No components in <span className="font-medium text-foreground mx-1">{fleetName}</span> yet — add one from Sources or Sinks.
      </div>
    )
  }

  const sources = components.filter((c) => c.kind === 'source')
  const sinks = components.filter((c) => c.kind === 'sink')

  const section = (title: string, items: Component[]) =>
    items.length > 0 && (
      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{title}</h3>
          <span className="text-xs text-muted-foreground/60">{items.length}</span>
        </div>
        {items.map((c) => (
          <InventoryRow
            key={c.id}
            c={c}
            usedBy={routeUsage[c.id] ?? []}
            canEdit={canEdit}
            onEdit={onEdit}
            onDelete={onDelete}
            deleting={deletingId === c.id}
          />
        ))}
      </div>
    )

  return (
    <div className="p-4 space-y-5">
      {section('Sources', sources)}
      {section('Sinks', sinks)}
    </div>
  )
}

// ─── Page ─────────────────────────────────────────────────────────────────────
export default function Catalog() {
  const { activeFleet } = useFleet()
  const { user } = useAuth()
  const canEdit = user?.role === 'admin' || user?.role === 'editor'
  const isAdmin = user?.role === 'admin'
  const { sources, sinks, vectorVersion, live, refresh } = useCatalog()
  const [refreshing, setRefreshing] = useState(false)
  const [tab, setTab] = useState<'sources' | 'sinks' | 'saved'>('sources')
  const [search, setSearch] = useState('')
  const [activeCategory, setActiveCategory] = useState<string | null>(null)
  const [selected, setSelected] = useState<CatalogComponent | null>(null)
  const [editing, setEditing] = useState<Component | null>(null)
  const [panelWide, setPanelWide] = useState(false) // expand the config panel to work

  // Active-fleet inventory + routes — drives usage badges and the In/Out view.
  const [fleetComponents, setFleetComponents] = useState<Component[]>([])
  const [routes, setRoutes] = useState<Route[]>([])
  const [fleetLoading, setFleetLoading] = useState(true)
  const [deletingId, setDeletingId] = useState<string | null>(null)

  const loadFleet = useCallback(() => {
    if (!activeFleet) { setFleetComponents([]); setRoutes([]); setFleetLoading(false); return }
    setFleetLoading(true)
    Promise.all([
      componentsApi.list({ fleet_id: activeFleet.id }).then((r) => setFleetComponents(r.data.components)),
      routesApi.list(activeFleet.id).then((r) => setRoutes(r.data.routes ?? r.data)).catch(() => setRoutes([])),
    ]).finally(() => setFleetLoading(false))
  }, [activeFleet])

  useEffect(() => { loadFleet() }, [loadFleet])

  // componentId → names of routes that reference it (source feed or sink target).
  const routeUsage: Record<string, string[]> = {}
  for (const r of routes) {
    const refs = new Set<string>([
      ...r.source_ids,
      ...r.passthrough_sink_ids,
      ...r.branches.flatMap((b) => b.sink_ids),
    ])
    for (const id of refs) (routeUsage[id] ??= []).push(r.name)
  }

  // component_type → count saved in the active fleet, by kind.
  const usageCount = (type: string, kind: 'source' | 'sink') =>
    fleetComponents.filter((c) => c.component_type === type && c.kind === kind).length

  const handleDelete = async (id: string) => {
    setDeletingId(id)
    try {
      if (await deleteGuarded((force) => componentsApi.delete(id, force)))
        setFleetComponents((prev) => prev.filter((c) => c.id !== id))
    } finally {
      setDeletingId(null)
    }
  }

  const components = tab === 'sources' ? sources : sinks

  const filtered = components.filter((c) => {
    const matchesSearch =
      !search ||
      c.name.toLowerCase().includes(search.toLowerCase()) ||
      c.type.toLowerCase().includes(search.toLowerCase()) ||
      c.description.toLowerCase().includes(search.toLowerCase()) ||
      c.category.toLowerCase().includes(search.toLowerCase())
    const matchesCategory = !activeCategory || c.category === activeCategory
    return matchesSearch && matchesCategory
  })

  const usedCategories = [...new Set(components.map((c) => c.category))]

  const handleSelect = (c: CatalogComponent) => {
    setEditing(null)
    setSelected((prev) => (prev?.type === c.type && prev?.category === c.category ? null : c))
  }

  // Edit a saved component: find its catalog definition and open the panel.
  const handleEdit = (c: Component) => {
    const def = [...sources, ...sinks].find((d) => d.type === c.component_type)
    if (!def) return
    setSelected(null)
    setEditing(c)
  }

  const editingDef = editing
    ? [...sources, ...sinks].find((d) => d.type === editing.component_type)
    : null

  // Config panel chrome — a right-anchored OVERLAY that floats over the component
  // list (so the cards don't reflow/squish when it opens or expands).
  const panelCls = `${panelWide ? 'w-[58vw] max-w-[1000px]' : 'w-[500px]'} absolute right-0 top-0 bottom-0 z-20 flex flex-col overflow-hidden bg-card border-l border-border shadow-2xl`
  const panelBar = (
    <div className="flex-shrink-0 flex justify-end px-2 py-1.5 border-l border-b border-border bg-secondary/40">
      <button
        onClick={() => setPanelWide((w) => !w)}
        title={panelWide ? 'Collapse panel' : 'Expand panel for more room'}
        className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground hover:text-foreground px-2 py-1 rounded border border-border hover:bg-secondary transition-colors"
      >
        <span className="text-sm leading-none">{panelWide ? '⤡' : '⤢'}</span>
        {panelWide ? 'Collapse' : 'Expand'}
      </button>
    </div>
  )

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Top bar */}
      <div className="flex-shrink-0 border-b border-border bg-card px-6 py-4 space-y-3">
        {/* Title + search */}
        <div className="flex items-center gap-4">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <h1 className="text-base font-semibold text-foreground">Component Catalog</h1>
              <span
                title={live
                  ? `Generated live from the deployed Vector ${vectorVersion ?? ''}`
                  : 'Using the catalog bundled in the app (Vector not reachable)'}
                className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${
                  live ? 'bg-primary/10 text-primary' : 'bg-secondary text-muted-foreground'
                }`}
              >
                {live ? `live · vector ${vectorVersion ?? '?'}` : 'bundled'}
              </span>
              {isAdmin && (
                <button
                  onClick={async () => { setRefreshing(true); try { await refresh() } finally { setRefreshing(false) } }}
                  disabled={refreshing}
                  className="text-[11px] text-muted-foreground hover:text-foreground disabled:opacity-50 transition-colors"
                  title="Re-read the source/sink catalog from the deployed Vector"
                >
                  {refreshing ? 'Refreshing…' : 'Refresh from Vector'}
                </button>
              )}
            </div>
            <p className="text-xs text-muted-foreground mt-0.5">
              Browse Vector sources &amp; sinks; "in use" badges show what {activeFleet?.name ?? 'this fleet'} already has. "In Fleet" lists its inventory with route usage.
            </p>
          </div>
          <div className="relative flex-shrink-0 w-60">
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth={1.75}
              className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground pointer-events-none"
            >
              <circle cx="11" cy="11" r="8" />
              <path d="M21 21l-4.35-4.35" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            <input
              type="search"
              className="w-full bg-background border border-border rounded-lg pl-8 pr-3 py-1.5 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary focus:border-primary"
              placeholder="Search components…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
        </div>

        {/* Tabs + category filters */}
        <div className="flex items-center gap-4 overflow-x-auto">
          {/* Source / Sink tabs */}
          <div className="flex rounded-lg border border-border overflow-hidden flex-shrink-0">
            <button
              onClick={() => { setTab('sources'); setSelected(null); setEditing(null); setActiveCategory(null) }}
              className={`px-4 py-1.5 text-xs font-medium transition-colors ${
                tab === 'sources'
                  ? 'bg-primary/15 text-primary'
                  : 'text-muted-foreground hover:text-foreground bg-background'
              }`}
            >
              Sources ({sources.length})
            </button>
            <button
              onClick={() => { setTab('sinks'); setSelected(null); setEditing(null); setActiveCategory(null) }}
              className={`px-4 py-1.5 text-xs font-medium border-l border-border transition-colors ${
                tab === 'sinks'
                  ? 'bg-primary/15 text-primary'
                  : 'text-muted-foreground hover:text-foreground bg-background'
              }`}
            >
              Sinks ({sinks.length})
            </button>
            <button
              onClick={() => { setTab('saved'); setSelected(null); setEditing(null); setActiveCategory(null) }}
              className={`px-4 py-1.5 text-xs font-medium border-l border-border transition-colors ${
                tab === 'saved'
                  ? 'bg-primary/15 text-primary'
                  : 'text-muted-foreground hover:text-foreground bg-background'
              }`}
            >
              In Fleet{fleetComponents.length > 0 ? ` (${fleetComponents.length})` : ''}
            </button>
          </div>

          {tab !== 'saved' && <div className="h-4 w-px bg-border flex-shrink-0" />}

          {/* Category chips */}
          {tab !== 'saved' && (
          <div className="flex items-center gap-1.5 overflow-x-auto">
            <button
              onClick={() => setActiveCategory(null)}
              className={`flex-shrink-0 px-3 py-1 rounded-full text-xs font-medium transition-colors border ${
                !activeCategory
                  ? 'border-primary/50 bg-primary/10 text-primary'
                  : 'border-border text-muted-foreground hover:text-foreground'
              }`}
            >
              All
            </button>
            {usedCategories.map((cat) => (
              <button
                key={cat}
                onClick={() => setActiveCategory(activeCategory === cat ? null : cat)}
                className={`flex-shrink-0 px-3 py-1 rounded-full text-xs font-medium transition-colors border ${
                  activeCategory === cat
                    ? 'border-primary/50 bg-primary/10 text-primary'
                    : 'border-border text-muted-foreground hover:text-foreground'
                }`}
              >
                {cat}
              </button>
            ))}
          </div>
          )}
        </div>
      </div>

      {/* Body */}
      {tab === 'saved' ? (
        <div className="relative flex flex-1 min-h-0">
          <div className="flex-1 min-h-0 overflow-y-auto">
            <Inventory
              components={fleetComponents}
              routeUsage={routeUsage}
              loading={fleetLoading}
              canEdit={canEdit}
              fleetName={activeFleet?.name}
              hasFleet={!!activeFleet}
              onEdit={handleEdit}
              onDelete={handleDelete}
              deletingId={deletingId}
            />
          </div>
          {editing && editingDef && (
            <div className={panelCls}>
              {panelBar}
              <div className="flex-1 min-h-0 [&>*]:h-full">
                <ComponentConfigForm
                  key={editing.id}
                  component={editingDef}
                  kind={editing.kind === 'source' ? 'sources' : 'sinks'}
                  existing={editing}
                  onClose={() => setEditing(null)}
                  onSaved={loadFleet}
                />
              </div>
            </div>
          )}
        </div>
      ) : (
        <div className="relative flex flex-1 min-h-0">
          {/* Cards grid — stays full width; the detail panel overlays it. */}
          <div className="flex-1 min-w-0 overflow-y-auto p-4 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 content-start">
            {filtered.length === 0 ? (
              <div className="col-span-full flex items-center justify-center py-16 text-sm text-muted-foreground">
                No components match your search.
              </div>
            ) : (
              filtered.map((c) => (
                <ComponentCard
                  key={`${tab}-${c.type}`}
                  component={c}
                  active={selected?.type === c.type && selected?.category === c.category}
                  onClick={() => handleSelect(c)}
                  usage={usageCount(c.type, tab === 'sources' ? 'source' : 'sink')}
                  fleetName={activeFleet?.name}
                  onUsageClick={() => { setSelected(null); setTab('saved') }}
                />
              ))
            )}
          </div>

          {/* Detail panel */}
          {selected && (
            <div className={panelCls}>
              {panelBar}
              <div className="flex-1 min-h-0 [&>*]:h-full">
                <ComponentConfigForm
                  key={`${selected.type}-${selected.category}`}
                  component={selected}
                  kind={tab as 'sources' | 'sinks'}
                  onClose={() => setSelected(null)}
                  onSaved={loadFleet}
                />
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
