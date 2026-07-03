// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

import { useEffect, useState } from 'react'

/**
 * Lands the OIDC/SSO redirect. The backend callback issues VortexFlow tokens and
 * 302s here with them in the URL *fragment* (#access_token=…&refresh_token=…),
 * which is never sent to a server. We pull them out, store them, scrub the URL,
 * and enter the app.
 */
export default function SsoCallback() {
  const [error, setError] = useState(false)

  useEffect(() => {
    const frag = window.location.hash.startsWith('#')
      ? window.location.hash.slice(1)
      : ''
    const params = new URLSearchParams(frag)
    const access = params.get('access_token')
    // The refresh token is delivered as an httpOnly cookie by the callback — only
    // the short-lived access token comes back in the fragment.
    if (access) {
      localStorage.setItem('access_token', access)
      // replace() so the token-bearing URL never enters history.
      window.location.replace('/')
    } else {
      setError(true)
      setTimeout(
        () => window.location.replace('/login?sso_error=callback_no_tokens'),
        1500,
      )
    }
  }, [])

  return (
    <div className="min-h-screen bg-background flex items-center justify-center p-4">
      <div className="text-center text-sm text-muted-foreground">
        {error ? 'Sign-in failed — returning to login…' : 'Completing sign-in…'}
      </div>
    </div>
  )
}
