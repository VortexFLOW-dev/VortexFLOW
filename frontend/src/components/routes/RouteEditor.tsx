// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

import { useEffect, useState } from 'react'
import { componentsApi, transformStagesApi, transformsApi } from '@/lib/api'
import type { Component, Fleet, Route, RouteBranch, TransformStage } from '@/lib/types'
import { btnPrimary, btnSecondary, inputCls } from '@/lib/ui'

// Stable client-side id so React keys survive branch reorder/removal (test
// panel state stays attached to the right branch).
let _branchUidCounter = 0
const nextBranchUid = () => `b${++_branchUidCounter}`

interface EditableBranch extends RouteBranch {
  _uid: string
}

// ─── YAML generation ─────────────────────────────────────────────────────────

const slug = (s: string, fallback: string) =>
  s.replace(/[^a-z0-9_]/gi, '_').toLowerCase() || fallback

// Assign collision-free YAML keys: two components whose names slug to the same
// value get -2, -3… suffixes so we never emit a duplicate top-level key.
function uniqueSlugger() {
  const used = new Set<string>()
  return (raw: string, fallback: string): string => {
    const base = slug(raw, fallback)
    let key = base
    let n = 2
    while (used.has(key)) key = `${base}_${n++}`
    used.add(key)
    return key
  }
}

interface RouteYamlInput {
  routeName: string
  branches: RouteBranch[]
  sources: Component[]
  passthroughSinkIds: string[]
  sinkById: Map<string, Component>
}

// Build a representative full Vector slice: sources → route → sinks.
// The authoritative config is assembled server-side; this is a preview.
function generateRouteYaml({
  routeName,
  branches,
  sources,
  passthroughSinkIds,
  sinkById,
}: RouteYamlInput): string {
  const keyOf = uniqueSlugger()
  const safeName = keyOf(routeName, 'my_route')
  const lines: string[] = []

  // Sources — unique key per component id
  const sourceKeyById = new Map<string, string>()
  if (sources.length) {
    lines.push('sources:')
    for (const s of sources) {
      const k = keyOf(s.name, s.id)
      sourceKeyById.set(s.id, k)
      lines.push(`  ${k}:`, `    type: ${s.component_type}`)
    }
    lines.push('')
  }

  // Route transform
  lines.push('transforms:', `  ${safeName}:`, '    type: route')
  lines.push(`    inputs: [${[...sourceKeyById.values()].join(', ')}]`, '    route:')
  for (const b of branches) {
    lines.push(`      ${slug(b.name, 'branch')}: '${b.condition.replace(/'/g, "''")}'`)
  }
  lines.push('')

  // Aggregate the route outputs each sink consumes, so a sink referenced by
  // multiple branches (or a branch + passthrough) is emitted ONCE with all its
  // inputs — emitting it twice would be a duplicate Vector component key.
  const sinkInputs = new Map<string, string[]>()
  const addSinkInput = (sinkId: string, routeOutput: string) => {
    if (!sinkById.has(sinkId)) return
    const out = `${safeName}.${routeOutput}`
    const existing = sinkInputs.get(sinkId)
    if (existing) {
      if (!existing.includes(out)) existing.push(out)
    } else {
      sinkInputs.set(sinkId, [out])
    }
  }
  for (const b of branches) {
    for (const id of b.sink_ids) addSinkInput(id, slug(b.name, 'branch'))
  }
  for (const id of passthroughSinkIds) addSinkInput(id, '_unmatched')

  if (sinkInputs.size) {
    lines.push('sinks:')
    for (const [sinkId, inputs] of sinkInputs) {
      const sink = sinkById.get(sinkId)!
      const k = keyOf(sink.name, sink.id)
      lines.push(
        `  ${k}:`,
        `    type: ${sink.component_type}`,
        `    inputs: [${inputs.map((i) => `"${i}"`).join(', ')}]`
      )
    }
  }

  return lines.join('\n')
}

// ─── Component multi-select ────────────────────────────────────────────────

