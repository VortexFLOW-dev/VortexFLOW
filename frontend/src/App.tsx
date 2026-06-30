// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

import { AuthProvider } from '@/lib/auth'
import { ThemeProvider } from '@/lib/theme'
import { FleetProvider } from '@/lib/fleet'
import Login from '@/pages/Login'
import Recovery from '@/pages/Recovery'
import SsoCallback from '@/pages/SsoCallback'
import Dashboard from '@/pages/Dashboard'
import Flow from '@/pages/Flow'
import Instances from '@/pages/Instances'
import Transforms from '@/pages/Transforms'
import Fleets from '@/pages/Fleets'
import Catalog from '@/pages/Catalog'
import Tap from '@/pages/Tap'
import Settings from '@/pages/Settings'
import Layout from '@/components/layout/Layout'

function Router() {
  const path = window.location.pathname

  if (path === '/login') return <Login />
  // SSO redirect landing — stores tokens from the URL fragment, outside Layout.
  if (path === '/auth/callback') return <SsoCallback />
  // Unauthenticated break-glass — must render outside the auth-gated Layout.
  if (path === '/recovery') return <Recovery />

  return (
    <FleetProvider>
      <Layout>
        {path === '/' && <Dashboard />}
        {path.startsWith('/flow') && <Flow />}
        {path.startsWith('/transforms') && <Transforms />}
        {path.startsWith('/instances') && <Instances />}
        {path.startsWith('/fleets') && <Fleets />}
        {path.startsWith('/catalog') && <Catalog />}
        {path.startsWith('/tap') && <Tap />}
        {path.startsWith('/settings') && <Settings />}
      </Layout>
    </FleetProvider>
  )
}

export default function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <Router />
      </AuthProvider>
    </ThemeProvider>
  )
}
