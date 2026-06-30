// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from 'react'
import { fleetsApi } from '@/lib/api'
import type { Fleet } from '@/lib/types'

interface FleetContextValue {
  fleets: Fleet[]
  activeFleet: Fleet | null
  setActiveFleet: (s: Fleet) => void
  loading: boolean
}

const FleetContext = createContext<FleetContextValue | null>(null)

const STORAGE_KEY = 'vf-fleet-id'

function readStoredFleetId(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY)
  } catch {
    return null
  }
}

function writeStoredFleetId(id: string): void {
  try {
    localStorage.setItem(STORAGE_KEY, id)
  } catch {
    // storage unavailable — selection still works for the session
  }
}

export function FleetProvider({ children }: { children: ReactNode }) {
  const [fleets, setFleets] = useState<Fleet[]>([])
  const [activeFleet, setActiveFleetState] = useState<Fleet | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const token = localStorage.getItem('access_token')
    if (!token) {
      setLoading(false)
      return
    }

    fleetsApi
      .list()
      .then(({ data }) => {
        const list = data.fleets ?? []
        setFleets(list)

        const storedId = readStoredFleetId()
        const match = storedId ? list.find((s) => s.id === storedId) ?? null : null
        const fallback = list.find((s) => s.is_default) ?? list[0] ?? null
        setActiveFleetState(match ?? fallback)
      })
      .catch(() => {
        // Non-fatal — fleets stay empty, user can still use the app
      })
      .finally(() => setLoading(false))
  }, [])

  const setActiveFleet = (s: Fleet) => {
    setActiveFleetState(s)
    writeStoredFleetId(s.id)
  }

  return (
    <FleetContext.Provider value={{ fleets, activeFleet, setActiveFleet, loading }}>
      {children}
    </FleetContext.Provider>
  )
}

export function useFleet(): FleetContextValue {
  const ctx = useContext(FleetContext)
  if (!ctx) throw new Error('useFleet must be used within FleetProvider')
  return ctx
}
