// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

/**
 * LiveTap — stream live output events from any Vector component.
 *
 * Uses fetch + ReadableStream (not EventSource) so the JWT Authorization
 * header is preserved. The backend proxies Vector's graphql-ws subscription
 * and re-emits events as SSE (text/event-stream).
 *
 * Compare mode: when the selected target is a transform, tap its input(s) and
 * its output side-by-side (before → after), so you can see what the remap did
 * to each event — the Vector equivalent of Cribl's capture/diff.
 */

import { useEffect, useRef, useState } from 'react'
import type { Instance } from '@/lib/types'
import { fleetsApi } from '@/lib/api'
import { btnPrimary, btnSecondary, inputCls } from '@/lib/ui'

// ─── Types ────────────────────────────────────────────────────────────────────

export interface TapEvent {
  id: number
  ts: string
  raw: Record<string, unknown>
}

interface TapTarget {
  resource_id: string
  id: string
  label: string
  kind: 'source' | 'transform' | 'route' | 'route_branch'
  input_ids?: string[]
}

let _eventId = 0

// Infer the field schema from a sample of tapped events: the underlying record
// is the JSON-encoded `string` field (Vector's tap) when present, else the event
// itself. Returns each field with the JS types seen and what % of events had it,
// so you can see the shape of the data flowing through a component — and, in
// compare mode, which fields a transform added or dropped.
interface FieldInfo {
  name: string
  types: string[]
  pct: number
}
function inferFields(events: TapEvent[]): FieldInfo[] {
  const seen = new Map<string, { types: Set<string>; count: number }>()
  let n = 0
  for (const e of events) {
    let rec: Record<string, unknown> | null = null
    const s = e.raw.string
    if (typeof s === 'string') {
      try {
        const parsed = JSON.parse(s)
        if (parsed && typeof parsed === 'object') rec = parsed as Record<string, unknown>
      } catch {
        /* not JSON — skip */
      }
    }
    if (!rec) continue
    n++
    for (const [k, v] of Object.entries(rec)) {
      const t = Array.isArray(v) ? 'array' : v === null ? 'null' : typeof v
      const cur = seen.get(k) ?? { types: new Set<string>(), count: 0 }
      cur.types.add(t)
      cur.count++
      seen.set(k, cur)
    }
  }
  return [...seen.entries()]
    .map(([name, { types, count }]) => ({
      name,
      types: [...types],
      pct: n ? Math.round((count / n) * 100) : 0,
    }))
    .sort((a, b) => a.name.localeCompare(b.name))
}

// ─── useTapStream ───────────────────────────────────────────────────────────────
// One live SSE stream (events + lifecycle). Compare mode runs two of these.

export interface TapStream {
  events: TapEvent[]
  running: boolean
  paused: boolean
  error: string | null
  start: (instanceId: string, componentId: string, limit: number) => Promise<void>
  stop: () => void
  setPaused: (p: boolean) => void
  clear: () => void
}

export function useTapStream(): TapStream {
  const [events, setEvents] = useState<TapEvent[]>([])
  const [running, setRunning] = useState(false)
  const [paused, setPaused] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const pausedRef = useRef(false)

  useEffect(() => {
    pausedRef.current = paused
  }, [paused])

  // Abort the stream if the component using the hook unmounts.
  useEffect(() => () => abortRef.current?.abort(), [])

  async function start(instanceId: string, componentId: string, limit: number) {
    const comp = componentId.trim()
    if (!instanceId || !comp) return
    abortRef.current?.abort()
    setEvents([])
    setError(null)
    setRunning(true)
    setPaused(false)
    pausedRef.current = false

    const controller = new AbortController()
    abortRef.current = controller
    const token = localStorage.getItem('access_token') ?? ''
    const url = `/api/v1/instances/${instanceId}/tap?component_id=${encodeURIComponent(comp)}&limit=${limit}`

    try {
      const res = await fetch(url, {
        headers: { Authorization: `Bearer ${token}` },
        signal: controller.signal,
      })
      if (!res.ok) {
        setError(`HTTP ${res.status}: ${await res.text()}`)
        setRunning(false)
        return
      }
      const reader = res.body?.getReader()
      if (!reader) {
        setError('No response body')
        setRunning(false)
        return
      }
      const decoder = new TextDecoder()
      let buf = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        const lines = buf.split('\n')
        buf = lines.pop() ?? ''
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          let parsed: Record<string, unknown>
          try {
            parsed = JSON.parse(line.slice(6)) as Record<string, unknown>
          } catch {
            continue
          }
          if (parsed.done) {
            setRunning(false)
            return
          }
          if (!pausedRef.current) {
            const ev: TapEvent = { id: ++_eventId, ts: new Date().toISOString(), raw: parsed }
            setEvents((prev) => [...prev.slice(-999), ev])
          }
        }
      }
    } catch (err: unknown) {
      if ((err as { name?: string }).name !== 'AbortError') setError(String(err))
    } finally {
      setRunning(false)
    }
  }

  function stop() {
    abortRef.current?.abort()
    setRunning(false)
  }
  function clear() {
    setEvents([])
  }
  return { events, running, paused, error, start, stop, setPaused, clear }
}

