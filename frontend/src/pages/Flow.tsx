// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

import { useCallback, useEffect, useRef, useState } from 'react'
import { useFleet } from '@/lib/fleet'
import { useAuth } from '@/lib/auth'
import { routesApi, transformsApi, fleetsApi, instancesApi } from '@/lib/api'
import { deleteGuarded } from '@/lib/deleteGuard'
import { useCatalog } from '@/lib/useCatalog'
import type { Component, Route, RouteBranch, TransformStage, VrlTransform } from '@/lib/types'
import FleetTopologyCanvas from '@/components/topology/FleetTopologyCanvas'
import { RouteEditor } from '@/components/routes/RouteEditor'
import StageEditor from '@/components/transforms/StageEditor'
import { ComponentConfigForm } from '@/components/catalog/ComponentConfigForm'
import NodeWiring from '@/components/topology/NodeWiring'
import NodeTap from '@/components/topology/NodeTap'
import type { NodeRef } from '@/lib/wiring'

type TapTarget = { id: string; input_ids?: string[] }

type FleetData = { components: Component[]; routes: Route[]; stages: TransformStage[] }

// The visual flow builder — the canvas is the primary build surface. Click a node
// and its editor opens in a side drawer, so you configure, wire, and (soon) preview
// in place without leaving the canvas. Today: remap → VRL editor, route → branch
// editor; source/sink config drawer is P1b.
export default function Flow() {
  const { activeFleet } = useFleet()
  const { user } = useAuth()
  const canEdit = user?.role === 'admin' || user?.role === 'editor'
  const [editingRoute, setEditingRoute] = useState<Route | null>(null)
  const [editingStage, setEditingStage] = useState<TransformStage | null>(null)
  const [editingComponent, setEditingComponent] = useState<Component | null>(null)
  const [library, setLibrary] = useState<VrlTransform[]>([])
  const [reloadKey, setReloadKey] = useState(0)
  const [wide, setWide] = useState(false) // expand the drawer for more room to work
  const { sources: catalogSources, sinks: catalogSinks } = useCatalog()
  // Rendered Vector ids (+ input ids) per resource, and an instance to tap, so the
  // drawer's "Live output" can sample real events at the selected node.
  const [tapTargets, setTapTargets] = useState<Map<string, TapTarget>>(new Map())
  const [tapInstanceId, setTapInstanceId] = useState<string | null>(null)
  const fleetId = activeFleet?.id ?? null

  useEffect(() => {
    if (!fleetId) return
    fleetsApi
      .tapTargets(fleetId)
      .then((r) =>
        setTapTargets(
          new Map(r.data.targets.map((t) => [t.resource_id, { id: t.id, input_ids: t.input_ids }])),
        ),
      )
      .catch(() => setTapTargets(new Map()))
    instancesApi
      .list()
      .then((r) => {
        const list = (r.data ?? []) as { id: string; fleet_id: string | null }[]
        setTapInstanceId(list.find((i) => i.fleet_id === fleetId)?.id ?? null)
      })
      .catch(() => setTapInstanceId(null))
  }, [fleetId])

  // The canvas owns the components/routes/stages load; we mirror it (via a ref, so
  // node-click handlers read fresh data without re-subscribing) to feed the drawers.
  const dataRef = useRef<FleetData>({ components: [], routes: [], stages: [] })
  const dataLoadedRef = useRef(false)
  const [data, setData] = useState<FleetData>(dataRef.current)
  const onData = useCallback((d: FleetData) => {
    dataRef.current = d
    dataLoadedRef.current = true
    setData(d)
  }, [])

  useEffect(() => {
    transformsApi
      .list()
      .then((r) => setLibrary(r.data.transforms ?? []))
      .catch(() => setLibrary([]))
  }, [])

  const openRoute = async (id: string) => {
    try {
      const r = await routesApi.get(id)
      setEditingStage(null)
      setEditingComponent(null)
      setEditingRoute(r.data as Route)
    } catch {
      // route fetch failed — leave drawer closed
    }
  }

  const onEditRemap = useCallback((stageId: string) => {
    const s = dataRef.current.stages.find((x) => x.id === stageId)
    if (s) {
      setEditingRoute(null)
      setEditingComponent(null)
      setEditingStage(s)
    }
  }, [])

  const onConfigureComponent = useCallback((componentId: string) => {
    const c = dataRef.current.components.find((x) => x.id === componentId)
    if (c) {
      setEditingRoute(null)
      setEditingStage(null)
      setEditingComponent(c)
    }
  }, [])

  // Click a "Fed by / Feeds" chip → open that neighbour's drawer.
  const selectNeighbor = (r: NodeRef) => {
    if (r.kind === 'route') void openRoute(r.id)
    else if (r.kind === 'transform') onEditRemap(r.id)
    else onConfigureComponent(r.id)
  }

  // Deep-link: /flow?node=<id> opens that node's drawer once the canvas data has
  // loaded — e.g. "Open in Flow" from the Transforms list.
  const [pendingNode] = useState(() => new URLSearchParams(window.location.search).get('node'))
  const pendingHandledRef = useRef(false)
  useEffect(() => {
    // Wait until the canvas has loaded the fleet's data, then resolve the node
    // once. Clean the URL whether or not it was found (a stale/wrong-fleet id
    // shouldn't keep retrying or linger in the address bar).
    if (!pendingNode || pendingHandledRef.current || !dataLoadedRef.current) return
    const g = dataRef.current
    if (g.components.some((c) => c.id === pendingNode)) onConfigureComponent(pendingNode)
    else if (g.stages.some((s) => s.id === pendingNode)) onEditRemap(pendingNode)
    else if (g.routes.some((r) => r.id === pendingNode)) void openRoute(pendingNode)
    pendingHandledRef.current = true
    window.history.replaceState({}, '', '/flow')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingNode, data])

  // A node added via the palette → open its drawer once the canvas reload brings
  // it into `data`, so add → configure is one motion.
  const [justCreatedId, setJustCreatedId] = useState<string | null>(null)
  useEffect(() => {
    if (!justCreatedId) return
    const g = dataRef.current
    if (g.components.some((c) => c.id === justCreatedId)) onConfigureComponent(justCreatedId)
    else if (g.stages.some((s) => s.id === justCreatedId)) onEditRemap(justCreatedId)
    else if (g.routes.some((r) => r.id === justCreatedId)) void openRoute(justCreatedId)
    else return // not in data yet — wait for the next canvas reload
    setJustCreatedId(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, justCreatedId])

  const saveRoute = async (d: {
    name: string
    fleet_id: string
    description: string
    branches: RouteBranch[]
    source_ids: string[]
    passthrough_sink_ids: string[]
  }) => {
    if (!editingRoute) return
    const res = await routesApi.update(editingRoute.id, {
      name: d.name,
      description: d.description,
      branches: d.branches,
      source_ids: d.source_ids,
      passthrough_sink_ids: d.passthrough_sink_ids,
    })
    setEditingRoute(res.data as Route)
    setReloadKey((n) => n + 1)
  }

  const deleteRoute = async () => {
    if (!editingRoute) return
    const id = editingRoute.id
    if (await deleteGuarded((force) => routesApi.delete(id, force))) {
      setEditingRoute(null)
      setReloadKey((n) => n + 1)
    }
  }

  if (!activeFleet) {
    return (
      <div className="flex-1 flex items-center justify-center text-sm text-muted-foreground">
        Select a fleet to build its flow.
      </div>
    )
  }

  const sources = data.components.filter((c) => c.kind === 'source')
  // The catalog schema (fields) for the component being configured, looked up by
  // its saved component_type — drives the guided config form in the drawer.
  const componentDef = editingComponent
    ? (editingComponent.kind === 'source' ? catalogSources : catalogSinks).find(
        (c) => c.type === editingComponent.component_type,
      )
    : undefined

  // Drawer chrome — a roomy default, expandable to ~full for the VRL editor /
  // config forms, restorable.
  const drawerCls = `${wide ? 'w-[60vw] max-w-[1100px]' : 'w-[560px]'} flex-shrink-0 flex flex-col overflow-hidden border-l border-border bg-card`
  const widthBar = (
    <div className="flex-shrink-0 flex justify-end px-2 py-1.5 border-b border-border bg-secondary/40">
      <button
        onClick={() => setWide((w) => !w)}
        title={wide ? 'Collapse panel' : 'Expand panel for more room'}
        className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground hover:text-foreground px-2 py-1 rounded border border-border hover:bg-secondary transition-colors"
      >
        <span className="text-sm leading-none">{wide ? '⤡' : '⤢'}</span>
        {wide ? 'Collapse' : 'Expand'}
      </button>
    </div>
  )

  return (
    <div className="flex flex-col h-full">
      <div className="flex-shrink-0 border-b border-border bg-card px-6 py-4">
        <h1 className="text-base font-semibold text-foreground">Flow</h1>
        <p className="text-xs text-muted-foreground mt-0.5">
          Build <span className="text-foreground font-medium">{activeFleet.name}</span> visually — add nodes, drag to wire, click an edge to insert a remap. Click any node to configure it in place.
        </p>
      </div>
      <div className="flex flex-1 min-h-0">
        <div className="flex-1 min-w-0 flex">
          <FleetTopologyCanvas
            fleetId={activeFleet.id}
            editable={canEdit}
            reloadKey={reloadKey}
            onData={onData}
            onRouteClick={(id) => { void openRoute(id) }}
            onEditRemap={onEditRemap}
            onConfigureComponent={onConfigureComponent}
            onNodeCreated={setJustCreatedId}
          />
        </div>
        {editingRoute && (
          <div className={drawerCls}>
            {widthBar}
            <NodeWiring nodeId={editingRoute.id} graph={data} onSelect={selectNeighbor} />
            <div className="flex-1 min-h-0 flex flex-col [&>*]:flex-1 [&>*]:min-h-0 [&>*]:w-full">
              <RouteEditor
                key={editingRoute.id}
                route={editingRoute}
                fleets={[activeFleet]}
                canEdit={canEdit}
                onSave={saveRoute}
                onDelete={deleteRoute}
                onClose={() => setEditingRoute(null)}
              />
            </div>
            <NodeTap
              key={editingRoute.id}
              instanceId={tapInstanceId}
              vectorId={tapTargets.get(editingRoute.id)?.id}
              nodeName={editingRoute.name}
            />
          </div>
        )}
        {editingStage && (
          <div className={drawerCls}>
            {widthBar}
            <NodeWiring nodeId={editingStage.id} graph={data} onSelect={selectNeighbor} />
            <div className="flex-1 min-h-0 flex flex-col [&>*]:flex-1 [&>*]:min-h-0 [&>*]:w-full">
              <StageEditor
                key={editingStage.id}
                stage={editingStage}
                fleetId={activeFleet.id}
                sources={sources}
                stages={data.stages}
                library={library}
                canEdit={canEdit}
                onSaved={() => setReloadKey((n) => n + 1)}
                onDeleted={() => { setEditingStage(null); setReloadKey((n) => n + 1) }}
                onClose={() => setEditingStage(null)}
              />
            </div>
            <NodeTap
              key={editingStage.id}
              instanceId={tapInstanceId}
              vectorId={tapTargets.get(editingStage.id)?.id}
              inputIds={tapTargets.get(editingStage.id)?.input_ids}
              nodeName={editingStage.name}
            />
          </div>
        )}
        {editingComponent && componentDef && (
          <div className={drawerCls}>
            {widthBar}
            <NodeWiring nodeId={editingComponent.id} graph={data} onSelect={selectNeighbor} />
            <div className="flex-1 min-h-0 flex flex-col [&>*]:flex-1 [&>*]:min-h-0 [&>*]:w-full">
              <ComponentConfigForm
                key={editingComponent.id}
                component={componentDef}
                kind={editingComponent.kind === 'source' ? 'sources' : 'sinks'}
                existing={editingComponent}
                onClose={() => setEditingComponent(null)}
                onSaved={() => setReloadKey((n) => n + 1)}
              />
            </div>
            {editingComponent.kind === 'source' && (
              <NodeTap
                key={editingComponent.id}
                instanceId={tapInstanceId}
                vectorId={tapTargets.get(editingComponent.id)?.id}
                nodeName={editingComponent.name}
              />
            )}
          </div>
        )}
      </div>
    </div>
  )
}
