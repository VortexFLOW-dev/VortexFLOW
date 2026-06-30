// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

import { useState } from 'react'
import { authApi } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import Modal from '@/components/ui/Modal'
import { btnPrimary, btnSecondary, inputCls } from '@/lib/ui'

const labelCls = 'block text-xs font-medium text-muted-foreground mb-1'

/** Shared current+new+confirm form. Used both as a dismissable modal (self-service)
 *  and as the non-dismissable forced-change screen on login. */
function ChangePasswordForm({
  submitLabel,
  onSuccess,
}: {
  submitLabel: string
  onSuccess: () => void
}) {
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async () => {
    setError(null)
    if (next.length < 8) { setError('New password must be at least 8 characters'); return }
    if (next !== confirm) { setError('New passwords do not match'); return }
    if (next === current) { setError('New password must differ from the current one'); return }
    setBusy(true)
    try {
      await authApi.changePassword(current, next)
      onSuccess()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail ?? 'Change failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-3">
      <div>
        <label className={labelCls}>Current password</label>
        <input type="password" className={`${inputCls} font-mono`} value={current}
          onChange={(e) => setCurrent(e.target.value)} autoComplete="current-password" />
      </div>
      <div>
        <label className={labelCls}>New password</label>
        <input type="password" className={`${inputCls} font-mono`} value={next}
          onChange={(e) => setNext(e.target.value)} autoComplete="new-password" placeholder="min 8 characters" />
      </div>
      <div>
        <label className={labelCls}>Confirm new password</label>
        <input type="password" className={`${inputCls} font-mono`} value={confirm}
          onChange={(e) => setConfirm(e.target.value)} autoComplete="new-password" />
      </div>
      {error && <p className="text-xs text-destructive">{error}</p>}
      <button
        onClick={() => { void submit() }}
        disabled={busy || !current || !next || !confirm}
        className={btnPrimary + ' w-full'}
      >
        {busy ? 'Saving…' : submitLabel}
      </button>
    </div>
  )
}

/** Self-service change-password modal (dismissable). */
export function ChangePasswordModal({ onClose }: { onClose: () => void }) {
  const [done, setDone] = useState(false)
  return (
    <Modal title="Change password" onClose={onClose} maxWidth="max-w-md">
      <div className="p-5">
        {done ? (
          <div className="space-y-4">
            <p className="text-sm text-emerald-400">✓ Password changed.</p>
            <div className="flex justify-end">
              <button onClick={onClose} className={btnSecondary}>Done</button>
            </div>
          </div>
        ) : (
          <ChangePasswordForm submitLabel="Change password" onSuccess={() => setDone(true)} />
        )}
      </div>
    </Modal>
  )
}

/** Full-screen, non-dismissable forced change on first login / after admin reset. */
export function ForcedPasswordChange() {
  const { user } = useAuth()
  return (
    <div className="min-h-screen bg-background flex items-center justify-center p-4">
      <div className="w-full max-w-md bg-card border border-border rounded-xl p-6 space-y-4">
        <div>
          <h1 className="text-base font-semibold text-foreground">Set a new password</h1>
          <p className="text-xs text-muted-foreground mt-1">
            {user?.email && <span className="font-medium text-foreground">{user.email}</span>}
            {user?.email ? ' must ' : 'You must '}set a new password before continuing.
          </p>
        </div>
        {/* Reload once cleared: /auth/me then reports must_change_password=false and
            the app unlocks. */}
        <ChangePasswordForm submitLabel="Set password & continue" onSuccess={() => window.location.reload()} />
      </div>
    </div>
  )
}
