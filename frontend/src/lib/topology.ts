// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

import dagre from '@dagrejs/dagre'
import type { Node, Edge } from '@xyflow/react'

export type ComponentKind = 'source' | 'transform' | 'sink'

export interface TopologyComponent {
  componentId: string
  componentType: string
  kind: ComponentKind
  inputs?: Array<{ componentId: string }>
  outputs?: Array<{
    outputId: string
    receivedEventsThroughput?: number
    sentEventsThroughput?: number
  }>
  receivedEventsThroughput?: number
}

export interface TopologyData {
  components: TopologyComponent[]
}

// Detect component kind from the GraphQL union type fields:
// Sources have no inputs field; Sinks have no outputs field.
function detectKind(raw: Record<string, unknown>): ComponentKind {
  if (!('inputs' in raw)) return 'source'
  if (!('outputs' in raw)) return 'sink'
  return 'transform'
}

export function parseTopology(data: Record<string, unknown>): TopologyComponent[] {
  const rawComponents = (data?.components as Record<string, unknown>[]) ?? []
  return rawComponents.map((c) => ({
    componentId: c.componentId as string,
    componentType: c.componentType as string,
    kind: detectKind(c),
    inputs: c.inputs as TopologyComponent['inputs'],
    outputs: c.outputs as TopologyComponent['outputs'],
    receivedEventsThroughput: c.receivedEventsThroughput as number | undefined,
  }))
}

const NODE_WIDTH = 200
const NODE_HEIGHT = 72

export function buildFlowGraph(components: TopologyComponent[]): {
  nodes: Node[]
  edges: Edge[]
} {
  const g = new dagre.graphlib.Graph()
  g.setDefaultEdgeLabel(() => ({}))
  g.setGraph({ rankdir: 'LR', nodesep: 40, ranksep: 80, marginx: 24, marginy: 24 })

  components.forEach((c) => {
    g.setNode(c.componentId, { width: NODE_WIDTH, height: NODE_HEIGHT })
  })

  components.forEach((c) => {
    c.inputs?.forEach((input) => {
      g.setEdge(input.componentId, c.componentId)
    })
  })

  dagre.layout(g)

  const nodes: Node[] = components.map((c) => {
    const pos = g.node(c.componentId)
    return {
      id: c.componentId,
      type: 'vectorComponent',
      position: { x: pos.x - NODE_WIDTH / 2, y: pos.y - NODE_HEIGHT / 2 },
      data: { component: c },
    }
  })

  const edges: Edge[] = []
  g.edges().forEach((e) => {
    edges.push({
      id: `${e.v}->${e.w}`,
      source: e.v,
      target: e.w,
      type: 'smoothstep',
      style: { stroke: '#3f3f46', strokeWidth: 1.5 },
      animated: false,
    })
  })

  return { nodes, edges }
}
