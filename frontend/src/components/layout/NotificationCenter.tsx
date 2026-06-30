// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

import { useEffect, useRef, useState } from 'react'
import { eventsApi } from '@/lib/api'
import type { FleetEvent } from '@/lib/types'

function BellIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75} className="h-4 w-4">
      <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M13.73 21a2 2 0 0 1-3.46 0" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

const SEV_DOT: Record<FleetEvent['severity'], string> = {
  critical: 'bg-destructive',
  warning: 'bg-amber-500',
  info: 'bg-primary',
}

function timeAgo(iso: string): string {
  const then = new Date(iso).getTime()
  const secs = Math.max(0, Math.floor((Date.now() - then) / 1000))
  if (secs < 60) return `${secs}s ago`
  const mins = Math.floor(secs / 60)
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return `${Math.floor(hrs / 24)}d ago`
}

export default function NotificationCenter() {
  const [events, setEvents] = useState<FleetEvent[]>([])
  const [unack, setUnack] = useState(0)
  const [open, setOpen] = useState(false)
  // Distance from the viewport bottom to the button's top — the panel opens
  // upward from the footer bell so it isn't clipped off the bottom edge.
  const [bottom, setBottom] = useState(0)
  const btnRef = useRef<HTMLButtonElement>(null)
  const popRef = useRef<HTMLDivElement>(null)

  const load = async () => {
    try {
      const { data } = await eventsApi.list()
      setEvents(data.events)
      setUnack(data.unacknowledged)
    } catch {
      /* transient — keep last known state */
    }
  }

  // Poll every 30s; refresh immediately when the panel opens.
  useEffect(() => {
    load()
    const t = window.setInterval(load, 30000)
    return () => window.clearInterval(t)
  }, [])

  useEffect(() => {
    if (!open) return
    load()
    const onClick = (e: MouseEvent) => {
      const t = e.target as Node
      if (
        popRef.current && !popRef.current.contains(t) &&
        btnRef.current && !btnRef.current.contains(t)
      ) {
        setOpen(false)
      }
    }
    const onEsc = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', onClick)
    document.addEventListener('keydown', onEsc)
    return () => {
      document.removeEventListener('mousedown', onClick)
      document.removeEventListener('keydown', onEsc)
    }
  }, [open])

  const toggle = () => {
    if (!open && btnRef.current) {
      const rect = btnRef.current.getBoundingClientRect()
      setBottom(window.innerHeight - rect.top + 8)
    }
    setOpen((o) => !o)
  }

  const ack = async (id: string) => {
    setEvents((es) => es.map((e) => (e.id === id ? { ...e, acknowledged_at: new Date().toISOString() } : e)))
    setUnack((n) => Math.max(0, n - 1))
    try {
      await eventsApi.ack(id)
    } finally {
      load()
    }
  }

  const ackAll = async () => {
    setUnack(0)
    try {
      await eventsApi.ackAll()
    } finally {
      load()
    }
  }

  return (
    <>
      <button
        ref={btnRef}
        onClick={toggle}
        className="relative text-muted-foreground hover:text-foreground transition-colors p-1 rounded"
        title="Notifications"
      >
        <BellIcon />
        {unack > 0 && (
          <span className="absolute -top-0.5 -right-0.5 min-w-[14px] h-[14px] px-1 rounded-full bg-destructive text-[9px] font-semibold text-white flex items-center justify-center leading-none">
            {unack > 9 ? '9+' : unack}
          </span>
        )}
      </button>

      {open && (
        <div
          ref={popRef}
          style={{ position: 'fixed', left: 224, bottom, zIndex: 50 }}
          className="w-80 bg-card border border-border rounded-lg shadow-xl overflow-hidden"
        >
          <div className="flex items-center justify-between px-3 py-2 border-b border-border">
            <span className="text-xs font-semibold text-foreground">Notifications</span>
            {unack > 0 && (
              <button onClick={ackAll} className="text-[11px] text-primary hover:underline">
                Mark all read
              </button>
            )}
          </div>
          <div className="max-h-96 overflow-y-auto">
            {events.length === 0 ? (
              <div className="px-3 py-8 text-xs text-muted-foreground text-center">
                Nothing needs attention.
              </div>
            ) : (
              events.map((e) => {
                const isUnack = e.acknowledged_at === null
                return (
                  <button
                    key={e.id}
                    onClick={() => isUnack && ack(e.id)}
                    disabled={!isUnack}
                    className={`w-full text-left px-3 py-2.5 border-b border-border/50 flex gap-2.5 transition-colors ${
                      isUnack ? 'hover:bg-secondary cursor-pointer' : 'opacity-50 cursor-default'
                    }`}
                  >
                    <span className={`mt-1 h-1.5 w-1.5 rounded-full flex-shrink-0 ${SEV_DOT[e.severity]}`} />
                    <span className="flex-1 min-w-0">
                      <span className="block text-xs font-medium text-foreground">{e.title}</span>
                      {e.body && <span className="block text-[11px] text-muted-foreground mt-0.5">{e.body}</span>}
                      <span className="block text-[10px] text-muted-foreground/70 mt-0.5">{timeAgo(e.created_at)}</span>
                    </span>
                  </button>
                )
              })
            )}
          </div>
        </div>
      )}
    </>
  )
}
