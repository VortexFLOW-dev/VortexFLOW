// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

import { useEffect, useState } from 'react'
import { authApi } from '@/lib/api'

// Configurable brand name (Settings → General → Application name), served
// publicly via /auth/methods. Module-cached so repeated mounts don't refetch;
// also keeps the document title in sync.
let _cached: string | null = null

export function useBrand(): string {
  const [name, setName] = useState(_cached ?? 'VortexFlow')
  useEffect(() => {
    if (_cached) {
      document.title = _cached
      return
    }
    authApi
      .methods()
      .then(({ data }) => {
        const n = (data?.app_name as string) || 'VortexFlow'
        _cached = n
        setName(n)
        document.title = n
      })
      .catch(() => {})
  }, [])
  return name
}