// ─── Component ────────────────────────────────────────────────────────────────

interface Props {
  instances: Instance[]
}

export default function LiveTap({ instances }: Props) {
  const [instanceId, setInstanceId] = useState(instances[0]?.id ?? '')
  const [componentId, setComponentId] = useState('')
  const [limit, setLimit] = useState(50)
  const [compare, setCompare] = useState(false)
  const [filter, setFilter] = useState('')
  const [targets, setTargets] = useState<TapTarget[]>([])

  const after = useTapStream()
  const before = useTapStream()

  const autoComponentRef = useRef<string | null>(
    new URLSearchParams(window.location.search).get('component'),
  )
  const autoStartedRef = useRef(false)

  // The selected target (if the typed id matches a known one) decides whether a
  // before/after compare is available — only transforms with rendered inputs.
  const selectedTarget = targets.find((t) => t.id === componentId)
  const beforeIds = selectedTarget?.input_ids ?? []
  const canCompare = selectedTarget?.kind === 'transform' && beforeIds.length > 0
  const comparing = compare && canCompare
  const running = after.running || before.running

  const selectedFleetId = instances.find((i) => i.id === instanceId)?.fleet_id ?? null
  useEffect(() => {
    if (!selectedFleetId) {
      setTargets([])
      return
    }
    fleetsApi
      .tapTargets(selectedFleetId)
      .then((r) => setTargets(r.data.targets))
      .catch(() => setTargets([]))
  }, [selectedFleetId])

  useEffect(() => {
    if (autoComponentRef.current) setComponentId(autoComponentRef.current)
  }, [])

  function startTap(compOverride?: string) {
    const comp = (compOverride ?? componentId).trim()
    if (!instanceId || !comp) return
    if (compOverride) setComponentId(compOverride)
    void after.start(instanceId, comp, limit)
    // Compare only kicks in for a known transform target; an ad-hoc glob taps once.
    const t = targets.find((x) => x.id === comp)
    if (compare && t?.kind === 'transform' && (t.input_ids?.length ?? 0) > 0) {
      void before.start(instanceId, (t.input_ids ?? []).join(','), limit)
    }
  }
  function stopTap() {
    after.stop()
    before.stop()
  }
  function setPausedBoth(p: boolean) {
    after.setPaused(p)
    before.setPaused(p)
  }
  function clearBoth() {
    after.clear()
    before.clear()
  }

  // Auto-start once when arriving via Flow's "tap this node" deep-link.
  useEffect(() => {
    if (autoComponentRef.current && instanceId && !autoStartedRef.current) {
      autoStartedRef.current = true
      startTap(autoComponentRef.current)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [instanceId])

  const activeInstance = instances.find((i) => i.id === instanceId)
  const paused = after.paused
  const error = after.error || before.error

  return (
    <div className="flex flex-col gap-4">
      {/* Controls */}
      <div className="bg-card border border-border rounded-xl p-4 flex flex-wrap gap-3 items-end">
        <div className="flex flex-col gap-1">
          <label className="text-xs text-muted-foreground font-medium">Instance</label>
          <select
            value={instanceId}
            onChange={(e) => setInstanceId(e.target.value)}
            disabled={running}
            className={`${inputCls} min-w-[180px]`}
          >
            {instances.map((inst) => (
              <option key={inst.id} value={inst.id}>
                {inst.label}
              </option>
            ))}
          </select>
        </div>

        <div className="flex flex-col gap-1 flex-1 min-w-[180px]">
          <label className="text-xs text-muted-foreground font-medium">Component ID</label>
          <input
            type="text"
            list="vf-tap-targets"
            className={`${inputCls} w-full`}
            placeholder="Pick a node, or type a glob like nginx_*"
            value={componentId}
            onChange={(e) => setComponentId(e.target.value)}
            disabled={running}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !running) startTap()
            }}
          />
          <datalist id="vf-tap-targets">
            {targets.map((t) => (
              <option key={t.id} value={t.id}>
                {t.label} · {t.kind.replace('_', ' ')}
              </option>
            ))}
          </datalist>
        </div>

        <div className="flex flex-col gap-1">
          <label className="text-xs text-muted-foreground font-medium">Max events</label>
          <input
            type="number"
            className={`${inputCls} w-24`}
            min={1}
            max={500}
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value))}
            disabled={running}
          />
        </div>

        {/* Filter applies to the displayed events (both panes), live — does not
            stop or restart the stream. */}
        <div className="flex flex-col gap-1">
          <label className="text-xs text-muted-foreground font-medium">Filter</label>
          <input
            type="text"
            className={`${inputCls} w-40`}
            placeholder="substring match…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
        </div>

        <div className="flex gap-2 items-end">
          {running ? (
            <>
              <button className={btnSecondary} onClick={() => setPausedBoth(!paused)}>
                {paused ? 'Resume' : 'Pause'}
              </button>
              <button className={btnSecondary} onClick={stopTap}>
                Stop
              </button>
            </>
          ) : (
            <button
              className={btnPrimary}
              disabled={!instanceId || !componentId.trim()}
              onClick={() => startTap()}
            >
              ▶ Start Tap
            </button>
          )}
        </div>
      </div>

      {/* Before/after toggle — only meaningful for a transform with inputs. */}
      {canCompare && (
        <label className="flex items-center gap-2 px-1 text-sm text-foreground cursor-pointer select-none">
          <input
            type="checkbox"
            checked={compare}
            onChange={(e) => setCompare(e.target.checked)}
            disabled={running}
            className="accent-primary"
          />
          Compare before / after — tap this transform’s input and output side by side
        </label>
      )}

      {activeInstance && (
        <p className="text-xs text-muted-foreground px-1">
          Vector API: <span className="font-mono">{activeInstance.api_url}</span>
          {' · '}
          Pick a component from the list, or type a glob pattern (e.g.{' '}
          <span className="font-mono">nginx_*</span>). Tip: on Flow, click a node to tap it.
        </p>
      )}

      {error && (
        <div className="bg-destructive/10 border border-destructive/30 text-destructive rounded-lg px-4 py-3 text-sm">
          {error}
        </div>
      )}

      {/* Event log(s) */}
      {comparing ? (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <TapLog
            title={`Before · ${beforeIds.join(', ')}`}
            subtitle="input to the transform"
            stream={before}
            running={running}
            onClear={clearBoth}
            filter={filter}
          />
          <TapLog
            title={`After · ${componentId}`}
            subtitle="transform output"
            stream={after}
            running={running}
            onClear={clearBoth}
            filter={filter}
          />
        </div>
      ) : (
        <TapLog
          title="Events"
          waitingFor={componentId}
          stream={after}
          running={running}
          onClear={clearBoth}
          filter={filter}
          copyable
        />
      )}
    </div>
  )
}