// Searchable multi-select: selected items as removable chips + a "+ add"
// typeahead dropdown. Scales to many sources/destinations (vs a flat chip wall).
function ComponentPicker({
  options,
  selected,
  canEdit,
  emptyLabel,
  onChange,
}: {
  options: { id: string; name: string; component_type?: string }[]
  selected: string[]
  canEdit: boolean
  emptyLabel: string
  onChange: (ids: string[]) => void
}) {
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)
  if (options.length === 0) {
    return <span className="text-xs text-muted-foreground/60 italic">{emptyLabel}</span>
  }
  const byId = new Map(options.map((o) => [o.id, o]))
  const selectedOpts = selected.map((id) => byId.get(id)).filter(Boolean) as typeof options
  const q = query.trim().toLowerCase()
  const matches = options.filter(
    (o) =>
      !selected.includes(o.id) &&
      (!q || o.name.toLowerCase().includes(q) || (o.component_type ?? '').toLowerCase().includes(q)),
  )
  const add = (id: string) => { onChange([...selected, id]); setQuery('') }
  const remove = (id: string) => onChange(selected.filter((x) => x !== id))

  return (
    <div className="space-y-1.5">
      {selectedOpts.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {selectedOpts.map((o) => (
            <span key={o.id} className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full border border-primary/50 bg-primary/10 text-primary" title={o.component_type}>
              {o.name}
              {canEdit && (
                <button type="button" onClick={() => remove(o.id)} className="hover:text-foreground" aria-label={`Remove ${o.name}`}>×</button>
              )}
            </span>
          ))}
        </div>
      )}
      {canEdit && (
        <div className="relative max-w-xs">
          <input
            type="text"
            value={query}
            onChange={(e) => { setQuery(e.target.value); setOpen(true) }}
            onFocus={() => setOpen(true)}
            onBlur={() => setTimeout(() => setOpen(false), 120)}
            placeholder="+ add…"
            className={inputCls + ' text-xs'}
          />
          {open && matches.length > 0 && (
            <div className="absolute z-20 mt-1 w-full max-h-48 overflow-y-auto bg-card border border-border rounded-lg shadow-lg py-1">
              {matches.slice(0, 50).map((o) => (
                <button
                  key={o.id}
                  type="button"
                  onMouseDown={(e) => { e.preventDefault(); add(o.id) }}
                  className="flex items-center justify-between gap-2 w-full text-left px-3 py-1.5 text-xs hover:bg-secondary"
                >
                  <span className="text-foreground truncate">{o.name}</span>
                  {o.component_type && <span className="text-muted-foreground/50 font-mono flex-shrink-0">{o.component_type}</span>}
                </button>
              ))}
            </div>
          )}
          {open && q && matches.length === 0 && (
            <div className="absolute z-20 mt-1 w-full bg-card border border-border rounded-lg shadow-lg px-3 py-1.5 text-xs text-muted-foreground/60">
              No matches
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ─── Branch row ───────────────────────────────────────────────────────────────

interface TestState {
  status: 'idle' | 'running' | 'matched' | 'unmatched' | 'error'
  message?: string
}

function BranchRow({
  branch,
  routeName,
  canEdit,
  sinks,
  onUpdate,
  onRemove,
}: {
  branch: RouteBranch
  routeName: string
  canEdit: boolean
  sinks: Component[]
  onUpdate: (b: RouteBranch) => void
  onRemove: () => void
}) {
  const [testEvent, setTestEvent] = useState('{"level":"info","message":"test"}')
  const [testOpen, setTestOpen] = useState(false)
  const [testState, setTestState] = useState<TestState>({ status: 'idle' })

  const runTest = async () => {
    let parsed: object
    try {
      parsed = JSON.parse(testEvent)
    } catch {
      setTestState({ status: 'error', message: 'Invalid JSON event' })
      return
    }
    setTestState({ status: 'running' })
    try {
      // Use VRL condition as a boolean expression — wrap it so testRemap returns bool
      const vrl = `result = (${branch.condition})\n. = {"matched": result}`
      const res = await transformsApi.test({ vrl, event: parsed })
      // /transforms/test returns HTTP 200 even when success:false (no instance,
      // VRL compile error) — surface that as an error, not a false "no match".
      if (res.data?.success === false) {
        setTestState({ status: 'error', message: res.data.error ?? 'VRL test failed' })
        return
      }
      const matched = res.data?.output?.matched === true
      setTestState({ status: matched ? 'matched' : 'unmatched' })
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        'Test failed'
      setTestState({ status: 'error', message: detail })
    }
  }

  const statusColor: Record<TestState['status'], string> = {
    idle: 'text-muted-foreground',
    running: 'text-muted-foreground animate-pulse',
    matched: 'text-emerald-400',
    unmatched: 'text-amber-400',
    error: 'text-destructive',
  }

  const statusLabel: Record<TestState['status'], string> = {
    idle: '',
    running: 'Testing…',
    matched: '✓ Matched',
    unmatched: '✗ No match',
    error: testState.message ?? 'Error',
  }

  const outKey = `${slug(routeName, 'my_route')}.${slug(branch.name, 'branch')}`

  return (
    <div className="border border-border rounded-xl overflow-hidden">
      {/* IF <condition> */}
      <div className="flex items-center gap-2 px-4 py-3 bg-card">
        <span className="flex-shrink-0 text-xs font-semibold text-violet-500/80 w-8">IF</span>
        <input
          type="text"
          disabled={!canEdit}
          className={`${inputCls} flex-1 font-mono text-xs`}
          value={branch.condition}
          onChange={(e) => onUpdate({ ...branch, condition: e.target.value })}
          placeholder='.level == "error"   (VRL condition)'
        />
        <button
          onClick={() => { setTestOpen((o) => !o); setTestState({ status: 'idle' }) }}
          className="flex-shrink-0 text-xs text-muted-foreground hover:text-foreground transition-colors px-2 py-1 rounded border border-border hover:border-border/80"
        >
          Test
        </button>
        {canEdit && (
          <button onClick={onRemove} className="flex-shrink-0 text-muted-foreground hover:text-destructive transition-colors" title="Remove branch">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="h-4 w-4">
              <path d="M18 6L6 18M6 6l12 12" strokeLinecap="round" />
            </svg>
          </button>
        )}
      </div>

      {/* → SEND TO <destinations> */}
      <div className="border-t border-border px-4 py-2.5 bg-background/30 flex items-center gap-3">
        <span className="flex-shrink-0 text-xs font-semibold text-orange-500/80 w-20">→ SEND TO</span>
        <ComponentPicker
          options={sinks}
          selected={branch.sink_ids}
          canEdit={canEdit}
          emptyLabel="No sinks in this fleet yet — add one in the Catalog."
          onChange={(ids) => onUpdate({ ...branch, sink_ids: ids })}
        />
      </div>

      {/* Branch name (Vector output key) — secondary */}
      <div className="border-t border-border/60 px-4 py-2 flex items-center gap-2">
        <span className="flex-shrink-0 text-xs text-muted-foreground/50 w-8">name</span>
        <input
          type="text"
          disabled={!canEdit}
          className={`${inputCls} w-40 text-xs`}
          value={branch.name}
          onChange={(e) => onUpdate({ ...branch, name: e.target.value })}
          placeholder="branch_name"
        />
        <span className="text-xs font-mono text-muted-foreground/40 truncate">output: {outKey}</span>
      </div>

      {/* Inline test panel */}
      {testOpen && (
        <div className="border-t border-border px-4 py-3 bg-background/50 space-y-2">
          <div className="flex items-center gap-2">
            <input
              type="text"
              className={`${inputCls} flex-1 font-mono text-xs`}
              value={testEvent}
              onChange={(e) => { setTestEvent(e.target.value); setTestState({ status: 'idle' }) }}
              placeholder='{"level":"error","message":"oops"}'
            />
            <button
              onClick={runTest}
              disabled={testState.status === 'running'}
              className="flex-shrink-0 bg-primary/15 hover:bg-primary/25 text-primary text-xs font-medium px-3 py-2 rounded-lg transition-colors disabled:opacity-50"
            >
              Run
            </button>
          </div>
          {testState.status !== 'idle' && (
            <p className={`text-xs font-medium ${statusColor[testState.status]}`}>
              {statusLabel[testState.status]}
            </p>
          )}
        </div>
      )}
    </div>
  )
}

// ─── Passthrough row ─────────────────────────────────────────────────────────

function PassthroughRow({
  sinks,
  selected,
  canEdit,
  onChange,
}: {
  sinks: Component[]
  selected: string[]
  canEdit: boolean
  onChange: (ids: string[]) => void
}) {
  return (
    <div className="border border-dashed border-border rounded-xl overflow-hidden bg-card/50">
      <div className="px-4 py-3 flex items-center gap-2">
        <span className="flex-shrink-0 text-xs font-semibold text-muted-foreground/70 w-20">ELSE</span>
        <span className="text-xs text-muted-foreground/60 flex-1">
          Everything not matched by a branch above (the <code className="font-mono">_unmatched</code> passthrough)
        </span>
      </div>
      <div className="border-t border-dashed border-border px-4 py-2.5 bg-background/20 flex items-center gap-3">
        <span className="flex-shrink-0 text-xs font-semibold text-orange-500/80 w-20">→ SEND TO</span>
        <ComponentPicker
          options={sinks}
          selected={selected}
          canEdit={canEdit}
          emptyLabel="leave empty to drop unmatched events"
          onChange={onChange}
        />
      </div>
    </div>
  )
}

// ─── Data Preview ────────────────────────────────────────────────────────────
// Fan N sample events through all branches in order, returning which branch
// each event lands in and the transformed event (if the condition is a remap,
// not just a boolean — for now we just report match/no-match per branch).

interface BranchResult {
  branchName: string
  matched: boolean
  error?: string
}

interface EventResult {
  eventIndex: number
  eventPreview: string
  results: BranchResult[]
  matchCount: number // branches matched (multi-match) — 0 = passthrough
}

function DataPreview({
  branches,
  open,
  onToggle,
}: {
  branches: EditableBranch[]
  open: boolean
  onToggle: () => void
}) {
  const [rawEvents, setRawEvents] = useState(
    '{"level":"error","message":"disk full","host":"web-01"}\n{"level":"info","message":"startup complete"}'
  )
  const [running, setRunning] = useState(false)
  const [results, setResults] = useState<EventResult[] | null>(null)
  const [previewError, setPreviewError] = useState<string | null>(null)

  const run = async () => {
    const lines = rawEvents
      .split('\n')
      .map((l) => l.trim())
      .filter(Boolean)
    const events: object[] = []
    for (const line of lines) {
      try {
        events.push(JSON.parse(line))
      } catch {
        setPreviewError(`Invalid JSON on line: ${line.slice(0, 60)}`)
        return
      }
    }
    if (events.length === 0) {
      setPreviewError('Paste at least one JSON event (one per line)')
      return
    }
    if (events.length > 20) {
      setPreviewError('Maximum 20 events per preview run')
      return
    }
    if (branches.length === 0) {
      setPreviewError('Add at least one branch first')
      return
    }

    setRunning(true)
    setPreviewError(null)
    setResults(null)

    try {
      const eventResults: EventResult[] = []
      for (let ei = 0; ei < events.length; ei++) {
        const ev = events[ei]
        const branchResults: BranchResult[] = []

        for (const branch of branches) {
          if (!branch.condition.trim()) {
            branchResults.push({ branchName: branch.name, matched: false })
            continue
          }
          const vrl = `result = (${branch.condition})\n. = {"matched": result}`
          try {
            const res = await transformsApi.test({ vrl, event: ev })
            if (res.data?.success === false) {
              branchResults.push({
                branchName: branch.name,
                matched: false,
                error: res.data.error ?? 'VRL error',
              })
            } else {
              branchResults.push({ branchName: branch.name, matched: res.data?.output?.matched === true })
            }
          } catch {
            branchResults.push({ branchName: branch.name, matched: false, error: 'Request failed' })
          }
        }

        eventResults.push({
          eventIndex: ei,
          eventPreview: JSON.stringify(ev).slice(0, 80),
          results: branchResults,
          matchCount: branchResults.filter((b) => b.matched).length,
        })
      }
      setResults(eventResults)
    } finally {
      setRunning(false)
    }
  }

  const matchSummary = (n: number) =>
    n === 0
      ? { label: '→ passthrough', cls: 'text-muted-foreground bg-secondary' }
      : { label: `→ ${n} branch${n !== 1 ? 'es' : ''}`, cls: 'text-emerald-400 bg-emerald-400/10' }

  return (
    <div className="border-t border-border flex-shrink-0">
      <button
        onClick={onToggle}
        className="w-full flex items-center justify-between px-5 py-2.5 text-xs font-medium text-muted-foreground hover:text-foreground transition-colors"
      >
        <span>Data Preview</span>
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth={2}
          className={`h-3.5 w-3.5 transition-transform ${open ? 'rotate-180' : ''}`}
        >
          <path d="M6 9l6 6 6-6" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>

      {open && (
        <div className="border-t border-border/50 px-5 pb-4 space-y-3 bg-background/30">
          <p className="text-xs text-muted-foreground pt-3">
            Paste sample events (one JSON object per line) to see which branches each event matches (it can match several).
          </p>
          <textarea
            className={`${inputCls} font-mono text-xs leading-relaxed resize-y min-h-[80px]`}
            value={rawEvents}
            onChange={(e) => { setRawEvents(e.target.value); setResults(null); setPreviewError(null) }}
            placeholder={'{"level":"error","message":"disk full"}\n{"level":"info","message":"ok"}'}
            rows={3}
          />
          <div className="flex items-center gap-3">
            <button
              onClick={() => { void run() }}
              disabled={running || branches.length === 0}
              className="bg-primary/15 hover:bg-primary/25 text-primary text-xs font-medium px-4 py-1.5 rounded-lg transition-colors disabled:opacity-50"
            >
              {running ? 'Running…' : 'Run preview'}
            </button>
            {results && (
              <span className="text-xs text-muted-foreground">
                {results.length} event{results.length !== 1 ? 's' : ''} processed
              </span>
            )}
          </div>

          {previewError && (
            <p className="text-xs text-destructive">{previewError}</p>
          )}

          {results && (
            <div className="space-y-2">
              {results.map((er) => (
                <div key={er.eventIndex} className="border border-border rounded-lg overflow-hidden">
                  <div className="flex items-center justify-between gap-3 px-3 py-2 bg-card">
                    <code className="text-xs text-foreground/70 truncate flex-1">
                      {er.eventPreview}{er.eventPreview.length >= 80 ? '…' : ''}
                    </code>
                    <span className={`text-xs font-mono px-2 py-0.5 rounded-full flex-shrink-0 ${matchSummary(er.matchCount).cls}`}>
                      {matchSummary(er.matchCount).label}
                    </span>
                  </div>
                  <div className="flex flex-wrap gap-1.5 px-3 py-2 bg-background/20 border-t border-border/50">
                    {er.results.map((br) => (
                      <span
                        key={br.branchName}
                        title={br.error ?? (br.matched ? 'Matched' : 'No match')}
                        className={`text-xs font-mono px-2 py-0.5 rounded border ${
                          br.error
                            ? 'border-destructive/50 text-destructive bg-destructive/8'
                            : br.matched
                            ? 'border-emerald-500/50 text-emerald-400 bg-emerald-400/8'
                            : 'border-border text-muted-foreground/50'
                        }`}
                      >
                        {br.matched ? '✓' : br.error ? '!' : '✗'} {br.branchName}
                      </span>
                    ))}
                    <span className="text-xs font-mono px-2 py-0.5 rounded border border-dashed border-border text-muted-foreground/40">
                      ∞ passthrough
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ─── Route editor ────────────────────────────────────────────────────────────

export function RouteEditor({
  route,
  fleets,
  canEdit,
  onSave,
  onDelete,
  onClose,
}: {
  route: Route | null
  fleets: Fleet[]
  canEdit: boolean
  onSave: (data: {
    name: string
    fleet_id: string
    description: string
    branches: RouteBranch[]
    source_ids: string[]
    passthrough_sink_ids: string[]
  }) => Promise<void>
  onDelete?: () => Promise<void>
  onClose: () => void
}) {
  const isNew = route === null
  const [name, setName] = useState(route?.name ?? '')
  const [description, setDescription] = useState(route?.description ?? '')
  const [fleetId, setFleetId] = useState(route?.fleet_id ?? fleets[0]?.id ?? '')
  const [branches, setBranches] = useState<EditableBranch[]>(() =>
    // New routes start with one blank branch to fill in — not a fake sample
    // condition that reads like real config (and would save as junk).
    (route?.branches ?? [{ name: 'branch_1', condition: '', sink_ids: [] }]).map(
      (b) => ({ ...b, sink_ids: b.sink_ids ?? [], _uid: nextBranchUid() })
    )
  )
  const [sourceIds, setSourceIds] = useState<string[]>(route?.source_ids ?? [])
  const [passthroughSinkIds, setPassthroughSinkIds] = useState<string[]>(
    route?.passthrough_sink_ids ?? []
  )
  const [components, setComponents] = useState<Component[]>([])
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [yamlOpen, setYamlOpen] = useState(false)
  const [previewOpen, setPreviewOpen] = useState(false)
  const [copied, setCopied] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  const [stages, setStages] = useState<TransformStage[]>([])

  // Load this fleet's source/sink resources + remap stages for the pickers.
  useEffect(() => {
    if (!fleetId) return
    let active = true
    componentsApi
      .list({ fleet_id: fleetId })
      .then((r) => {
        if (active) setComponents(r.data.components ?? [])
      })
      .catch(() => {
        if (active) setComponents([])
      })
    transformStagesApi
      .list(fleetId)
      .then((r) => { if (active) setStages(r.data.stages) })
      .catch(() => { if (active) setStages([]) })
    return () => {
      active = false
    }
  }, [fleetId])

  const sources = components.filter((c) => c.kind === 'source')
  const sinks = components.filter((c) => c.kind === 'sink')
  // A route input can be a source component OR a remap stage (source → remap → route).
  const sourceOptions = [
    ...sources.map((s) => ({ id: s.id, name: s.name, component_type: s.component_type })),
    ...stages.map((s) => ({ id: s.id, name: `${s.name} (remap)`, component_type: 'remap' })),
  ]
  const sinkById = new Map(sinks.map((s) => [s.id, s]))

  const yaml = generateRouteYaml({
    routeName: name || 'my_route',
    branches,
    sources: sources.filter((s) => sourceIds.includes(s.id)),
    passthroughSinkIds,
    sinkById,
  })

  const addBranch = () => {
    setBranches((prev) => [
      ...prev,
      { name: `branch_${prev.length + 1}`, condition: '', sink_ids: [], _uid: nextBranchUid() },
    ])
  }

  const updateBranch = (i: number, b: RouteBranch) => {
    setBranches((prev) => prev.map((x, idx) => (idx === i ? { ...b, _uid: x._uid } : x)))
  }

  const removeBranch = (i: number) => {
    setBranches((prev) => prev.filter((_, idx) => idx !== i))
  }

  const handleSave = async () => {
    setSaving(true)
    setSaveError(null)
    try {
      const cleanBranches = branches.map(({ name: n, condition, sink_ids }) => ({
        name: n,
        condition,
        sink_ids,
      }))
      await onSave({
        name,
        fleet_id: fleetId,
        description,
        branches: cleanBranches,
        source_ids: sourceIds,
        passthrough_sink_ids: passthroughSinkIds,
      })
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setSaveError(detail ?? 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async () => {
    if (!onDelete) return
    setDeleting(true)
    try {
      await onDelete()
    } finally {
      setDeleting(false)
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

  return (
    <div className="flex flex-col h-full border-l border-border bg-card overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-4 border-b border-border flex-shrink-0">
        <div>
          <h2 className="text-sm font-semibold text-foreground">
            {isNew ? 'New Route' : route.name}
          </h2>
          <p className="text-xs text-muted-foreground mt-0.5">
            Vector <code className="text-primary/80">route</code> transform with named branches
          </p>
        </div>
        <button onClick={onClose} className="text-muted-foreground hover:text-foreground transition-colors">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="h-4 w-4">
            <path d="M18 6L6 18M6 6l12 12" strokeLinecap="round" />
          </svg>
        </button>
      </div>

      {/* Form */}
      <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
        {/* Fleet is implicit in the fleet-scoped Transforms/Flow context (only one
            fleet is ever passed), so the picker is hidden unless there's a real
            choice. Name spans full width when it's the lone field. */}
        <div className={`grid gap-3 ${fleets.length > 1 ? 'grid-cols-2' : 'grid-cols-1'}`}>
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-muted-foreground">
              Name <span className="text-destructive">*</span>
            </label>
            <input
              type="text"
              disabled={!canEdit}
              className={inputCls}
              value={name}
              onChange={(e) => setName(e.target.value.replace(/[^a-z0-9_]/gi, '_').toLowerCase())}
              placeholder="my_route"
            />
          </div>
          {fleets.length > 1 && (
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-muted-foreground">Fleet</label>
              <select
                disabled={!isNew || !canEdit}
                className={`${inputCls} bg-background`}
                value={fleetId}
                onChange={(e) => setFleetId(e.target.value)}
              >
                {fleets.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
            </div>
          )}
        </div>

        <div className="space-y-1.5">
          <label className="text-xs font-medium text-muted-foreground">Description</label>
          <input
            type="text"
            disabled={!canEdit}
            className={inputCls}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Optional description"
          />
        </div>

        {/* "Do you even need a route?" hint */}
        <div className="rounded-lg border border-border bg-secondary/30 px-3 py-2 text-xs text-muted-foreground">
          A route <span className="text-foreground">splits data by condition</span>. To send a source
          straight to a sink, skip this — connect them on the{' '}
          <span className="text-primary">Flow</span> canvas instead.
        </div>

        {/* Sources (route inputs) */}
        <div className="space-y-1.5">
          <label className="text-xs font-medium text-muted-foreground">Reading from</label>
          <p className="text-xs text-muted-foreground/50">Click a source or remap to feed this route (or wire it on the canvas).</p>
          <ComponentPicker
            options={sourceOptions}
            selected={sourceIds}
            canEdit={canEdit}
            emptyLabel="No sources or remap stages in this fleet yet."
            onChange={setSourceIds}
          />
        </div>

        {/* Branches — each reads IF <condition> → SEND TO <destinations> */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <label className="text-xs font-medium text-muted-foreground">Branches</label>
            <span className="text-xs text-muted-foreground/60">
              Match independently — an event fires every branch it matches (not first-match).
            </span>
          </div>

          <div className="space-y-2">
            {branches.map((b, i) => (
              <BranchRow
                key={b._uid}
                branch={b}
                routeName={name || 'my_route'}
                canEdit={canEdit}
                sinks={sinks}
                onUpdate={(updated) => updateBranch(i, updated)}
                onRemove={() => removeBranch(i)}
              />
            ))}
            <PassthroughRow
              sinks={sinks}
              selected={passthroughSinkIds}
              canEdit={canEdit}
              onChange={setPassthroughSinkIds}
            />
          </div>

          {canEdit && (
            <button
              onClick={addBranch}
              className="w-full py-2 border border-dashed border-border rounded-xl text-xs text-muted-foreground hover:text-foreground hover:border-border/80 transition-colors"
            >
              + Add branch
            </button>
          )}
        </div>
      </div>

      {/* Data Preview */}
      <DataPreview
        branches={branches}
        open={previewOpen}
        onToggle={() => setPreviewOpen((o) => !o)}
      />

      {/* YAML preview */}
      <div className="border-t border-border flex-shrink-0">
        <button
          onClick={() => setYamlOpen((o) => !o)}
          className="w-full flex items-center justify-between px-5 py-2.5 text-xs font-medium text-muted-foreground hover:text-foreground transition-colors"
        >
          <span>Generated YAML</span>
          <div className="flex items-center gap-3">
            {yamlOpen && (
              <span
                onClick={(e) => { e.stopPropagation(); void copyYaml() }}
                className="text-xs text-muted-foreground hover:text-foreground transition-colors cursor-pointer px-2 py-0.5 rounded hover:bg-secondary"
              >
                {copied ? 'Copied!' : 'Copy'}
              </span>
            )}
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth={2}
              className={`h-3.5 w-3.5 transition-transform ${yamlOpen ? 'rotate-180' : ''}`}
            >
              <path d="M6 9l6 6 6-6" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>
        </button>
        {yamlOpen && (
          <pre className="px-5 pb-4 text-xs font-mono text-foreground/80 overflow-x-auto max-h-48 overflow-y-auto leading-relaxed border-t border-border/50">
            {yaml}
          </pre>
        )}
      </div>

      {/* Save error */}
      {saveError && (
        <div className="px-5 pt-2 flex-shrink-0">
          <p className="text-xs text-destructive">{saveError}</p>
        </div>
      )}

      {/* Footer actions */}
      {canEdit && (
        <div className="flex items-center justify-between px-5 py-3 border-t border-border flex-shrink-0">
          <div>
            {!isNew && onDelete && (
              <button
                onClick={handleDelete}
                disabled={deleting}
                className="text-sm text-destructive hover:text-destructive/80 transition-colors disabled:opacity-50"
              >
                {deleting ? 'Deleting…' : 'Delete route'}
              </button>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button onClick={onClose} className={btnSecondary}>
              Cancel
            </button>
            <button
              onClick={handleSave}
              disabled={saving || !name}
              className={btnPrimary}
            >
              {saving ? 'Saving…' : isNew ? 'Create route' : 'Save changes'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

// ─── Route list item ───────────────────────────────────────────────────────────

// Dense, expandable master-list row. Expansion shows branches as independent
// fan-out conditions (Vector `route` is multi-match — NOT Cribl first-match), with
// _unmatched pinned last as the catch-all.
export function RouteListItem({
  route,
  fleetName,
  showFleet,
  active,
  expanded,
  onSelect,
  onToggle,
  nameOf,
}: {
  route: Route
  fleetName: string
  showFleet: boolean
  active: boolean
  expanded: boolean
  onSelect: () => void
  onToggle: () => void
  nameOf: (id: string) => string
}) {
  const sources = route.source_ids.map(nameOf)
  const sinkIds = new Set<string>([
    ...route.branches.flatMap((b) => b.sink_ids),
    ...route.passthrough_sink_ids,
  ])
  const names = (ids: string[]) => (ids.length ? ids.map(nameOf).join(', ') : '—')

  return (
    <div
      className={`rounded-xl border transition-colors ${
        active ? 'border-primary/50 bg-primary/5 ring-1 ring-primary/30' : 'border-border bg-card'
      }`}
    >
      <div className="flex items-center gap-2 px-3 py-2.5">
        <button
          onClick={onToggle}
          className="flex-shrink-0 text-muted-foreground hover:text-foreground p-0.5"
          title={expanded ? 'Collapse' : 'Show branches'}
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}
            className={`h-3.5 w-3.5 transition-transform ${expanded ? 'rotate-90' : ''}`}>
            <path d="M9 18l6-6-6-6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
        <button onClick={onSelect} className="flex-1 min-w-0 text-left">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-medium text-foreground">{route.name}</span>
            {showFleet && (
              <span className="text-xs bg-secondary text-muted-foreground px-1.5 py-0.5 rounded-full">{fleetName}</span>
            )}
          </div>
          <div className="text-xs text-muted-foreground mt-0.5 truncate">
            <span className="text-muted-foreground/70">{sources.length ? sources.join(', ') : 'no source'}</span>
            {' → '}
            {route.branches.length} branch{route.branches.length !== 1 ? 'es' : ''}
            {' → '}
            <span className="text-muted-foreground/70">{sinkIds.size} sink{sinkIds.size !== 1 ? 's' : ''}</span>
          </div>
        </button>
      </div>

      {expanded && (
        <div className="border-t border-border px-3 py-2.5 bg-background/40 space-y-1.5">
          <p className="text-[11px] text-muted-foreground/60">
            Branches match <span className="text-muted-foreground">independently</span> — an event fires every branch whose condition matches.
          </p>
          {route.branches.map((b) => (
            <div key={b.name} className="grid grid-cols-[7rem_1fr_auto] gap-2 items-start text-xs">
              <span className="font-mono text-primary/80 truncate" title={b.name}>{b.name}</span>
              <code className="text-foreground/70 break-all">{b.condition || '(always)'}</code>
              <span className="text-muted-foreground text-right">→ {names(b.sink_ids)}</span>
            </div>
          ))}
          <div className="grid grid-cols-[7rem_1fr_auto] gap-2 items-start text-xs border-t border-border/60 pt-1.5 mt-1.5">
            <span className="font-mono text-muted-foreground/60">_unmatched</span>
            <span className="text-muted-foreground/50">everything else</span>
            <span className="text-muted-foreground text-right">
              → {route.passthrough_sink_ids.length ? names(route.passthrough_sink_ids) : 'dropped'}
            </span>
          </div>
        </div>
      )}
    </div>
  )
}
