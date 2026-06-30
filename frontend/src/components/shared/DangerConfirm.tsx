// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

/**
 * DangerConfirm — confirmation modal for destructive actions.
 *
 * Pass a `phrase` (e.g. "DELETE") to require the user to type it before the
 * confirm button enables — used for breaking changes like deleting a fleet
 * (which cascades away its config and detaches its instances). Without a phrase
 * it's a plain confirm. `children` renders the impact/blast-radius body.
 */

import { useState } from 'react'
import type { ReactNode } from 'react'
import Modal from '@/components/ui/Modal'
import { btnSecondary, inputCls } from '@/lib/ui'

interface Props {
  title: string
  phrase?: string
  confirmLabel?: string
  loading?: boolean
  onConfirm: () => void
  onClose: () => void
  children: ReactNode
}

export default function DangerConfirm({
  title,
  phrase,
  confirmLabel = 'Delete',
  loading = false,
  onConfirm,
  onClose,
  children,
}: Props) {
  const [typed, setTyped] = useState('')
  const ok = !phrase || typed === phrase

  return (
    <Modal title={title} onClose={onClose}>
      <div className="space-y-4">
        <div className="text-sm text-muted-foreground">{children}</div>

        {phrase && (
          <div className="space-y-1.5">
            <label className="text-xs text-muted-foreground">
              Type <span className="font-mono text-foreground">{phrase}</span> to confirm
            </label>
            <input
              autoFocus
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && ok && !loading) onConfirm()
              }}
              placeholder={phrase}
              className={`${inputCls} font-mono`}
            />
          </div>
        )}

        <div className="flex justify-end gap-2 pt-1">
          <button onClick={onClose} className={btnSecondary} disabled={loading}>
            Cancel
          </button>
          <button
            onClick={onConfirm}
            disabled={!ok || loading}
            className="px-4 py-2 rounded-lg bg-destructive text-white text-sm font-medium hover:bg-destructive/90 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {loading ? 'Deleting…' : confirmLabel}
          </button>
        </div>
      </div>
    </Modal>
  )
}
