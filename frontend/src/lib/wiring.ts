// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

/**
 * Client-side wiring graph helpers — the mirror of the backend `find_references`,
 * computed from the fleet data the Flow canvas already loads. Used by the node
 * drawer to show "Fed by" (a node's inputs) and "Feeds" (its consumers).
 */

import type { Component, Route, TransformStage } from '@/lib/types'

export interface FleetGraph {
  components: Component[]
  routes: Route[]
  stages: TransformStage[]
}

export type NodeKind = 'source' | 'sink' | 'transform' | 'route'
export interface NodeRef {
  kind: NodeKind
  id: string
  name: string
}

function matchesTarget(ids: string[] | undefined, targetId: string): boolean {
  return (ids ?? []).some((i) => i === targetId || i.startsWith(`${targetId}.`))
}

/** Resolve an id (component / stage / route, or a `routeId.branch` output) to a NodeRef. */
export function resolve(g: FleetGraph, id: string): NodeRef | null {
  const c = g.components.find((x) => x.id === id)
  if (c) return { kind: c.kind, id: c.id, name: c.name }
  const s = g.stages.find((x) => x.id === id)
  if (s) return { kind: 'transform', id: s.id, name: s.name }
  const r = g.routes.find((x) => x.id === id)
  if (r) return { kind: 'route', id: r.id, name: r.name }
  if (id.includes('.')) {
    const base = id.split('.')[0]
    const rr = g.routes.find((x) => x.id === base)
    if (rr) return { kind: 'route', id: rr.id, name: `${rr.name} → ${id.split('.').slice(1).join('.')}` }
  }
  return null
}

/** Nodes that read this node's output (consumers) — reverse of the wiring. */
export function feeds(g: FleetGraph, targetId: string): NodeRef[] {
  const out: NodeRef[] = []
  for (const c of g.components)
    if (c.id !== targetId && matchesTarget(c.inputs, targetId))
      out.push({ kind: c.kind, id: c.id, name: c.name })
  for (const s of g.stages)
    if (s.id !== targetId && matchesTarget(s.inputs, targetId))
      out.push({ kind: 'transform', id: s.id, name: s.name })
  for (const r of g.routes) {
    if (r.id === targetId) continue
    const ids = [
      ...(r.source_ids ?? []),
      ...(r.passthrough_sink_ids ?? []),
      ...(r.branches ?? []).flatMap((b) => b.sink_ids ?? []),
    ]
    if (matchesTarget(ids, targetId)) out.push({ kind: 'route', id: r.id, name: r.name })
  }
  return out
}

/** What feeds this node (its declared inputs), resolved to names. */
export function fedBy(g: FleetGraph, targetId: string): NodeRef[] {
  const inputIds =
    g.components.find((c) => c.id === targetId)?.inputs ??
    g.stages.find((s) => s.id === targetId)?.inputs ??
    g.routes.find((r) => r.id === targetId)?.source_ids ??
    []
  return inputIds.map((id) => resolve(g, id) ?? { kind: 'source', id, name: id })
}
