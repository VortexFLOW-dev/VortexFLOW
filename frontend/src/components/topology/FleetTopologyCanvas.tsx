// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

import { useEffect, useState, useCallback, useRef } from 'react'
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  BackgroundVariant,
} from '@xyflow/react'
import type { Node, Edge, Connection } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { componentsApi, fleetsApi, routesApi, transformStagesApi } from '@/lib/api'
import type { Component, Route, TransformStage } from '@/lib/types'
import { buildFleetFlowGraph } from '@/lib/fleetTopology'
import type { FleetNodeData, FleetNodeKind } from '@/lib/fleetTopology'
import { FleetNode, KIND_STYLES } from './FleetNode'
import { useTheme } from '@/lib/theme'
import { SOURCES, SINKS } from '@/lib/catalog'
import Modal from '@/components/ui/Modal'
import { btnPrimary, btnSecondary, inputCls } from '@/lib/ui'

type AddKind = 'source' | 'sink' | 'transform' | 'route'

function AddNodeModal({
  kind,
  fleetId,
  onClose,
  onAdded,
}: {
  kind: AddKind
  fleetId: string
  onClose: () => void
  // Receives the new resource id so the caller can open its drawer to configure it.
  onAdded: (createdId?: string) => void
}) {
  const catalog = kind === 'source' ? SOURCES : kind === 'sink' ? SINKS : []
  const [name, setName] = useState('')
  const [type, setType] = useState(catalog[0]?.type ?? '')
  const [vrl, setVrl] = useState('. = parse_json!(.message)\n')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const title = { source: 'Add source', sink: 'Add sink', transform: 'Add transform (remap)', route: 'Add route' }[kind]

  const submit = async () => {
    if (!name.trim()) { setError('Name is required'); return }
    setBusy(true)
    setError(null)
    try {
      let createdId: string | undefined
      if (kind === 'source' || kind === 'sink') {
        const res = await componentsApi.create({ fleet_id: fleetId, kind, name: name.trim(), component_type: type, config: {} })
        createdId = (res.data as { id?: string })?.id
      } else if (kind === 'transform') {
        const res = await transformStagesApi.create({ fleet_id: fleetId, name: name.trim(), mode: 'inline', source_vrl: vrl, inputs: [] })
        createdId = res.data?.id
      } else {
        const res = await routesApi.create({ fleet_id: fleetId, name: name.trim(), branches: [], source_ids: [], passthrough_sink_ids: [] })
        createdId = (res.data as { id?: string })?.id
      }
      onAdded(createdId)
      onClose()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail ?? 'Create failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal title={title} onClose={onClose} maxWidth="max-w-md">
      <div className="p-5 space-y-4">
        <div>
          <label className="block text-xs font-medium text-muted-foreground mb-1">Name</label>
          <input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} placeholder={kind === 'route' ? 'errors' : kind === 'transform' ? 'parse_logs' : 'my_' + kind} autoFocus />
        </div>
        {(kind === 'source' || kind === 'sink') && (
          <div>
            <label className="block text-xs font-medium text-muted-foreground mb-1">Type</label>
            <select className={inputCls} value={type} onChange={(e) => setType(e.target.value)}>
              {catalog.map((c) => <option key={c.type} value={c.type}>{c.name} ({c.type})</option>)}
            </select>
            <p className="text-xs text-muted-foreground/60 mt-1">You'll configure its fields in the drawer next.</p>
          </div>
        )}
        {kind === 'transform' && (
          <div>
            <label className="block text-xs font-medium text-muted-foreground mb-1">VRL</label>
            <textarea className={`${inputCls} font-mono text-xs resize-y min-h-[100px]`} value={vrl} onChange={(e) => setVrl(e.target.value)} rows={5} />
          </div>
        )}
        {kind === 'route' && (
          <p className="text-xs text-muted-foreground/60">Add branch conditions + sinks after creating, in the route editor.</p>
        )}
        {error && <p className="text-xs text-destructive">{error}</p>}
        <div className="flex justify-end gap-2">
          <button onClick={onClose} className={btnSecondary}>Cancel</button>
          <button onClick={() => { void submit() }} disabled={busy} className={btnPrimary}>
            {busy ? 'Adding…' : title}
          </button>
        </div>
      </div>
    </Modal>
  )
}

