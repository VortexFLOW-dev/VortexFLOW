// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

/**
 * NodeWiring — a compact "Fed by → / → Feeds" strip for the Flow node drawer.
 * Shows what a node reads from and what reads it (computed client-side from the
 * loaded fleet graph); each chip is clickable to jump to that neighbour's drawer.
 */

import type { FleetGraph, NodeKind, NodeRef } from '@/lib/wiring'
import { feeds, fedBy } from '@/lib/wiring'

const KIND_DOT: Record<NodeKind, string> = {
  source: 'bg-teal-500',
  transform: 'bg-sky-400',
  route: 'bg-violet-500',
  sink: 'bg-orange-500',
}

function Chip({ ref, onSelect }: { ref: NodeRef; onSelect?: (r: NodeRef) => void }) {
  return (
    <button
      type="button"
      onClick={() => onSelect?.(ref)}
      disabled={!onSelect}
      title={`${ref.name} · ${ref.kind}`}
      className="inline-flex items-center gap-1 max-w-[160px] bg-secondary/70 hover:bg-secondary rounded px-1.5 py-0.5 text-[11px] text-foreground/80 transition-colors disabled:cursor-default"
    >
      <span className={`h-1.5 w-1.5 rounded-full flex-shrink-0 ${KIND_DOT[ref.kind]}`} />
      <span className="truncate">{ref.name}</span>
    </button>
  )
}

export default function NodeWiring({
  nodeId,
  graph,
  onSelect,
}: {
  nodeId: string
  graph: FleetGraph
  onSelect?: (r: NodeRef) => void
}) {
  const inputs = fedBy(graph, nodeId)
  const consumers = feeds(graph, nodeId)
  if (inputs.length === 0 && consumers.length === 0) return null

  return (
    <div className="flex-shrink-0 border-b border-border bg-background/40 px-4 py-2 space-y-1.5">
      {inputs.length > 0 && (
        <div className="flex items-start gap-2">
          <span className="text-[11px] text-muted-foreground/70 w-12 flex-shrink-0 pt-0.5">Fed by</span>
          <div className="flex flex-wrap gap-1">
            {inputs.map((r) => (
              <Chip key={`in-${r.id}`} ref={r} onSelect={onSelect} />
            ))}
          </div>
        </div>
      )}
      {consumers.length > 0 && (
        <div className="flex items-start gap-2">
          <span className="text-[11px] text-muted-foreground/70 w-12 flex-shrink-0 pt-0.5">Feeds</span>
          <div className="flex flex-wrap gap-1">
            {consumers.map((r) => (
              <Chip key={`out-${r.id}`} ref={r} onSelect={onSelect} />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