// ─── TapLog ─────────────────────────────────────────────────────────────────────
// One scrollable event pane (header + list). Reused by both compare panes.

interface TapLogProps {
  title: string
  subtitle?: string
  waitingFor?: string
  stream: TapStream
  running: boolean
  onClear: () => void
  filter?: string
  copyable?: boolean
  // Height of the scrollable log area — defaults to the full-page size; the
  // embedded drawer tap passes a smaller one.
  heightClass?: string
}

export function TapLog({ title, subtitle, waitingFor, stream, running, onClear, filter, copyable, heightClass = 'h-[480px]' }: TapLogProps) {
  const { events, paused } = stream
  const logRef = useRef<HTMLDivElement>(null)
  const autoScrollRef = useRef(true)
  const [copied, setCopied] = useState(false)
  const [showFields, setShowFields] = useState(false)

  const q = (filter ?? '').trim().toLowerCase()
  const shown = q
    ? events.filter((e) => JSON.stringify(e.raw).toLowerCase().includes(q))
    : events
  const fields = inferFields(shown)

  useEffect(() => {
    if (autoScrollRef.current && logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight
    }
  }, [shown])

  function handleScroll() {
    const el = logRef.current
    if (!el) return
    autoScrollRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40
  }
  function copyAll() {
    const text = shown.map((e) => JSON.stringify(e.raw, null, 2)).join('\n\n---\n\n')
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    })
  }

  return (
    <div className="bg-card border border-border rounded-xl overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2 border-b border-border">
        <span className="text-sm font-medium text-foreground truncate">
          <span className="font-mono">{title}</span>
          {subtitle && <span className="ml-2 text-xs text-muted-foreground">{subtitle}</span>}
          {events.length > 0 && (
            <span className="ml-2 text-xs text-muted-foreground">
              {q ? `${shown.length}/${events.length}` : events.length}
              {running && !paused && (
                <span className="ml-2 inline-block w-2 h-2 rounded-full bg-primary animate-pulse" />
              )}
              {paused && <span className="ml-2 text-amber-500 text-xs">paused</span>}
            </span>
          )}
        </span>
        {events.length > 0 && (
          <div className="flex gap-2 shrink-0">
            <button
              className={`text-xs transition-colors ${showFields ? 'text-foreground' : 'text-muted-foreground hover:text-foreground'}`}
              onClick={() => setShowFields((s) => !s)}
              title="Inferred fields in the sample"
            >
              Fields {fields.length > 0 ? `(${fields.length})` : ''}
            </button>
            <button
              className="text-xs text-muted-foreground hover:text-foreground transition-colors"
              onClick={onClear}
            >
              Clear
            </button>
            {copyable && (
              <button
                className="text-xs text-muted-foreground hover:text-foreground transition-colors"
                onClick={copyAll}
              >
                {copied ? '✓ Copied' : 'Copy all'}
              </button>
            )}
          </div>
        )}
      </div>
      {showFields && (
        <div className="flex flex-wrap gap-1.5 px-3 py-2 border-b border-border bg-secondary/20">
          {fields.length === 0 ? (
            <span className="text-xs text-muted-foreground">No structured fields detected yet.</span>
          ) : (
            fields.map((f) => (
              <span
                key={f.name}
                className="text-[11px] font-mono bg-secondary rounded px-1.5 py-0.5 text-foreground/80"
                title={`${f.types.join(' | ')} · present in ${f.pct}% of events`}
              >
                {f.name}
                <span className="text-muted-foreground/60"> {f.types.join('|')}</span>
                {f.pct < 100 && <span className="text-amber-500/80"> {f.pct}%</span>}
              </span>
            ))
          )}
        </div>
      )}
      <div
        ref={logRef}
        onScroll={handleScroll}
        className={`${heightClass} overflow-y-auto font-mono text-xs`}
      >
        {events.length === 0 && !running && (
          <div className="flex items-center justify-center h-full text-muted-foreground text-sm">
            No events yet — start a tap to see live data.
          </div>
        )}
        {events.length === 0 && running && (
          <div className="flex items-center justify-center h-full text-muted-foreground text-sm gap-2">
            <span className="inline-block w-3 h-3 rounded-full border-2 border-primary border-t-transparent animate-spin" />
            Waiting for events{waitingFor ? ' from ' : '…'}
            {waitingFor && <span className="font-mono text-foreground">{waitingFor}</span>}
          </div>
        )}
        {events.length > 0 && shown.length === 0 && (
          <div className="flex items-center justify-center h-full text-muted-foreground text-sm">
            No events match “{q}”.
          </div>
        )}
        {shown.map((ev, idx) => (
          <EventRow key={ev.id} event={ev} alt={idx % 2 === 1} />
        ))}
      </div>
    </div>
  )
}