function InsertRemapModal({
  onSubmit,
  onClose,
}: {
  onSubmit: (name: string, vrl: string) => Promise<void>
  onClose: () => void
}) {
  const [name, setName] = useState('')
  const [vrl, setVrl] = useState('. = parse_json!(.message)\n')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const submit = async () => {
    if (!name.trim()) { setError('Name is required'); return }
    setBusy(true)
    await onSubmit(name, vrl)
  }
  return (
    <Modal title="Insert remap on this edge" onClose={onClose} maxWidth="max-w-md">
      <div className="p-5 space-y-4">
        <p className="text-xs text-muted-foreground/70">
          A new remap is spliced in: the upstream feeds the remap, and the downstream now reads the remap.
        </p>
        <div>
          <label className="block text-xs font-medium text-muted-foreground mb-1">Name</label>
          <input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} placeholder="parse_logs" autoFocus />
        </div>
        <div>
          <label className="block text-xs font-medium text-muted-foreground mb-1">VRL</label>
          <textarea className={`${inputCls} font-mono text-xs resize-y min-h-[100px]`} value={vrl} onChange={(e) => setVrl(e.target.value)} rows={5} />
        </div>
        {error && <p className="text-xs text-destructive">{error}</p>}
        <div className="flex justify-end gap-2">
          <button onClick={onClose} className={btnSecondary}>Cancel</button>
          <button onClick={() => { void submit() }} disabled={busy} className={btnPrimary}>
            {busy ? 'Inserting…' : 'Insert remap'}
          </button>
        </div>
      </div>
    </Modal>
  )
}

const NODE_TYPES = { fleetNode: FleetNode }

interface Props {
  fleetId: string
  onRouteClick: (routeId: string) => void
  // Click a remap node → edit its VRL in the drawer (receives the stage id).
  onEditRemap?: (stageId: string) => void
  // Click a source/sink node → configure it in the drawer (receives the component id).
  onConfigureComponent?: (componentId: string) => void
  // A node was just created via the palette → open its drawer to configure it.
  onNodeCreated?: (resourceId: string) => void
  // Surfaces the canvas's loaded components/routes/stages so the page can feed
  // the node drawers without re-fetching (kept fresh on every reload).
  onData?: (d: { components: Component[]; routes: Route[]; stages: TransformStage[] }) => void
  // Bumping this triggers a reload (e.g. after a route is saved/deleted).
  reloadKey?: number
  // When true, edges can be drawn (wire) and deleted (unwire) directly.
  editable?: boolean
}

type Parsed = { kind: 'c' | 's' | 'r'; id: string }
const parseNodeId = (nodeId: string): Parsed => {
  const [k, ...rest] = nodeId.split(':')
  return { kind: k as Parsed['kind'], id: rest.join(':') }
}
const uniq = (a: string[]) => Array.from(new Set(a))

