// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

import { useEffect, useState } from 'react'
import { recoveryApi } from '@/lib/api'

const inputCls =
  'w-full bg-background border border-border rounded-lg px-3 py-2 text-sm text-foreground placeholder-muted-foreground focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary transition-colors'

export default function Recovery() {
  const [available, setAvailable] = useState<boolean | null>(null)
  const [token, setToken] = useState('')
  const [pw, setPw] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [done, setDone] = useState(false)

  useEffect(() => {
    recoveryApi
      .status()
      .then(({ data }) => setAvailable(data.available))
      .catch(() => setAvailable(null))
  }, [])

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    // Validate client-side first: the server consumes the one-time token before
    // checking the password, so a length error would otherwise burn the token.
    if (pw.length < 12) {
      setError('New password must be at least 12 characters')
      return
    }
    if (pw !== confirm) {
      setError('Passwords do not match')
      return
    }
    setLoading(true)
    try {
      await recoveryApi.use(token.trim(), pw)
      setDone(true)
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        'Recovery failed'
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-background flex items-center justify-center p-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <div className="inline-flex items-center gap-3 mb-2">
            <img src="/logo.png" alt="VortexFlow" className="h-10 w-10 object-contain" />
            <span className="text-xl font-semibold text-foreground tracking-tight">VortexFlow</span>
          </div>
          <p className="text-sm text-muted-foreground">Account recovery</p>
        </div>

        <div className="bg-card border border-border rounded-xl p-6 shadow-xl">
          {done ? (
            <div className="space-y-4">
              <h1 className="text-sm font-medium text-foreground">Admin account ready</h1>
              <p className="text-xs text-muted-foreground">
                Your admin account is set. You can now sign in with the new password.
              </p>
              <a
                href="/login"
                className="block text-center w-full bg-primary hover:bg-primary/90 text-primary-foreground text-sm font-medium py-2 rounded-lg transition-colors"
              >
                Go to sign in
              </a>
            </div>
          ) : (
            <>
              <h1 className="text-sm font-medium text-foreground mb-2">Set up / recover admin</h1>
              <p className="text-xs text-muted-foreground mb-5">
                The single-use token is printed to the server logs on startup
                (<code className="font-mono">SETUP / RECOVERY TOKEN</code>). On a fresh install it
                creates the first admin; afterward it resets the admin password.
              </p>

              {available === false && (
                <div className="mb-4 bg-amber-400/10 border border-amber-400/30 rounded-lg px-3 py-2 text-xs text-amber-400">
                  No recovery token is currently active. Restart the service to generate a
                  fresh one, then check the server logs.
                </div>
              )}

              <form onSubmit={handleSubmit} className="space-y-4">
                <div>
                  <label className="block text-xs font-medium text-muted-foreground mb-1.5">Recovery token</label>
                  <input
                    type="text"
                    value={token}
                    onChange={(e) => setToken(e.target.value)}
                    required
                    autoFocus
                    className={`${inputCls} font-mono`}
                    placeholder="paste from server logs"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-muted-foreground mb-1.5">New admin password</label>
                  <input
                    type="password"
                    value={pw}
                    onChange={(e) => setPw(e.target.value)}
                    required
                    autoComplete="new-password"
                    className={`${inputCls} font-mono`}
                    placeholder="min 12 characters"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-muted-foreground mb-1.5">Confirm new password</label>
                  <input
                    type="password"
                    value={confirm}
                    onChange={(e) => setConfirm(e.target.value)}
                    required
                    autoComplete="new-password"
                    className={`${inputCls} font-mono`}
                  />
                </div>

                {error && (
                  <div className="bg-destructive/10 border border-destructive/30 rounded-lg px-3 py-2 text-xs text-destructive">
                    {error}
                  </div>
                )}

                <button
                  type="submit"
                  disabled={loading || !token || !pw || !confirm}
                  className="w-full bg-primary hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed text-primary-foreground text-sm font-medium py-2 rounded-lg transition-colors"
                >
                  {loading ? 'Saving…' : 'Set password'}
                </button>
              </form>
            </>
          )}
        </div>

        <p className="mt-6 text-center text-xs text-muted-foreground">
          <a href="/login" className="text-muted-foreground/80 hover:text-foreground transition-colors">
            Back to sign in
          </a>
        </p>
      </div>
    </div>
  )
}
