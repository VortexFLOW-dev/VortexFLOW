// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

import { memo } from 'react'
import { Handle, Position } from '@xyflow/react'
import type { NodeProps } from '@xyflow/react'
import type { TopologyComponent, ComponentKind } from '@/lib/topology'

const KIND_STYLES: Record<ComponentKind, { ring: string; dot: string; label: string }> = {
  source: {
    ring: 'border-primary/40',
    dot: 'bg-primary',
    label: 'text-primary',
  },
  transform: {
    ring: 'border-violet-500/40',
    dot: 'bg-violet-400',
    label: 'text-violet-500',
  },
  sink: {
    ring: 'border-orange-500/40',
    dot: 'bg-orange-400',
    label: 'text-orange-500',
  },
}

function throughputLabel(n: number | undefined): string | null {
  if (n === undefined || n === null) return null
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k/s`
  return `${n.toFixed(0)}/s`
}

export const ComponentNode = memo(({ data }: NodeProps) => {
  const component = data.component as TopologyComponent
  const style = KIND_STYLES[component.kind]

  const tput =
    component.outputs?.[0]?.sentEventsThroughput ??
    component.receivedEventsThroughput

  return (
    <div
      className={`w-[200px] bg-card border ${style.ring} rounded-xl px-4 py-3 shadow-lg select-none`}
    >
      {component.kind !== 'source' && (
        <Handle
          type="target"
          position={Position.Left}
          className="!w-2 !h-2 !bg-secondary !border-border"
        />
      )}

      <div className="flex items-start gap-2.5">
        <span className={`mt-1 h-2 w-2 rounded-full flex-shrink-0 ${style.dot}`} />
        <div className="min-w-0">
          <div className="text-xs font-medium text-foreground truncate leading-tight">
            {component.componentId}
          </div>
          <div className={`text-xs mt-0.5 ${style.label} truncate`}>
            {component.componentType}
          </div>
          {throughputLabel(tput) && (
            <div className="text-xs text-muted-foreground mt-1">{throughputLabel(tput)}</div>
          )}
        </div>
      </div>

      {component.kind !== 'sink' && (
        <Handle
          type="source"
          position={Position.Right}
          className="!w-2 !h-2 !bg-secondary !border-border"
        />
      )}
    </div>
  )
})

ComponentNode.displayName = 'ComponentNode'
