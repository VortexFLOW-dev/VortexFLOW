// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

import { useEffect, useState } from 'react'
import { useFleet } from '@/lib/fleet'
import { fleetsApi } from '@/lib/api'
import type { FleetWithInstances } from '@/lib/types'

function FleetIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75} className="h-3.5 w-3.5 flex-shrink-0 text-muted-foreground/60">
      <path d="M12 2L2 7l10 5 10-5-10-5z" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M2 17l10 5 10-5M2 12l10 5 10-5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function Chip({ label, value }: { label: string; value: string | number }) {
  return (
    <span className="flex items-center gap-1 text-xs text-muted-foreground/70 bg-secondary/60 rounded-md px-2 py-0.5">
      <span className="text-muted-foreground/40">{label}</span>
      <span className="font-medium text-foreground/70">{value}</span>
    </span>
  )
}

export default function TopBar() {
  const { activeFleet } = useFleet()
  const [detail, setDetail] = useState<FleetWithInstances | null>(null)

  useEffect(() => {
    if (!activeFleet) { setDetail(null); return }
    fleetsApi.get(activeFleet.id)
      .then((r) => setDetail(r.data))
      .catch(() => setDetail(null))
  }, [activeFleet?.id])

  const instances = detail?.instances ?? []
  const agentCount = instances.filter((i) => i.role === 'agent').length
  const aggregatorCount = instances.filter((i) => i.role === 'aggregator').length
  const totalCount = instances.length

  return (
    <div className="h-14 flex-shrink-0 bg-background border-b border-border flex items-center px-5 gap-4">
      {activeFleet ? (
        <>
          <div className="flex items-center gap-2 min-w-0">
            <FleetIcon />
            <span className="text-sm font-semibold text-foreground truncate">
              {activeFleet.name}
            </span>
            {activeFleet.is_default && (
              <span className="text-[10px] text-muted-foreground/50 bg-secondary rounded px-1.5 py-0.5 flex-shrink-0">
                default
              </span>
            )}
          </div>

          {totalCount > 0 ? (
            <div className="flex items-center gap-1.5 flex-shrink-0">
              {agentCount > 0 && <Chip label="agents" value={agentCount} />}
              {aggregatorCount > 0 && <Chip label="agg" value={aggregatorCount} />}
              {agentCount === 0 && aggregatorCount === 0 && (
                <Chip label="instances" value={totalCount} />
              )}
            </div>
          ) : detail !== null ? (
            <span className="text-xs text-muted-foreground/50">No instances</span>
          ) : null}
        </>
      ) : (
        <span className="text-sm text-muted-foreground/50">No fleet selected</span>
      )}

      {/* Right side — page breadcrumb portal target, kept for future use */}
      <div className="flex-1 min-w-0" id="topbar-breadcrumb" />
    </div>
  )
}