export default function FleetTopologyCanvas({ fleetId, onRouteClick, onEditRemap, onConfigureComponent, onNodeCreated, onData, reloadKey, editable }: Props) {
  const { theme } = useTheme()
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [hint, setHint] = useState<string | null>(null)
  const [empty, setEmpty] = useState(false)
  const [adding, setAdding] = useState<AddKind | null>(null)
  // Edge-click menu (Insert remap / Unwire) + the edge being spliced.
  const [edgeMenu, setEdgeMenu] = useState<{ x: number; y: number; edge: Edge } | null>(null)
  const [inserting, setInserting] = useState<{ source: string; target: string } | null>(null)
  // Always-fresh snapshot of the wiring data, so rapid successive drags read the
  // latest inputs (not a stale render closure) and don't last-write-wins clobber.
  const dataRef = useRef<{ components: Component[]; routes: Route[]; stages: TransformStage[] }>({
    components: [],
    routes: [],
    stages: [],
  })
  // resource id → rendered Vector id, for the "tap this node" shortcut.
  const tapIdRef = useRef<Map<string, string>>(new Map())

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    // Tap-target ids are best-effort (used only for the click-to-tap shortcut);
    // a failure here must not block the topology from rendering.
    fleetsApi
      .tapTargets(fleetId)
      .then((r) => {
        tapIdRef.current = new Map(r.data.targets.map((t) => [t.resource_id, t.id]))
      })
      .catch(() => {})
    Promise.all([
      componentsApi.list({ fleet_id: fleetId }),
      routesApi.list(fleetId),
      transformStagesApi.list(fleetId),
    ])
      .then(([compRes, routeRes, stageRes]) => {
        const comps: Component[] = compRes.data.components ?? []
        const rts: Route[] = routeRes.data.routes ?? []
        const stgs: TransformStage[] = stageRes.data.stages ?? []
        dataRef.current = { components: comps, routes: rts, stages: stgs }
        onData?.({ components: comps, routes: rts, stages: stgs })
        if (comps.length === 0 && rts.length === 0 && stgs.length === 0) {
          setEmpty(true)
          setNodes([])
          setEdges([])
          return
        }
        setEmpty(false)
        const { nodes: n, edges: e } = buildFleetFlowGraph(comps, rts, stgs)
        setNodes(n)
        setEdges(e)
      })
      .catch(() => setError('Failed to load fleet topology'))
      .finally(() => setLoading(false))
  }, [fleetId, setNodes, setEdges, onData])

  useEffect(() => { load() }, [load, reloadKey])

  const flash = (msg: string) => { setHint(msg); setTimeout(() => setHint(null), 3500) }

  // Optimistic ref patches — applied right after a successful write so a rapid
  // next drag reads the new value (the trailing load() reconciles with the server).
  const patchSinkInputs = (id: string, inputs: string[]) => {
    dataRef.current.components = dataRef.current.components.map((c) => (c.id === id ? { ...c, inputs } : c))
  }
  const patchStageInputs = (id: string, inputs: string[]) => {
    dataRef.current.stages = dataRef.current.stages.map((x) => (x.id === id ? { ...x, inputs } : x))
  }
  const patchRouteSources = (id: string, source_ids: string[]) => {
    dataRef.current.routes = dataRef.current.routes.map((r) => (r.id === id ? { ...r, source_ids } : r))
  }

  // Adding src→target creates a cycle if src already reads target transitively.
  // Only remap stages have inputs, so cycles can only form among stages.
  const wouldCycle = useCallback((srcId: string, targetId: string): boolean => {
    const inputsOf = new Map(dataRef.current.stages.map((s) => [s.id, s.inputs]))
    const seen = new Set<string>()
    const stack = [srcId]
    while (stack.length) {
      const cur = stack.pop() as string
      if (cur === targetId) return true
      if (seen.has(cur)) continue
      seen.add(cur)
      const ins = inputsOf.get(cur)
      if (ins) stack.push(...ins)
    }
    return false
  }, [])

  // Drag an edge from an upstream node into a target → set the target's inputs.
  const onConnect = useCallback(
    async (conn: Connection) => {
      if (!editable || !conn.source || !conn.target || conn.source === conn.target) return
      const { components, routes, stages } = dataRef.current
      const s = parseNodeId(conn.source)
      const t = parseNodeId(conn.target)
      const compKind = (id: string) => components.find((c) => c.id === id)?.kind
      const srcIsUpstream = (s.kind === 'c' && compKind(s.id) === 'source') || s.kind === 's'
      // current inputs of the target (sink/stage) or source_ids (route)
      const current =
        t.kind === 'c'
          ? (components.find((c) => c.id === t.id)?.inputs ?? [])
          : t.kind === 's'
            ? (stages.find((x) => x.id === t.id)?.inputs ?? [])
            : (routes.find((x) => x.id === t.id)?.source_ids ?? [])
      if (current.includes(s.id)) return // already wired — no-op
      if (wouldCycle(s.id, t.id)) return flash('That would create a cycle.')
      const next = uniq([...current, s.id])
      try {
        if (t.kind === 'c' && compKind(t.id) === 'sink') {
          if (!srcIsUpstream) return flash('Wire a route to a sink in the route editor.')
          await componentsApi.update(t.id, { inputs: next })
          patchSinkInputs(t.id, next)
        } else if (t.kind === 's') {
          if (!srcIsUpstream) return flash('A remap reads from sources or other remaps.')
          await transformStagesApi.update(t.id, { inputs: next })
          patchStageInputs(t.id, next)
        } else if (t.kind === 'r') {
          if (!srcIsUpstream) return flash('A route reads from sources or remaps.')
          await routesApi.update(t.id, { source_ids: next })
          patchRouteSources(t.id, next)
        } else {
          return flash('That target has no inputs.')
        }
        load()
      } catch {
        flash('Wiring failed.')
        load()
      }
    },
    [editable, load, wouldCycle],
  )

  // Deleting an edge removes the corresponding input. Route→sink branch edges are
  // marked non-deletable in the builder (edit those in the route editor).
  const onEdgesDelete = useCallback(
    async (deleted: Edge[]) => {
      if (!editable) return
      const { components, routes, stages } = dataRef.current
      const compKind = (id: string) => components.find((c) => c.id === id)?.kind
      let failed = false
      for (const ed of deleted) {
        const s = parseNodeId(ed.source)
        const t = parseNodeId(ed.target)
        try {
          if (t.kind === 'c' && compKind(t.id) === 'sink') {
            const next = (components.find((c) => c.id === t.id)?.inputs ?? []).filter((i) => i !== s.id)
            await componentsApi.update(t.id, { inputs: next })
            patchSinkInputs(t.id, next)
          } else if (t.kind === 's') {
            const next = (stages.find((x) => x.id === t.id)?.inputs ?? []).filter((i) => i !== s.id)
            await transformStagesApi.update(t.id, { inputs: next })
            patchStageInputs(t.id, next)
          } else if (t.kind === 'r') {
            const next = (routes.find((x) => x.id === t.id)?.source_ids ?? []).filter((i) => i !== s.id)
            await routesApi.update(t.id, { source_ids: next })
            patchRouteSources(t.id, next)
          }
        } catch {
          failed = true
        }
      }
      if (failed) flash('Unwire failed for one or more edges.')
      load()
    },
    [editable, load],
  )

  const handleNodeClick = useCallback(
    (_: unknown, node: Node) => {
      setEdgeMenu(null)
      const d = node.data as FleetNodeData
      // Every node opens its editor in the drawer (build-in-place): routes → branch
      // editor, remaps → VRL editor, sources/sinks → catalog config form.
      if (d.kind === 'route' && d.routeId) {
        onRouteClick(d.routeId)
        return
      }
      if (d.kind === 'remap' && onEditRemap) {
        onEditRemap(parseNodeId(node.id).id)
        return
      }
      if ((d.kind === 'source' || d.kind === 'sink') && onConfigureComponent) {
        onConfigureComponent(parseNodeId(node.id).id)
      }
    },
    [onRouteClick, onEditRemap, onConfigureComponent],
  )

  // Dismiss the edge menu on Escape (pane click + node click cover the rest).
  useEffect(() => {
    if (!edgeMenu) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setEdgeMenu(null) }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [edgeMenu])

  // Click an edge → contextual menu (Insert remap / Unwire).
  const onEdgeClick = useCallback(
    (evt: React.MouseEvent, edge: Edge) => {
      if (!editable) return
      evt.stopPropagation()
      setEdgeMenu({ x: evt.clientX, y: evt.clientY, edge })
    },
    [editable],
  )

  // Remove the input behind a single edge (used by the menu's Unwire).
  const unwireEdge = useCallback(
    async (edge: Edge) => {
      const { components, routes, stages } = dataRef.current
      const s = parseNodeId(edge.source)
      const t = parseNodeId(edge.target)
      const compKind = (id: string) => components.find((c) => c.id === id)?.kind
      try {
        if (t.kind === 'c' && compKind(t.id) === 'sink') {
          const next = (components.find((c) => c.id === t.id)?.inputs ?? []).filter((i) => i !== s.id)
          await componentsApi.update(t.id, { inputs: next })
          patchSinkInputs(t.id, next)
        } else if (t.kind === 's') {
          const next = (stages.find((x) => x.id === t.id)?.inputs ?? []).filter((i) => i !== s.id)
          await transformStagesApi.update(t.id, { inputs: next })
          patchStageInputs(t.id, next)
        } else if (t.kind === 'r') {
          const next = (routes.find((x) => x.id === t.id)?.source_ids ?? []).filter((i) => i !== s.id)
          await routesApi.update(t.id, { source_ids: next })
          patchRouteSources(t.id, next)
        }
      } catch {
        flash('Unwire failed.')
      }
      load()
    },
    [load],
  )

  // Splice a remap into edge A→B: new stage reads A; B now reads the stage.
  const insertRemap = useCallback(
    async (sourceNodeId: string, targetNodeId: string, name: string, vrl: string) => {
      if (!editable) return
      const { components, routes, stages } = dataRef.current
      const srcId = parseNodeId(sourceNodeId).id
      const t = parseNodeId(targetNodeId)
      // Read the target's current inputs and confirm the edge still exists before
      // creating anything — avoids orphaning a stage on stale data.
      const currentInputs =
        t.kind === 'c'
          ? (components.find((c) => c.id === t.id)?.inputs ?? [])
          : t.kind === 's'
            ? (stages.find((x) => x.id === t.id)?.inputs ?? [])
            : (routes.find((x) => x.id === t.id)?.source_ids ?? [])
      if (!currentInputs.includes(srcId)) {
        flash('That edge is out of date — reopen the canvas and retry.')
        return
      }
      try {
        const res = await transformStagesApi.create({
          fleet_id: fleetId,
          name: name.trim(),
          mode: 'inline',
          source_vrl: vrl,
          inputs: [srcId],
        })
        const stageId = res.data?.id
        if (!stageId) {
          flash('Insert failed.')
          load()
          return
        }
        const next = currentInputs.map((i) => (i === srcId ? stageId : i))
        if (t.kind === 'c') await componentsApi.update(t.id, { inputs: next })
        else if (t.kind === 's') await transformStagesApi.update(t.id, { inputs: next })
        else await routesApi.update(t.id, { source_ids: next })
        load()
      } catch {
        flash('Insert failed.')
        load()
      }
    },
    [editable, fleetId, load],
  )

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="h-6 w-6 border-2 border-border border-t-primary rounded-full animate-spin" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="text-center space-y-2">
          <p className="text-sm text-destructive">{error}</p>
          <button onClick={load} className="text-xs text-muted-foreground hover:text-foreground transition-colors">
            Retry
          </button>
        </div>
      </div>
    )
  }

  const isDark = theme === 'dark'

  // The add buttons double as the colour legend: each dot is the same colour as
  // that kind's node tile (sourced from KIND_STYLES so they can't drift). The
  // "transform" button creates a `remap` node, hence the kind remap here.
  const palette = editable && (
    <div className="absolute top-2 left-2 z-10 flex items-center gap-1.5 bg-card/95 border border-border rounded-lg p-1 shadow-sm">
      {([
        ['source', '+ Source', 'source'],
        ['transform', '+ Transform', 'remap'],
        ['route', '+ Route', 'route'],
        ['sink', '+ Sink', 'sink'],
      ] as [AddKind, string, FleetNodeKind][]).map(([k, label, nodeKind]) => (
        <button
          key={k}
          onClick={() => { setEdgeMenu(null); setAdding(k) }}
          className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground hover:bg-secondary rounded px-2 py-1 transition-colors"
        >
          <span className={`h-2 w-2 rounded-full flex-shrink-0 ${KIND_STYLES[nodeKind].dot}`} aria-hidden="true" />
          {label}
        </button>
      ))}
    </div>
  )

  const addModal = adding && (
    <AddNodeModal
      kind={adding}
      fleetId={fleetId}
      onClose={() => setAdding(null)}
      onAdded={(createdId) => {
        load()
        if (createdId) onNodeCreated?.(createdId)
      }}
    />
  )

  const edgeMenuEl = editable && edgeMenu && (
    <div
      className="fixed z-50 bg-card border border-border rounded-lg shadow-lg py-1 text-xs min-w-[120px]"
      style={{ left: edgeMenu.x, top: edgeMenu.y }}
    >
      {parseNodeId(edgeMenu.edge.source).kind !== 'r' && (
        <button
          onClick={() => { setInserting({ source: edgeMenu.edge.source, target: edgeMenu.edge.target }); setEdgeMenu(null) }}
          className="block w-full text-left px-3 py-1.5 hover:bg-secondary text-foreground"
        >
          Insert remap…
        </button>
      )}
      {edgeMenu.edge.deletable !== false ? (
        <button
          onClick={() => { void unwireEdge(edgeMenu.edge); setEdgeMenu(null) }}
          className="block w-full text-left px-3 py-1.5 hover:bg-secondary text-destructive"
        >
          Unwire
        </button>
      ) : (
        <span className="block px-3 py-1.5 text-muted-foreground/50">Edit in route editor</span>
      )}
    </div>
  )

  const insertModal = inserting && (
    <InsertRemapModal
      onClose={() => setInserting(null)}
      onSubmit={async (name, vrl) => {
        await insertRemap(inserting.source, inserting.target, name, vrl)
        setInserting(null)
      }}
    />
  )

  if (empty) {
    return (
      <div className="flex-1 min-h-0 relative">
        {palette}
        <div className="h-full flex items-center justify-center px-8">
          <p className="text-sm text-muted-foreground text-center max-w-md">
            {editable
              ? 'Empty fleet. Use the palette (top-left) to add a source and sink, then drag between them to wire.'
              : 'Nothing to show yet. Add Sources and Sinks in the Catalog, then create a Route to wire them together.'}
          </p>
        </div>
        {addModal}
      </div>
    )
  }

  return (
    <div className="flex-1 min-h-0 relative">
      {palette}
      {editable && (
        <div className="absolute top-2 left-1/2 -translate-x-1/2 z-10 text-xs text-muted-foreground bg-card/90 border border-border rounded-full px-3 py-1 pointer-events-none">
          {hint ?? 'Drag from a node’s right edge to wire. Click an edge to insert a remap or unwire.'}
        </div>
      )}
      {addModal}
      {edgeMenuEl}
      {insertModal}
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={handleNodeClick}
        onEdgeClick={editable ? onEdgeClick : undefined}
        onPaneClick={() => setEdgeMenu(null)}
        onConnect={editable ? onConnect : undefined}
        onEdgesDelete={editable ? onEdgesDelete : undefined}
        nodesConnectable={!!editable}
        nodesDraggable
        deleteKeyCode={editable ? ['Backspace', 'Delete'] : null}
        nodeTypes={NODE_TYPES}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        proOptions={{ hideAttribution: true }}
        colorMode={isDark ? 'dark' : 'light'}
      >
        <Background
          variant={BackgroundVariant.Dots}
          gap={20}
          size={1}
          color={isDark ? '#27272a' : '#d4d4d8'}
        />
        <Controls className="!bg-card !border-border !shadow-none" showInteractive={false} />
        <MiniMap
          nodeColor={(n) => {
            const kind = (n.data as FleetNodeData)?.kind
            if (kind === 'source') return '#14b8a6'
            if (kind === 'remap') return '#38bdf8'
            if (kind === 'route') return '#8b5cf6'
            return '#f97316'
          }}
          maskColor={isDark ? 'rgba(9,9,11,0.7)' : 'rgba(250,250,250,0.7)'}
          className="!bg-card !border-border"
        />
      </ReactFlow>
    </div>
  )
}
