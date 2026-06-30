// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

import { memo } from 'react'
import { Handle, Position } from '@xyflow/react'
import type { NodeProps } from '@xyflow/react'
import type { FleetNodeData, FleetNodeKind } from '@/lib/fleetTopology'

export const KIND_STYLES: Record<FleetNodeKind, { ring: string; dot: string; label: string }> = {
  source: { ring: 'border-primary/40', dot: 'bg-primary', label: 'text-primary' },
  remap: { ring: 'border-sky-500/40', dot: 'bg-sky-400', label: 'text-sky-500' },
  route: { ring: 'border-violet-500/40', dot: 'bg-violet-400', label: 'text-violet-500' },
  sink: { ring: 'border-orange-500/40', dot: 'bg-orange-400', label: 'text-orange-500' },
}

export const FleetNode = memo(({ data }: NodeProps) => {
  const d = data as FleetNodeData
  const style = KIND_STYLES[d.kind]
  const clickable = d.kind === 'route'

  return (
    <div
      className={`w-[200px] bg-card border ${style.ring} rounded-xl px-4 py-3 shadow-lg select-none ${
        d.orphan ? 'opacity-50' : ''
      } ${clickable ? 'cursor-pointer hover:ring-1 hover:ring-violet-500/40 transition-all' : ''}`}
    >
      {d.kind !== 'source' && (
        <Handle type="target" position={Position.Left} className="!w-2 !h-2 !bg-secondary !border-border" />
      )}

      <div className="flex items-start gap-2.5">
        <span className={`mt-1 h-2 w-2 rounded-full flex-shrink-0 ${style.dot}`} />
        <div className="min-w-0">
          <div className="text-xs font-medium text-foreground truncate leading-tight">{d.label}</div>
          <div className={`text-xs mt-0.5 ${style.label} truncate`}>{d.subLabel}</div>
          {d.orphan && <div className="text-xs text-muted-foreground/60 mt-1">not wired</div>}
          {clickable && !d.orphan && (
            <div className="text-xs text-muted-foreground/60 mt-1">click to edit</div>
          )}
        </div>
      </div>

      {d.kind !== 'sink' && (
        <Handle type="source" position={Position.Right} className="!w-2 !h-2 !bg-secondary !border-border" />
      )}
    </div>
  )
})

FleetNode.displayName = 'FleetNode'
