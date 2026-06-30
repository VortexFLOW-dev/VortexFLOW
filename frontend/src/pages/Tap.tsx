// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

import { useEffect, useState } from 'react'
import { instancesApi } from '@/lib/api'
import type { Instance } from '@/lib/types'
import { useFleet } from '@/lib/fleet'
import LiveTap from '@/components/shared/LiveTap'
import PageHeader from '@/components/ui/PageHeader'

export default function TapPage() {
  const { activeFleet } = useFleet()
  const [instances, setInstances] = useState<Instance[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    instancesApi
      .list()
      .then((res) => setInstances(res.data as Instance[]))
      .catch(() => setError('Failed to load instances'))
      .finally(() => setLoading(false))
  }, [])

  // Live Tap is fleet-scoped: only show instances in the active fleet.
  const members = activeFleet
    ? instances.filter((i) => i.fleet_id === activeFleet.id)
    : []

  return (
    <div className="p-6 space-y-6">
      <PageHeader
        title="Live Tap"
        description={`Stream live output events from a Vector component in ${
          activeFleet?.name ?? 'the active fleet'
        }, in real time. Zero retention — sampled directly from the running pipeline.`}
      />

      {loading && (
        <div className="space-y-3">
          {[...Array(2)].map((_, i) => (
            <div key={i} className="bg-card border border-border rounded-xl h-16 animate-pulse" />
          ))}
        </div>
      )}
      {error && (
        <div className="bg-destructive/10 border border-destructive/30 text-destructive rounded-lg px-4 py-3 text-sm">
          {error}
        </div>
      )}
      {!loading && !error && !activeFleet && (
        <div className="text-sm text-muted-foreground">Select a fleet to tap its instances.</div>
      )}
      {!loading && !error && activeFleet && members.length === 0 && (
        <div className="text-sm text-muted-foreground">
          No instances in <span className="text-foreground font-medium">{activeFleet.name}</span> yet.
        </div>
      )}
      {!loading && activeFleet && members.length > 0 && (
        <LiveTap key={activeFleet.id} instances={members} />
      )}
    </div>
  )
}
