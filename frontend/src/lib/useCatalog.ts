// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

import { useCallback, useEffect, useState } from 'react'
import { catalogApi } from './api'
import { SOURCES, SINKS, buildCatalogFromSchema, type CatalogComponent } from './catalog'

export interface CatalogState {
  sources: CatalogComponent[]
  sinks: CatalogComponent[]
  /** Vector version the live catalog came from, or null when using the bundle. */
  vectorVersion: string | null
  /** True when built from the deployed Vector; false = bundled fallback. */
  live: boolean
  loading: boolean
  refresh: () => Promise<void>
}

/**
 * The source/sink catalog. Tries the deployed Vector's live schema (so it tracks
 * the running version with no rebuild); falls back to the catalog bundled in the
 * app when Vector isn't available (e.g. dev, or an older image).
 */
export function useCatalog(): CatalogState {
  const [sources, setSources] = useState<CatalogComponent[]>(SOURCES)
  const [sinks, setSinks] = useState<CatalogComponent[]>(SINKS)
  const [vectorVersion, setVectorVersion] = useState<string | null>(null)
  const [live, setLive] = useState(false)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async (force: boolean) => {
    setLoading(true)
    try {
      if (force) await catalogApi.refresh()
      const res = await catalogApi.schema(force)
      const version =
        (res.headers['x-vector-version'] as string | undefined) || null
      const built = buildCatalogFromSchema(res.data)
      setSources(built.sources)
      setSinks(built.sinks)
      setVectorVersion(version)
      setLive(true)
    } catch {
      // No bundled Vector / unreachable → keep the built-in catalog.
      setSources(SOURCES)
      setSinks(SINKS)
      setLive(false)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load(false)
  }, [load])

  return {
    sources,
    sinks,
    vectorVersion,
    live,
    loading,
    refresh: () => load(true),
  }
}