// ─── EventRow ─────────────────────────────────────────────────────────────────

interface EventRowProps {
  event: TapEvent
  alt: boolean
}

function EventRow({ event, alt }: EventRowProps) {
  const [expanded, setExpanded] = useState(false)

  const isNotif = event.raw.__typename === 'EventNotification'
  const isMetric = !isNotif && 'name' in event.raw && 'kind' in event.raw
  const isLog = !isNotif && !isMetric && ('message' in event.raw || 'string' in event.raw)
  const badge = isNotif ? 'INFO' : isLog ? 'LOG' : isMetric ? 'METRIC' : 'TRACE'
  const badgeCls = isNotif
    ? 'bg-muted text-muted-foreground'
    : isLog
      ? 'bg-sky-500/15 text-sky-500'
      : isMetric
        ? 'bg-violet-500/15 text-violet-500'
        : 'bg-orange-500/15 text-orange-500'

  const summary = isNotif
    ? String((event.raw as { message?: unknown }).message ?? '')
    : isLog
      ? String(
          (event.raw as { message?: unknown }).message ?? JSON.stringify(event.raw).slice(0, 120),
        )
      : isMetric
        ? `${String(event.raw.name)} [${String(event.raw.kind)}]`
        : JSON.stringify(event.raw).slice(0, 120)

  return (
    <div
      className={`border-b border-border/50 px-3 py-1.5 cursor-pointer hover:bg-secondary/50 transition-colors ${alt ? 'bg-secondary/30' : ''}`}
      onClick={() => setExpanded((x) => !x)}
    >
      <div className="flex items-start gap-2">
        <span className="text-muted-foreground shrink-0 mt-0.5" style={{ fontSize: 10 }}>
          {event.ts.slice(11, 23)}
        </span>
        <span className={`shrink-0 rounded px-1 py-0.5 text-[10px] font-semibold ${badgeCls}`}>
          {badge}
        </span>
        <span className="text-foreground truncate">{summary}</span>
        <span className="shrink-0 text-muted-foreground ml-auto">{expanded ? '▲' : '▼'}</span>
      </div>
      {expanded && (
        <pre className="mt-2 text-[11px] text-foreground bg-secondary/40 rounded p-2 overflow-x-auto whitespace-pre-wrap break-all">
          {JSON.stringify(event.raw, null, 2)}
        </pre>
      )}
    </div>
  )
}
