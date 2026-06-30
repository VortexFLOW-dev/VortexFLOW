// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

import type { ReactNode } from 'react'
import Sidebar from './Sidebar'
import TopBar from './TopBar'
import { useAuth } from '@/lib/auth'
import { ForcedPasswordChange } from '@/components/ChangePassword'

interface LayoutProps {
  children: ReactNode
}

export default function Layout({ children }: LayoutProps) {
  const { loading, user } = useAuth()

  if (loading) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <div className="h-5 w-5 border-2 border-border border-t-primary rounded-full animate-spin" />
      </div>
    )
  }

  if (!user) {
    window.location.href = '/login'
    return null
  }

  // Forced password change gates the entire app (mirrors the server-side
  // require_role guard) until the user rotates a bootstrap/temp password.
  if (user.must_change_password) {
    return <ForcedPasswordChange />
  }

  // The TopBar shows active-fleet context, which only makes sense on the
  // fleet-scoped editor pages. It's hidden on / (the fleet dashboard has its own
  // FleetBar) and on global pages (Fleets/Instances/Settings), where a single
  // active fleet is irrelevant and showing it would misrepresent the model.
  const path = window.location.pathname
  const fleetScoped = ['/catalog', '/flow', '/transforms', '/tap'].some((p) =>
    path.startsWith(p),
  )

  return (
    <div className="flex h-screen bg-background text-foreground">
      <Sidebar />
      <div className="flex flex-col flex-1 min-w-0">
        {fleetScoped && <TopBar />}
        <main className="flex-1 overflow-auto">
          {children}
        </main>
      </div>
    </div>
  )
}
