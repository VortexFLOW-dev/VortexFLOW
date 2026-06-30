// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

import { useEffect, useRef, useState } from 'react'
import { useAuth } from '@/lib/auth'
import { useTheme } from '@/lib/theme'
import { useFleet } from '@/lib/fleet'
import { useBrand } from '@/lib/brand'
import { fleetsApi } from '@/lib/api'
import type { Fleet } from '@/lib/types'
import NotificationCenter from './NotificationCenter'
import { ChangePasswordModal } from '@/components/ChangePassword'

// ─── Icons ────────────────────────────────────────────────────────────────────

function ChevronDownIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="h-3 w-3 flex-shrink-0">
      <path d="M6 9l6 6 6-6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function CheckIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="h-3.5 w-3.5 flex-shrink-0">
      <path d="M20 6L9 17l-5-5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function PlusIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="h-3.5 w-3.5">
      <path d="M12 5v14M5 12h14" strokeLinecap="round" />
    </svg>
  )
}

function SunIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75} className="h-4 w-4">
      <circle cx="12" cy="12" r="5" strokeLinecap="round" strokeLinejoin="round" />
      <line x1="12" y1="1" x2="12" y2="3" strokeLinecap="round" />
      <line x1="12" y1="21" x2="12" y2="23" strokeLinecap="round" />
      <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" strokeLinecap="round" />
      <line x1="18.36" y1="18.36" x2="19.78" y2="19.78" strokeLinecap="round" />
      <line x1="1" y1="12" x2="3" y2="12" strokeLinecap="round" />
      <line x1="21" y1="12" x2="23" y2="12" strokeLinecap="round" />
      <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" strokeLinecap="round" />
      <line x1="18.36" y1="5.64" x2="19.78" y2="4.22" strokeLinecap="round" />
    </svg>
  )
}

function MoonIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75} className="h-4 w-4">
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

// ─── Nav item definitions ─────────────────────────────────────────────────────

interface NavItem {
  label: string
  href: string
  icon: React.ReactNode
  adminOnly?: boolean
}

const fleetNav: NavItem[] = [
  {
    label: 'Health',
    href: '/',
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75} className="h-4 w-4">
        <path d="M22 12h-4l-3 9L9 3l-3 9H2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
  },
  {
    label: 'Catalog',
    href: '/catalog',
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75} className="h-4 w-4">
        <rect x="3" y="3" width="7" height="7" rx="1" strokeLinecap="round" strokeLinejoin="round" />
        <rect x="14" y="3" width="7" height="7" rx="1" strokeLinecap="round" strokeLinejoin="round" />
        <rect x="3" y="14" width="7" height="7" rx="1" strokeLinecap="round" strokeLinejoin="round" />
        <rect x="14" y="14" width="7" height="7" rx="1" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
  },
  {
    label: 'Transforms',
    href: '/transforms',
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75} className="h-4 w-4">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" strokeLinecap="round" strokeLinejoin="round" />
        <polyline points="14 2 14 8 20 8" strokeLinecap="round" strokeLinejoin="round" />
        <line x1="16" y1="13" x2="8" y2="13" strokeLinecap="round" />
        <line x1="16" y1="17" x2="8" y2="17" strokeLinecap="round" />
        <polyline points="10 9 9 9 8 9" strokeLinecap="round" />
      </svg>
    ),
  },
  {
    label: 'Flow',
    href: '/flow',
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75} className="h-4 w-4">
        <circle cx="5" cy="6" r="2" strokeLinecap="round" strokeLinejoin="round" />
        <circle cx="5" cy="18" r="2" strokeLinecap="round" strokeLinejoin="round" />
        <circle cx="19" cy="12" r="2" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M7 6h5a3 3 0 0 1 3 3v1M7 18h5a3 3 0 0 0 3-3v-1" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
  },
  {
    label: 'Live Tap',
    href: '/tap',
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75} className="h-4 w-4">
        <circle cx="12" cy="12" r="3" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M12 1v4M12 19v4M4.22 4.22l2.83 2.83M16.95 16.95l2.83 2.83M1 12h4M19 12h4M4.22 19.78l2.83-2.83M16.95 7.05l2.83-2.83" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
  },
]

