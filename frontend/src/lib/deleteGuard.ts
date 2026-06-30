// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

import type { AxiosError } from 'axios'

/**
 * Run a delete that may be refused with 409 when the resource is still wired to
 * others. On 409, surface the backend's "in use by …" message and offer a
 * force-delete; on confirm, retry with force=true.
 *
 * `fn` takes the force flag so the same call can be retried. Returns true if the
 * resource was deleted (with or without force), false if the user cancelled.
 * Re-throws any non-409 error for the caller to handle.
 */
export async function deleteGuarded(fn: (force: boolean) => Promise<unknown>): Promise<boolean> {
  try {
    await fn(false)
    return true
  } catch (e) {
    const err = e as AxiosError<{ detail?: { message?: string } | string }>
    if (err.response?.status === 409) {
      const d = err.response.data?.detail
      const msg = typeof d === 'string' ? d : (d?.message ?? 'This item is in use.')
      if (window.confirm(`${msg}\n\nForce delete anyway?`)) {
        await fn(true)
        return true
      }
      return false
    }
    throw e
  }
}
