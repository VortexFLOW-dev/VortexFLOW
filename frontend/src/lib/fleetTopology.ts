// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

import dagre from '@dagrejs/dagre'
import type { Node, Edge } from '@xyflow/react'
import type { Component, Route, TransformStage } from '@/lib/types'

// Designed-topology node kinds (from our DB, not Vector's live API).
export type FleetNodeKind = 'source' | 'remap' | 'route' | 'sink'

export interface FleetNodeData {
  kind: FleetNodeKind
  label: string // component / stage / route name
  subLabel: string // component_type / branch summary / "remap"
  routeId?: string // set for route nodes — click target
  stageId?: string // set for remap nodes
  orphan: boolean // not wired to anything
  [key: string]: unknown
}

const NODE_WIDTH = 200
const NODE_HEIGHT = 72

const compNodeId = (id: string) => `c:${id}`
const routeNodeId = (id: string) => `r:${id}`
const stageNodeId = (id: string) => `s:${id}`

const EDGE_STYLE = { stroke: '#3f3f46', strokeWidth: 1.5 }

/**
 * Build a ReactFlow graph for a single fleet's *designed* topology from DB
 * resources: sources → (remap stages) → routes / sinks. Wiring is by id:
 * routes read source_ids; sinks accept route-branch outputs AND direct inputs
 * (quick-connect / fan-out); remap stages read their inputs. Unwired resources
 * render as orphan nodes so operators can see what isn't hooked up.
 */
export function buildFleetFlowGraph(
  components: Component[],
  routes: Route[],
  stages: TransformStage[] = [],
): { nodes: Node[]; edges: Edge[] } {
  const sources = components.filter((c) => c.kind === 'source')
  const sinks = components.filter((c) => c.kind === 'sink')
  const sinkById = new Map(sinks.map((s) => [s.id, s]))
  const sourceById = new Map(sources.map((s) => [s.id, s]))
  const stageById = new Map(stages.map((s) => [s.id, s]))

  // Node id for an upstream resource id (source component or remap stage).
  const upstreamNode = (id: string): string | null =>
    sourceById.has(id) ? compNodeId(id) : stageById.has(id) ? stageNodeId(id) : null

  // Every node id that appears in at least one edge → not an orphan.
  const connected = new Set<string>()

  const g = new dagre.graphlib.Graph()
  g.setDefaultEdgeLabel(() => ({}))
  g.setGraph({ rankdir: 'LR', nodesep: 40, ranksep: 90, marginx: 24, marginy: 24 })

  for (const c of components) g.setNode(compNodeId(c.id), { width: NODE_WIDTH, height: NODE_HEIGHT })
  for (const s of stages) g.setNode(stageNodeId(s.id), { width: NODE_WIDTH, height: NODE_HEIGHT })
  for (const r of routes) g.setNode(routeNodeId(r.id), { width: NODE_WIDTH, height: NODE_HEIGHT })

  const edges: Edge[] = []
  // `slot` discriminates edges that share source+target but differ in meaning
  // so React Flow edge ids never collide.
  const addEdge = (
    source: string,
    target: string,
    slot: string,
    label?: string,
    deletable = true,
  ) => {
    edges.push({
      id: `${source}->${target}:${slot}`,
      source,
      target,
      type: 'smoothstep',
      style: EDGE_STYLE,
      label,
      labelStyle: { fill: '#71717a', fontSize: 10 },
      labelBgStyle: { fill: 'transparent' },
      // Route→sink branch edges are edited in the route editor, not by deleting
      // an edge on the canvas.
      deletable,
    })
    g.setEdge(source, target)
    connected.add(source)
    connected.add(target)
  }

  const uniq = (a: string[]) => Array.from(new Set(a))

  // upstream → remap stage
  for (const st of stages) {
    for (const iid of uniq(st.inputs)) {
      const src = upstreamNode(iid)
      if (src) addEdge(src, stageNodeId(st.id), 'in')
    }
  }

  // routes
  for (const r of routes) {
    const rn = routeNodeId(r.id)
    for (const sid of uniq(r.source_ids)) {
      const src = upstreamNode(sid)
      if (src) addEdge(src, rn, 'in')
    }
    r.branches.forEach((b, bi) => {
      for (const sinkId of b.sink_ids) {
        if (!sinkById.has(sinkId)) continue
        addEdge(rn, compNodeId(sinkId), `b${bi}`, b.name, false)
      }
    })
    for (const sinkId of r.passthrough_sink_ids) {
      if (!sinkById.has(sinkId)) continue
      addEdge(rn, compNodeId(sinkId), 'pt', '_unmatched', false)
    }
  }

  // direct upstream → sink (quick-connect / fan-out, no route)
  for (const sk of sinks) {
    for (const iid of uniq(sk.inputs ?? [])) {
      const src = upstreamNode(iid)
      if (src) addEdge(src, compNodeId(sk.id), 'direct')
    }
  }

  dagre.layout(g)

  const nodes: Node[] = []
  const pushNode = (id: string, data: FleetNodeData) => {
    const pos = g.node(id)
    nodes.push({
      id,
      type: 'fleetNode',
      position: { x: pos.x - NODE_WIDTH / 2, y: pos.y - NODE_HEIGHT / 2 },
      data,
    })
  }

  for (const c of components) {
    pushNode(compNodeId(c.id), {
      kind: c.kind,
      label: c.name,
      subLabel: c.component_type,
      orphan: !connected.has(compNodeId(c.id)),
    })
  }
  for (const st of stages) {
    pushNode(stageNodeId(st.id), {
      kind: 'remap',
      label: st.name,
      subLabel: st.mode === 'library' ? 'remap · library' : 'remap',
      stageId: st.id,
      orphan: !connected.has(stageNodeId(st.id)),
    })
  }
  for (const r of routes) {
    const n = r.branches.length
    pushNode(routeNodeId(r.id), {
      kind: 'route',
      label: r.name,
      subLabel: `${n} ${n === 1 ? 'branch' : 'branches'} + passthrough`,
      routeId: r.id,
      orphan: r.source_ids.length === 0,
    })
  }

  return { nodes, edges }
}
