// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

import { useEffect, useState, useCallback } from 'react'
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  BackgroundVariant,
} from '@xyflow/react'
import type { Node, Edge } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { instancesApi } from '@/lib/api'
import { parseTopology, buildFlowGraph } from '@/lib/topology'
import { ComponentNode } from './ComponentNode'
import { useTheme } from '@/lib/theme'

const NODE_TYPES = { vectorComponent: ComponentNode }

interface Props {
  instanceId: string
  instanceLabel: string
}

export default function TopologyCanvas({ instanceId, instanceLabel }: Props) {
  const { theme } = useTheme()
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [componentCount, setComponentCount] = useState(0)

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    instancesApi
      .topology(instanceId)
      .then((r) => {
        const components = parseTopology(r.data)
        setComponentCount(components.length)
        if (components.length === 0) {
          setNodes([])
          setEdges([])
          return
        }
        const { nodes: n, edges: e } = buildFlowGraph(components)
        setNodes(n)
        setEdges(e)
      })
      .catch((err) => {
        const msg = err?.response?.data?.detail ?? 'Could not reach Vector API'
        setError(msg)
      })
      .finally(() => setLoading(false))
  }, [instanceId, setNodes, setEdges])

  useEffect(() => { load() }, [load])

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="flex flex-col items-center gap-3">
          <div className="h-6 w-6 border-2 border-border border-t-primary rounded-full animate-spin" />
          <p className="text-xs text-muted-foreground">Fetching topology from {instanceLabel}…</p>
        </div>
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

  if (componentCount === 0) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <p className="text-sm text-muted-foreground">
          No components found in {instanceLabel}. Add sources, transforms, and sinks to your Vector
          config to see the topology here.
        </p>
      </div>
    )
  }

  const isDark = theme === 'dark'

  return (
    <div className="flex-1 min-h-0">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
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
        <Controls
          className="!bg-card !border-border !shadow-none"
          showInteractive={false}
        />
        <MiniMap
          nodeColor={(n) => {
            const kind = (n.data?.component as { kind: string })?.kind
            if (kind === 'source') return '#14b8a6'
            if (kind === 'transform') return '#8b5cf6'
            return '#f97316'
          }}
          maskColor={isDark ? 'rgba(9,9,11,0.7)' : 'rgba(250,250,250,0.7)'}
          className="!bg-card !border-border"
        />
      </ReactFlow>
    </div>
  )
}