const globalNav: NavItem[] = [
  {
    label: 'Fleets',
    href: '/fleets',
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75} className="h-4 w-4">
        <path d="M12 2L2 7l10 5 10-5-10-5z" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M2 17l10 5 10-5M2 12l10 5 10-5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
  },
  {
    label: 'Instances',
    href: '/instances',
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75} className="h-4 w-4">
        <rect x="2" y="3" width="20" height="14" rx="2" strokeLinecap="round" strokeLinejoin="round" />
        <line x1="8" y1="21" x2="16" y2="21" strokeLinecap="round" />
        <line x1="12" y1="17" x2="12" y2="21" strokeLinecap="round" />
      </svg>
    ),
  },
]

const settingsNavItem: NavItem = {
  label: 'Settings',
  href: '/settings',
  adminOnly: true,
  icon: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75} className="h-4 w-4">
      <circle cx="12" cy="12" r="3" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  ),
}

// ─── New fleet modal ─────────────────────────────────────────────────────────

function NewFleetModal({ onCreated, onClose }: { onCreated: (s: Fleet) => void; onClose: () => void }) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim()) { setError('Name is required'); return }
    setSaving(true)
    try {
      const { data } = await fleetsApi.create({ name: name.trim(), description: description.trim() || undefined })
      onCreated(data)
    } catch {
      setError('Failed to create fleet')
    } finally {
      setSaving(false)
    }
  }

  const inputCls = 'w-full bg-background border border-border rounded-lg px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary focus:border-primary'

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div className="bg-card border border-border rounded-xl w-full max-w-md shadow-xl">
        <div className="flex items-center justify-between px-6 py-4 border-b border-border">
          <h2 className="text-sm font-semibold text-foreground">New Fleet</h2>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground transition-colors">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="h-4 w-4">
              <path d="M18 6L6 18M6 6l12 12" strokeLinecap="round" />
            </svg>
          </button>
        </div>
        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-muted-foreground">Name <span className="text-destructive">*</span></label>
            <input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} placeholder="production" autoFocus />
          </div>
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-muted-foreground">Description</label>
            <input className={inputCls} value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Production Vector fleet" />
          </div>
          {error && <p className="text-xs text-destructive">{error}</p>}
          <div className="flex justify-end gap-3 pt-1">
            <button type="button" onClick={onClose} className="text-muted-foreground hover:text-foreground text-sm px-4 py-2 rounded-lg hover:bg-secondary transition-colors">Cancel</button>
            <button type="submit" disabled={saving} className="bg-primary hover:bg-primary/90 text-primary-foreground font-medium text-sm px-4 py-2 rounded-lg transition-colors disabled:opacity-50">
              {saving ? 'Creating…' : 'Create fleet'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ─── Fleet selector ──────────────────────────────────────────────────────────

function FleetSelector() {
  const { fleets, activeFleet, setActiveFleet } = useFleet()
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const [showNewModal, setShowNewModal] = useState(false)
  const btnRef = useRef<HTMLButtonElement>(null)
  const popoverRef = useRef<HTMLDivElement>(null)
  const searchRef = useRef<HTMLInputElement>(null)

  // Popover position — fixed to the right edge of the sidebar
  const [popoverTop, setPopoverTop] = useState(0)

  const openPopover = () => {
    if (open) { setOpen(false); return }
    if (btnRef.current) {
      const rect = btnRef.current.getBoundingClientRect()
      setPopoverTop(rect.top)
    }
    setSearch('')
    setOpen(true)
  }

  // Close on outside click
  useEffect(() => {
    if (!open) return
    // Focus search on open
    requestAnimationFrame(() => searchRef.current?.focus())
    const handler = (e: MouseEvent) => {
      const target = e.target as Node
      if (
        popoverRef.current && !popoverRef.current.contains(target) &&
        btnRef.current && !btnRef.current.contains(target)
      ) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  // Close on Escape
  useEffect(() => {
    if (!open) return
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [open])

  const filtered = fleets.filter((s) =>
    s.name.toLowerCase().includes(search.toLowerCase())
  )

  const handleSelect = (s: Fleet) => { setActiveFleet(s); setOpen(false) }
  const handleCreated = (s: Fleet) => { setActiveFleet(s); setShowNewModal(false) }

  return (
    <>
      <div className="px-2 pb-1">
        <button
          ref={btnRef}
          onClick={openPopover}
          className="w-full flex items-center gap-2 px-3 py-2 rounded-lg bg-secondary/60 hover:bg-secondary border border-border/50 transition-colors text-sm text-foreground"
        >
          <span className="flex-1 text-left font-medium truncate">
            {activeFleet?.name ?? 'No fleet'}
          </span>
          {activeFleet?.is_default && (
            <span className="text-[10px] text-muted-foreground/60 bg-background rounded px-1.5 py-0.5 flex-shrink-0">
              default
            </span>
          )}
          <ChevronDownIcon />
        </button>
      </div>

      {/* Floating popover — fixed position, right of sidebar (w-56 = 224px) */}
      {open && (
        <div
          ref={popoverRef}
          style={{ position: 'fixed', left: 224, top: popoverTop, zIndex: 50 }}
          className="w-64 bg-card border border-border rounded-lg shadow-xl overflow-hidden"
        >
          {/* Search */}
          <div className="p-2 border-b border-border">
            <div className="flex items-center gap-2 bg-background border border-border rounded-md px-2.5 py-1.5">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="h-3.5 w-3.5 text-muted-foreground flex-shrink-0">
                <circle cx="11" cy="11" r="8" /><path d="M21 21l-4.35-4.35" strokeLinecap="round" />
              </svg>
              <input
                ref={searchRef}
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search fleets…"
                className="flex-1 bg-transparent text-xs text-foreground placeholder:text-muted-foreground outline-none"
              />
              {search && (
                <button onClick={() => setSearch('')} className="text-muted-foreground hover:text-foreground">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="h-3 w-3">
                    <path d="M18 6L6 18M6 6l12 12" strokeLinecap="round" />
                  </svg>
                </button>
              )}
            </div>
          </div>

          {/* Fleet list */}
          <div className="max-h-64 overflow-y-auto py-1">
            {filtered.length === 0 ? (
              <div className="px-3 py-4 text-xs text-muted-foreground text-center">
                {search ? `No fleets matching "${search}"` : 'No fleets available'}
              </div>
            ) : (
              filtered.map((s) => (
                <button
                  key={s.id}
                  onClick={() => handleSelect(s)}
                  className="w-full text-left px-3 py-2 text-sm text-foreground hover:bg-secondary transition-colors flex items-center gap-2"
                >
                  <span className="w-4 flex-shrink-0 text-primary">
                    {activeFleet?.id === s.id && <CheckIcon />}
                  </span>
                  <span className="flex-1 truncate">{s.name}</span>
                  {s.is_default && (
                    <span className="text-xs text-muted-foreground bg-secondary rounded px-1.5 py-0.5 flex-shrink-0">
                      default
                    </span>
                  )}
                </button>
              ))
            )}
          </div>

          {/* Footer: new fleet */}
          <div className="border-t border-border py-1">
            <button
              onClick={() => { setOpen(false); if (isAdmin) setShowNewModal(true) }}
              disabled={!isAdmin}
              className="w-full text-left px-3 py-2 text-sm flex items-center gap-2 transition-colors disabled:opacity-40 disabled:cursor-not-allowed text-muted-foreground hover:text-foreground hover:bg-secondary"
              title={isAdmin ? undefined : 'Admin access required'}
            >
              <span className="w-4 flex-shrink-0"><PlusIcon /></span>
              New fleet
            </button>
          </div>
        </div>
      )}

      {showNewModal && <NewFleetModal onCreated={handleCreated} onClose={() => setShowNewModal(false)} />}
    </>
  )
}

// ─── Nav link ─────────────────────────────────────────────────────────────────

function NavLink({ item, current }: { item: NavItem; current: string }) {
  const active = current === item.href || (item.href !== '/' && current.startsWith(item.href))
  return (
    <a
      href={item.href}
      className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors ${
        active ? 'bg-primary/10 text-primary' : 'text-muted-foreground hover:text-foreground hover:bg-secondary'
      }`}
    >
      <span className={active ? 'text-primary' : 'text-muted-foreground'}>{item.icon}</span>
      {item.label}
    </a>
  )
}

// ─── Section label ────────────────────────────────────────────────────────────

function SectionLabel({ label }: { label: string }) {
  return (
    <div className="px-3 pt-4 pb-1">
      <span className="text-[10px] font-semibold text-muted-foreground/50 uppercase tracking-widest">
        {label}
      </span>
    </div>
  )
}

// ─── Sidebar ──────────────────────────────────────────────────────────────────

function KeyIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75} className="h-4 w-4">
      <circle cx="7.5" cy="15.5" r="4.5" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M10.7 12.3 21 2m-4 4 2.5 2.5M14 9l2.5 2.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

export default function Sidebar() {
  const { user, logout } = useAuth()
  const { theme, toggleTheme } = useTheme()
  const current = window.location.pathname
  const [showChangePw, setShowChangePw] = useState(false)
  const brand = useBrand()

  const showSettings = user?.role === 'admin'

  return (
    <aside className="w-56 flex-shrink-0 bg-card border-r border-border flex flex-col h-screen sticky top-0">

      {/* Logo — h-14 matches the fleet context strip in TopBar */}
      <div className="h-14 flex items-center px-4 border-b border-border flex-shrink-0">
        <a href="/" className="flex items-center gap-2.5 min-w-0 hover:opacity-80 transition-opacity" title={brand}>
          <img src="/logo.png" alt={brand} className="h-7 w-7 object-contain flex-shrink-0" />
          <span className="text-sm font-semibold text-foreground tracking-tight truncate">{brand}</span>
        </a>
      </div>

      {/* Scrollable nav area */}
      <div className="flex-1 overflow-y-auto">

        {/* Fleet selector */}
        <div className="pt-3">
          <SectionLabel label="Fleet" />
          <FleetSelector />
        </div>

        {/* Fleet-scoped nav */}
        <nav className="px-2 pb-2 space-y-0.5">
          {fleetNav.map((item) => <NavLink key={item.href} item={item} current={current} />)}
        </nav>

        {/* Global nav */}
        <div className="border-t border-border/60">
          <SectionLabel label="Global" />
          <nav className="px-2 pb-2 space-y-0.5">
            {globalNav.map((item) => <NavLink key={item.href} item={item} current={current} />)}
          </nav>
        </div>

      </div>

      {/* Docs + Settings + user footer — pinned to bottom */}
      <div className="flex-shrink-0 border-t border-border">
        <div className="px-2 pt-2 space-y-0.5">
          {/* Docs live in the repo today; this points at the docs site, which
              resolves once it's published. Opens in a new tab. */}
          <a
            href="https://docs.vortexflow.dev"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-3 px-3 py-2 rounded-lg text-sm text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors"
          >
            <span className="text-muted-foreground">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75} className="h-4 w-4">
                <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" strokeLinecap="round" strokeLinejoin="round" />
                <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </span>
            Docs
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75} className="h-3.5 w-3.5 ml-auto text-muted-foreground/60">
              <path d="M7 17L17 7M17 7H8M17 7v9" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </a>
          {showSettings && <NavLink item={settingsNavItem} current={current} />}
        </div>
        <div className="px-3 py-3">
          <div className="flex items-center gap-2 px-2 py-1.5 rounded-lg">
            <div className="h-6 w-6 rounded-full bg-secondary flex items-center justify-center text-xs text-foreground font-medium flex-shrink-0">
              {user?.name?.[0]?.toUpperCase() ?? '?'}
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-xs font-medium text-foreground truncate">{user?.name}</div>
              <div className="text-xs text-muted-foreground truncate capitalize">{user?.role}</div>
            </div>
            <div className="flex items-center gap-1 flex-shrink-0">
              <NotificationCenter />
              {user?.auth_method === 'local' && (
                <button
                  onClick={() => setShowChangePw(true)}
                  className="text-muted-foreground hover:text-foreground transition-colors p-1 rounded"
                  title="Change password"
                >
                  <KeyIcon />
                </button>
              )}
              <button
                onClick={toggleTheme}
                className="text-muted-foreground hover:text-foreground transition-colors p-1 rounded"
                title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
              >
                {theme === 'dark' ? <SunIcon /> : <MoonIcon />}
              </button>
              <button
                onClick={() => logout().then(() => (window.location.href = '/login'))}
                className="text-muted-foreground hover:text-foreground transition-colors p-1 rounded"
                title="Sign out"
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75} className="h-4 w-4">
                  <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" strokeLinecap="round" strokeLinejoin="round" />
                  <polyline points="16 17 21 12 16 7" strokeLinecap="round" strokeLinejoin="round" />
                  <line x1="21" y1="12" x2="9" y2="12" strokeLinecap="round" />
                </svg>
              </button>
            </div>
          </div>
        </div>
      </div>

      {showChangePw && <ChangePasswordModal onClose={() => setShowChangePw(false)} />}

    </aside>
  )
}
