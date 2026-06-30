// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

import { useEffect, useState } from 'react'
import { useAuth } from '@/lib/auth'
import { authApi } from '@/lib/api'
import type { AuthMethods } from '@/lib/types'

// SSO error codes are `{provider}_{reason}` (e.g. oidc_state_expired,
// azure_verify_failed). Messages are keyed by the provider-agnostic reason.
const SSO_ERROR_REASONS: Record<string, string> = {
  disabled: 'Single sign-on is not enabled for this provider.',
  misconfigured: 'Single sign-on is misconfigured. Contact your administrator.',
  idp_error: 'Your identity provider reported an error.',
  bad_request: 'The sign-in response was incomplete. Please try again.',
  state_expired: 'Your sign-in attempt expired. Please try again.',
  state_invalid: 'The sign-in response could not be validated.',
  verify_failed: 'Could not verify your identity with the provider.',
  no_email: 'Your account has no email address to sign in with.',
  email_unverified: 'Your email address is not verified with your identity provider.',
  account_conflict:
    'An account with your email already exists with a different sign-in method.',
  account_disabled: 'Your account is disabled. Contact your administrator.',
}

function ssoErrorMessage(code: string): string {
  if (code === 'callback_no_tokens') return 'Sign-in did not complete. Please try again.'
  const reason = code.replace(/^[a-z]+_/, '')
  return SSO_ERROR_REASONS[reason] ?? 'Single sign-on failed. Please try again.'
}

export default function Login() {
  const { login, user } = useAuth()
  const [methods, setMethods] = useState<AuthMethods | null>(null)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (user) window.location.href = '/'
    authApi.methods().then(({ data }) => {
      setMethods(data)
      if (data?.app_name) document.title = data.app_name
    })
  }, [user])

  useEffect(() => {
    const code = new URLSearchParams(window.location.search).get('sso_error')
    if (code) setError(ssoErrorMessage(code))
  }, [])

  const brand = methods?.app_name ?? 'VortexFlow'

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await login(email, password)
      window.location.href = '/'
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        'Login failed'
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-background flex items-center justify-center p-4">
      <div className="w-full max-w-sm">
        {/* Logo / wordmark */}
        <div className="mb-8 text-center">
          <div className="inline-flex items-center gap-3 mb-2">
            <img src="/logo.png" alt={brand} className="h-10 w-10 object-contain" />
            <span className="text-xl font-semibold text-foreground tracking-tight">{brand}</span>
          </div>
          <p className="text-sm text-muted-foreground">Vector pipeline control plane</p>
        </div>

        <div className="bg-card border border-border rounded-xl p-6 shadow-xl">
          <h1 className="text-sm font-medium text-foreground mb-5">Sign in to your account</h1>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-xs font-medium text-muted-foreground mb-1.5">Email</label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                autoFocus
                className="w-full bg-background border border-border rounded-lg px-3 py-2 text-sm text-foreground placeholder-muted-foreground focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary transition-colors"
                placeholder="you@company.com"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-muted-foreground mb-1.5">Password</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                className="w-full bg-background border border-border rounded-lg px-3 py-2 text-sm text-foreground placeholder-muted-foreground focus:outline-none focus:border-primary focus:ring-1 focus:ring-primary transition-colors"
                placeholder="••••••••"
              />
            </div>

            {error && (
              <div className="bg-destructive/10 border border-destructive/30 rounded-lg px-3 py-2 text-xs text-destructive">
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={loading}
              className="w-full bg-primary hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed text-primary-foreground text-sm font-medium py-2 rounded-lg transition-colors"
            >
              {loading ? 'Signing in…' : 'Sign in'}
            </button>
          </form>

          {/* SSO buttons */}
          {/* LDAP is transparent on the local form (no button), so it must not
              gate this "or continue with" block — only the redirect providers do. */}
          {methods && (methods.azure || methods.oidc || methods.saml) && (
            <div className="mt-5">
              <div className="relative flex items-center gap-3 text-xs text-muted-foreground mb-4">
                <div className="flex-1 border-t border-border" />
                <span>or continue with</span>
                <div className="flex-1 border-t border-border" />
              </div>
              <div className="space-y-2">
                {methods.azure && (
                  <a
                    href="/api/v1/auth/azure/login"
                    className="flex items-center justify-center w-full bg-secondary hover:bg-secondary/80 border border-border rounded-lg px-3 py-2 text-sm text-foreground transition-colors"
                  >
                    Microsoft / Azure AD
                  </a>
                )}
                {methods.oidc && (
                  <a
                    href="/api/v1/auth/oidc/login"
                    className="flex items-center justify-center w-full bg-secondary hover:bg-secondary/80 border border-border rounded-lg px-3 py-2 text-sm text-foreground transition-colors"
                  >
                    {methods.oidc_display_name}
                  </a>
                )}
                {methods.saml && (
                  <a
                    href="/api/v1/auth/saml/login"
                    className="flex items-center justify-center w-full bg-secondary hover:bg-secondary/80 border border-border rounded-lg px-3 py-2 text-sm text-foreground transition-colors"
                  >
                    {methods.saml_display_name}
                  </a>
                )}
              </div>
            </div>
          )}
        </div>

        <p className="mt-6 text-center text-xs text-muted-foreground">
          Locked out?{' '}
          <a href="/recovery" className="text-muted-foreground/80 hover:text-foreground transition-colors">
            Use recovery token
          </a>
        </p>
      </div>
    </div>
  )
}
