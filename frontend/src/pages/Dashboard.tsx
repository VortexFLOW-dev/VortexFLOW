// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Maximize2, Minimize2, RefreshCw, Workflow, X } from 'lucide-react'
import FleetTopologyCanvas from '@/components/topology/FleetTopologyCanvas'
import { certsApi, dashboardApi, instancesApi } from '@/lib/api'
import type { DashboardInstance, DashboardFleet, DashboardSummary, NodeHealth } from '@/lib/types'

// ─── Color palette ───────────────────────────────────────────────────────────
const C = {
  healthy:  '#2dd4bf',   // teal-400
  degraded: '#f59e0b',   // amber-400
  offline:  '#f87171',   // red-400
  unknown:  '#52525b',   // zinc-600
}

// ─── Types ────────────────────────────────────────────────────────────────────
interface InstanceWithHealth extends DashboardInstance {
  health: NodeHealth
}

function fmtRate(n: number): string {
  if (n === 0) return '—'
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k/s`
  if (n >= 1) return `${n.toFixed(1)}/s`
  return `${(n * 1000).toFixed(0)}m/s`
}

type Metric = 'events' | 'bytes'

function fmtBytes(n: number): string {
  if (n === 0) return '—'
  const u = ['B', 'KB', 'MB', 'GB', 'TB']
  let i = 0
  while (n >= 1024 && i < u.length - 1) {
    n /= 1024
    i++
  }
  return `${n.toFixed(i === 0 ? 0 : 1)} ${u[i]}/s`
}

interface FleetWithHealth extends DashboardFleet {
  instances: InstanceWithHealth[]
}

// ─── Throughput-by-fleet (stacked hero) ─────────────────────────────────────────
// Top-N fleets by throughput get a distinct colour; the rest fold into one gray
// "Others" band so the stacked total stays honest. The same colour map keys the
// fleet rows, so a band's colour == its row's identity.
const FLEET_PALETTE = ['#2dd4bf', '#7f77dd', '#e0823a', '#378add', '#d4537e']
const OTHERS_COLOR = '#888780'
const TOP_FLEETS = 5

interface Band {
  id: string
  name: string
  color: string
  series: number[]
  evps: number
  isOthers?: boolean
  count?: number
}

// Rank fleets by current throughput, build the top-N + Others bands (with aligned,
// zero-padded series for stacking), and a fleet→colour map shared with the rows.
function fleetBands(fleets: FleetWithHealth[]): {
  bands: Band[]
  ranked: FleetWithHealth[]
  tail: FleetWithHealth[]
  colorMap: Map<string, string>
} {
  const ranked = [...fleets].sort((a, b) => {
    const d = fleetRates(b).evps - fleetRates(a).evps
    return d !== 0 ? d : a.name.localeCompare(b.name)
  })
  const top = ranked.slice(0, TOP_FLEETS)
  const tail = ranked.slice(TOP_FLEETS)
  const colorMap = new Map<string, string>()
  ranked.forEach((f, i) => colorMap.set(f.id, i < TOP_FLEETS ? FLEET_PALETTE[i] : OTHERS_COLOR))

  const len = Math.max(0, ...fleets.map((f) => f.throughput_series?.length ?? 0))
  const pad = (s: number[]) => {
    const a = s ?? []
    return a.length >= len ? a.slice(a.length - len) : [...Array(len - a.length).fill(0), ...a]
  }

  const bands: Band[] = top.map((f) => ({
    id: f.id,
    name: f.name,
    color: colorMap.get(f.id)!,
    series: pad(f.throughput_series),
    evps: fleetRates(f).evps,
  }))
  if (tail.length) {
    const series = Array(len).fill(0)
    tail.forEach((f) => pad(f.throughput_series).forEach((v, i) => (series[i] += v)))
    bands.push({
      id: '__others__',
      name: 'Others',
      color: OTHERS_COLOR,
      series,
      evps: tail.reduce((a, f) => a + fleetRates(f).evps, 0),
      isOthers: true,
      count: tail.length,
    })
  }
  return { bands, ranked, tail, colorMap }
}

// ─── Helpers ─────────────────────────────────────────────────────────────────
function healthColor(h: NodeHealth) {
  return h === 'healthy' ? C.healthy : h === 'degraded' ? C.degraded : h === 'offline' ? C.offline : C.unknown
}

function systemHealthLabel(ok: boolean) {
  return ok ? C.healthy : C.offline
}

// ─── Small bits ────────────────────────────────────────────────────────────────
function Kpi({ label, value, accent }: { label: string; value: string | number; accent?: string }) {
  return (
    <span className="flex items-baseline gap-1">
      <span className="text-sm font-semibold tabular-nums" style={accent ? { color: accent } : undefined}>
        {value}
      </span>
      <span className="text-[10px] text-muted-foreground/50 uppercase tracking-wide">{label}</span>
    </span>
  )
}


export interface FleetKpis {
  fleets: number
  instances: number
  evps: number
  errps: number
}

// ─── Fleet bar (global home header) ─────────────────────────────────────────────
function FleetBar({
  summary,
  kpis,
  loading,
  onRefresh,
  refreshInterval,
  onChangeInterval,
  windowMinutes,
  onChangeWindow,
  metric,
  onChangeMetric,
  fullscreen,
  onToggleFullscreen,
  onShowTopology,
  topologyDisabled,
}: {
  summary: DashboardSummary | null
  kpis: FleetKpis
  loading: boolean
  onRefresh: () => void
  refreshInterval: number
  onChangeInterval: (ms: number) => void
  windowMinutes: number
  onChangeWindow: (m: number) => void
  metric: Metric
  onChangeMetric: (m: Metric) => void
  fullscreen: boolean
  onToggleFullscreen: () => void
  onShowTopology: () => void
  topologyDisabled: boolean
}) {
  const services = summary
    ? [
        { label: 'API', ok: summary.system.api },
        { label: 'DB', ok: summary.system.db },
        { label: 'Redis', ok: summary.system.redis },
        { label: 'VM', ok: summary.system.vm },
      ]
    : []

  return (
    <div className="flex items-center justify-between px-5 h-14 border-b border-border bg-card flex-shrink-0 gap-4">
      <div className="flex items-center gap-3 min-w-0">
        <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider mr-1">Overview</span>
        {loading && <div className="h-3 w-3 border border-border border-t-primary rounded-full animate-spin" />}
        {services.map((s) => (
          <span key={s.label} className="flex items-center gap-1.5 text-xs">
            <span
              className="h-1.5 w-1.5 rounded-full"
              style={{
                backgroundColor: systemHealthLabel(s.ok),
                boxShadow: s.ok ? `0 0 4px ${C.healthy}` : undefined,
                animation: !s.ok ? 'vf-status-blink 1.2s ease-in-out infinite' : undefined,
              }}
            />
            <span className="text-muted-foreground">{s.label}</span>
          </span>
        ))}
        {summary?.leader && (summary.leader.load1 != null || summary.leader.mem_pct != null) && (
          <span
            className="hidden md:flex items-center gap-2 text-xs text-muted-foreground/70 border-l border-border pl-3"
            title="VortexFlow leader host"
          >
            <span className="text-muted-foreground/40 uppercase tracking-wider text-[10px]">leader</span>
            {summary.leader.load1 != null && <span>load {summary.leader.load1.toFixed(2)}</span>}
            {summary.leader.mem_pct != null && <span>mem {summary.leader.mem_pct}%</span>}
          </span>
        )}
      </div>

      <div className="flex items-center gap-4 flex-shrink-0">
        <div className="hidden sm:flex items-center gap-4">
          <Kpi label="fleets" value={kpis.fleets} />
          <a href="/instances" title="View all nodes" className="hover:opacity-80 transition-opacity">
            <Kpi label="instances" value={kpis.instances} />
          </a>
          <Kpi label="ev/s" value={fmtRate(kpis.evps)} accent={kpis.evps > 0 ? C.healthy : undefined} />
          <Kpi
            label="err/s"
            value={kpis.errps > 0 ? fmtRate(kpis.errps) : '0'}
            accent={kpis.errps > 0 ? C.offline : undefined}
          />
        </div>
        <div className="h-5 w-px bg-border" />
        <div className="flex items-center gap-1">
          <button
            onClick={onShowTopology}
            disabled={topologyDisabled}
            className="text-muted-foreground hover:text-foreground transition-colors p-1 rounded disabled:opacity-40"
            title="View selected fleet topology"
          >
            <Workflow size={13} />
          </button>
          <button
            onClick={onRefresh}
            className="text-muted-foreground hover:text-foreground transition-colors p-1 rounded"
            title="Refresh now"
          >
            <RefreshCw size={13} />
          </button>
          <select
            value={metric}
            onChange={(e) => onChangeMetric(e.target.value as Metric)}
            title="Throughput unit"
            className="bg-secondary/60 text-muted-foreground text-[11px] rounded px-1.5 py-1 border-none focus:outline-none cursor-pointer hover:text-foreground"
          >
            <option value="events">EPS</option>
            <option value="bytes">Size</option>
          </select>
          <select
            value={windowMinutes}
            onChange={(e) => onChangeWindow(Number(e.target.value))}
            title="Throughput chart window"
            className="bg-secondary/60 text-muted-foreground text-[11px] rounded px-1.5 py-1 border-none focus:outline-none cursor-pointer hover:text-foreground"
          >
            <option value={15}>15m</option>
            <option value={60}>1h</option>
            <option value={360}>6h</option>
            <option value={1440}>24h</option>
          </select>
          <select
            value={refreshInterval}
            onChange={(e) => onChangeInterval(Number(e.target.value))}
            title="Auto-refresh interval"
            className="bg-secondary/60 text-muted-foreground text-[11px] rounded px-1.5 py-1 border-none focus:outline-none cursor-pointer hover:text-foreground"
          >
            <option value={0}>Off</option>
            <option value={10_000}>10s</option>
            <option value={30_000}>30s</option>
            <option value={60_000}>60s</option>
          </select>
          <button
            onClick={onToggleFullscreen}
            className="text-muted-foreground hover:text-foreground transition-colors p-1 rounded"
            title={fullscreen ? 'Exit fullscreen' : 'Fullscreen'}
          >
            {fullscreen ? <Minimize2 size={13} /> : <Maximize2 size={13} />}
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Rollout health ─────────────────────────────────────────────────────────────
export interface Rollout {
  converged: number
  pending: number
  failed: number
}

function RolloutHealth({ rollout }: { rollout: Rollout }) {
  const total = rollout.converged + rollout.pending + rollout.failed
  return (
    <div className="space-y-2">
      <div className="text-[11px] uppercase tracking-wider text-muted-foreground/50">Agent rollout</div>
      {total === 0 ? (
        <div className="text-xs text-muted-foreground/50">No agents yet</div>
      ) : (
        <>
          <div className="flex items-center gap-3 text-sm">
            <span className="text-primary tabular-nums">{rollout.converged} ✓</span>
            {rollout.pending > 0 && <span className="text-amber-500 tabular-nums">{rollout.pending} ⏳</span>}
            {rollout.failed > 0 && <span className="text-destructive tabular-nums">{rollout.failed} ✗</span>}
          </div>
          <div className="flex h-1.5 rounded-full overflow-hidden bg-secondary">
            <div className="bg-primary" style={{ width: `${(rollout.converged / total) * 100}%` }} />
            <div className="bg-amber-500" style={{ width: `${(rollout.pending / total) * 100}%` }} />
            <div className="bg-destructive" style={{ width: `${(rollout.failed / total) * 100}%` }} />
          </div>
        </>
      )}
    </div>
  )
}

// ─── Attention feed ─────────────────────────────────────────────────────────────
export interface AttentionItem {
  kind: 'offline' | 'failed' | 'cert'
  text: string
}

function Attention({ items }: { items: AttentionItem[] }) {
  const dot = (k: AttentionItem['kind']) => (k === 'cert' ? C.degraded : C.offline)
  return (
    <div className="space-y-2">
      <div className="text-[11px] uppercase tracking-wider text-muted-foreground/50">Attention</div>
      {items.length === 0 ? (
        <div className="flex items-center gap-1.5 text-xs text-muted-foreground/50">
          <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: C.healthy }} />
          All clear
        </div>
      ) : (
        <div className="space-y-1.5">
          {items.map((it, i) => (
            <div key={i} className="flex items-start gap-1.5 text-xs">
              <span
                className="h-1.5 w-1.5 rounded-full mt-1 flex-shrink-0"
                style={{ backgroundColor: dot(it.kind) }}
              />
              <span className="text-foreground/80 leading-snug">{it.text}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ─── Side panel (rollout · throughput · attention) ──────────────────────────────

// ─── Main Dashboard ───────────────────────────────────────────────────────────
// ─── Throughput hero ─────────────────────────────────────────────────────────
function ThroughputHero({
  bands,
  ranked,
  tail,
  totalEvps,
  errps,
  rollout,
  scope,
  onScope,
  metric,
}: {
  bands: Band[]
  ranked: FleetWithHealth[]
  tail: FleetWithHealth[]
  totalEvps: number
  errps: number
  rollout: Rollout
  scope: string
  onScope: (s: string) => void
  metric: Metric
}) {
  const w = 1000
  const h = 140
  const len = Math.max(0, ...bands.map((b) => b.series.length))
  const hasData = len > 1 && bands.some((b) => b.series.some((v) => v > 0))

  // Stack the bands bottom-up; each band's top edge is the running cumulative sum.
  const xAt = (i: number) => (i * w) / Math.max(1, len - 1)
  let peak = 1
  for (let i = 0; i < len; i++) peak = Math.max(peak, bands.reduce((a, b) => a + (b.series[i] ?? 0), 0))
  const yAt = (v: number) => h - (v / (peak * 1.08)) * (h - 8) - 4
  const cum = Array(len).fill(0)
  const polys = bands.map((b) => {
    const top: string[] = []
    const bot: string[] = []
    for (let i = 0; i < len; i++) {
      const base = cum[i]
      const t = base + (b.series[i] ?? 0)
      top.push(`${xAt(i).toFixed(1)},${yAt(t).toFixed(1)}`)
      bot.push(`${xAt(i).toFixed(1)},${yAt(base).toFixed(1)}`)
      cum[i] = t
    }
    return { band: b, points: [...top, ...bot.reverse()].join(' ') }
  })

  const scopedFleet = scope !== 'all' && scope !== '__others__' ? ranked.find((f) => f.id === scope) : null
  const scopedBand = scope === '__others__' ? bands.find((b) => b.isOthers) : null
  // A tail fleet has no band of its own — it lives inside the Others band.
  const isTailScope = scopedFleet != null && !bands.some((b) => b.id === scope)
  const scopedEvps = scopedFleet ? fleetRates(scopedFleet).evps : scopedBand ? scopedBand.evps : totalEvps
  // For the bytes view the number comes from the series itself (the latest
  // point), since per-instance EPS metrics have no bytes equivalent.
  const lastIdx = Math.max(0, len - 1)
  const totalLatest = bands.reduce((a, b) => a + (b.series[lastIdx] ?? 0), 0)
  // Ingest→egress bytes for the active scope → volume reduction.
  const bytesAgg = (fleets: FleetWithHealth[]) =>
    fleets.reduce(
      (a, f) => {
        const r = fleetRates(f)
        return { in: a.in + r.bytesIn, out: a.out + r.bytesOut }
      },
      { in: 0, out: 0 },
    )
  const scopedBytes = scopedFleet
    ? bytesAgg([scopedFleet])
    : scope === '__others__'
      ? bytesAgg(tail)
      : bytesAgg(ranked)
  const reduced = reductionPct(scopedBytes.in, scopedBytes.out)
  const scopedHero =
    scope === 'all'
      ? totalLatest
      : scope === '__others__'
        ? (scopedBand?.series[lastIdx] ?? 0)
        : (bands.find((b) => b.id === scope)?.series[lastIdx] ?? 0)
  const scopeName = scopedFleet
    ? isTailScope
      ? `${scopedFleet.name} · in Others`
      : scopedFleet.name
    : scopedBand
      ? `Others (${scopedBand.count})`
      : 'all fleets'
  // Highlight Others when a tail fleet is scoped (its volume is part of that band).
  const litId = isTailScope ? '__others__' : scope

  return (
    <div className="bg-card border border-border rounded-xl p-5">
      <div className="flex items-start justify-between gap-4 mb-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-[11px] uppercase tracking-wider text-muted-foreground/60">Throughput</span>
            <select
              value={scope}
              onChange={(e) => onScope(e.target.value)}
              className="text-[11px] bg-secondary/60 border border-border rounded px-1.5 py-0.5 text-muted-foreground hover:text-foreground focus:outline-none focus:ring-1 focus:ring-primary/40"
              aria-label="Scope throughput view"
            >
              <option value="all">All fleets</option>
              {ranked.slice(0, TOP_FLEETS).map((f) => (
                <option key={f.id} value={f.id}>{f.name}</option>
              ))}
              {tail.length > 0 && <option value="__others__">Others ({tail.length})</option>}
              {tail.map((f) => (
                <option key={f.id} value={f.id}>{' '}· {f.name}</option>
              ))}
            </select>
          </div>
          <div className="flex items-baseline gap-2 mt-1">
            <span className="text-2xl font-semibold tabular-nums" style={{ color: C.healthy }}>{
              metric === 'bytes' ? fmtBytes(scopedHero) : fmtRate(scopedEvps)
            }</span>
            <span className="text-xs text-muted-foreground">{metric === 'bytes' ? 'bytes / s out' : 'events / s out'} · {scopeName}</span>
            {errps > 0 && scope === 'all' && (
              <span className="text-xs ml-3 tabular-nums" style={{ color: C.offline }}>{fmtRate(errps)} err / s</span>
            )}
          </div>
          {scopedBytes.in > 0 && (
            <div className="text-[11px] text-muted-foreground mt-0.5 tabular-nums">
              {fmtBytes(scopedBytes.in)} in → {fmtBytes(scopedBytes.out)} out
              {reduced != null && (
                <span> · <span style={{ color: C.healthy }}>{reduced}% reduced</span></span>
              )}
            </div>
          )}
        </div>
        <RolloutHealth rollout={rollout} />
      </div>
      <div className="h-32 w-full">
        {hasData ? (
          <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" className="w-full h-full">
            {polys.map(({ band, points }) => {
              const lit = scope === 'all' || litId === band.id
              return (
                <polygon
                  key={band.id}
                  points={points}
                  fill={band.color}
                  fillOpacity={lit ? 0.5 : 0.08}
                  stroke={band.color}
                  strokeOpacity={lit ? 0.9 : 0.18}
                  strokeWidth="1"
                  vectorEffect="non-scaling-stroke"
                  style={{ cursor: 'pointer' }}
                  onClick={() => onScope(scope === band.id ? 'all' : band.id)}
                />
              )
            })}
          </svg>
        ) : (
          <div className="h-full flex items-center justify-center text-xs text-muted-foreground/40">
            Waiting for throughput metrics…
          </div>
        )}
      </div>
      {bands.length > 1 && (
        <div className="flex flex-wrap gap-x-4 gap-y-1.5 mt-3">
          {bands.map((b) => {
            const dim = scope !== 'all' && litId !== b.id
            return (
              <button
                key={b.id}
                onClick={() => onScope(scope === b.id ? 'all' : b.id)}
                className={`flex items-center gap-1.5 text-xs transition-opacity ${dim ? 'opacity-30' : ''}`}
              >
                <span className="h-2.5 w-2.5 rounded-sm flex-shrink-0" style={{ backgroundColor: b.color }} />
                <span className="text-foreground/80">{b.name}{b.isOthers ? ` (${b.count})` : ''}</span>
                <span className="text-muted-foreground tabular-nums">{
                  metric === 'bytes'
                    ? (totalLatest > 0 ? `${Math.round(((b.series[lastIdx] ?? 0) / totalLatest) * 100)}%` : '—')
                    : (totalEvps > 0 ? `${Math.round((b.evps / totalEvps) * 100)}%` : '—')
                }</span>
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}

// ─── Fleet health row ────────────────────────────────────────────────────────
function fleetHealth(f: FleetWithHealth): NodeHealth {
  const hs = f.instances.map((i) => i.health)
  if (hs.includes('offline')) return 'offline'
  if (hs.includes('degraded')) return 'degraded'
  if (hs.length === 0 || hs.every((h) => h === 'unknown')) return 'unknown'
  return 'healthy'
}

// Aggregate out-rate / error-rate / ingest+egress bytes across a fleet's instances.
function fleetRates(f: FleetWithHealth): {
  evps: number
  errps: number
  bytesIn: number
  bytesOut: number
} {
  return {
    evps: f.instances.reduce((a, i) => a + (i.metrics?.events_out_per_sec ?? 0), 0),
    errps: f.instances.reduce((a, i) => a + (i.metrics?.errors_per_sec ?? 0), 0),
    bytesIn: f.instances.reduce((a, i) => a + (i.metrics?.bytes_in_per_sec ?? 0), 0),
    bytesOut: f.instances.reduce((a, i) => a + (i.metrics?.bytes_out_per_sec ?? 0), 0),
  }
}

/** Reduction ratio (0–100) from ingest→egress bytes, or null if no ingest. */
function reductionPct(bytesIn: number, bytesOut: number): number | null {
  if (bytesIn <= 0) return null
  return Math.max(0, Math.round(((bytesIn - bytesOut) / bytesIn) * 100))
}

function FleetRow({ fleet, active, color, onOpen }: { fleet: FleetWithHealth; active: boolean; color?: string; onOpen: () => void }) {
  const health = fleetHealth(fleet)
  const agents = fleet.instances.filter((i) => i.role === 'agent').length
  const aggs = fleet.instances.filter((i) => i.role === 'aggregator').length
  const { evps, errps, bytesIn, bytesOut } = fleetRates(fleet)
  const reduced = reductionPct(bytesIn, bytesOut)
  let pending = 0
  let failed = 0
  fleet.instances.forEach((i) => {
    if (i.config_push_mode !== 'agent') return
    if (i.agent_status === 'validate_failed' || i.agent_status === 'reload_failed') failed++
    else if (i.applied_generation !== fleet.generation) pending++
  })
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(e) => { if (e.key === 'Enter') onOpen() }}
      className={`grid grid-cols-[12px_minmax(0,1fr)_auto_auto] items-center gap-3 px-4 py-3 rounded-xl border cursor-pointer transition-colors ${
        active ? 'border-primary/50 bg-primary/5 ring-1 ring-primary/30' : 'border-border bg-card hover:border-border/70'
      }`}
    >
      <span className="h-2.5 w-2.5 rounded-full flex-shrink-0" style={{ backgroundColor: healthColor(health) }} />
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          {color && (
            <span className="h-2.5 w-2.5 rounded-sm flex-shrink-0" style={{ backgroundColor: color }} title="throughput band" />
          )}
          <span className="text-sm font-medium text-foreground truncate">{fleet.name}</span>
          {fleet.is_default && (
            <span className="text-[10px] text-muted-foreground/60 bg-secondary rounded px-1.5 py-0.5 flex-shrink-0">default</span>
          )}
        </div>
        <div className="text-xs text-muted-foreground truncate">
          {fleet.instances.length === 0
            ? 'no instances'
            : `${agents} agent${agents !== 1 ? 's' : ''}${aggs > 0 ? ` · ${aggs} agg` : ''}`}
          {` · gen ${fleet.generation}`}
          {failed > 0 && <span style={{ color: C.offline }}> · {failed} failed</span>}
          {pending > 0 && <span style={{ color: C.degraded }}> · {pending} rolling</span>}
          {reduced != null && <span style={{ color: C.healthy }}> · {reduced}% reduced</span>}
        </div>
      </div>
      <div className="text-right w-16">
        <div className="text-sm font-medium tabular-nums" style={evps > 0 ? { color: C.healthy } : undefined}>{fmtRate(evps)}</div>
        <div className="text-[10px] text-muted-foreground/50">ev / s</div>
      </div>
      <div className="text-right w-12">
        <div className={`text-sm font-medium tabular-nums ${errps > 0 ? '' : 'text-muted-foreground/40'}`} style={errps > 0 ? { color: C.offline } : undefined}>
          {errps > 0 ? fmtRate(errps) : '0'}
        </div>
        <div className="text-[10px] text-muted-foreground/50">err / s</div>
      </div>
    </div>
  )
}

export default function Dashboard() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null)
  const [fleets, setFleets] = useState<FleetWithHealth[]>([])
  const [loading, setLoading] = useState(true)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [fullscreen, setFullscreen] = useState(false)
  const [refreshInterval, setRefreshInterval] = useState(10_000) // ms; 0 = off
  const [windowMinutes, setWindowMinutes] = useState(60) // throughput chart window
  const [metric, setMetric] = useState<Metric>('events') // throughput chart: events vs bytes
  const [showTopology, setShowTopology] = useState(false)
  const [certs, setCerts] = useState<{ label: string; expires_in_days: number | null }[]>([])
  const [scope, setScope] = useState('all') // throughput hero scope: 'all' | fleetId | '__others__'
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const rootRef = useRef<HTMLDivElement>(null)

  const fetchSummary = useCallback(async () => {
    try {
      const { data } = await dashboardApi.summary(windowMinutes, metric)
      setSummary(data)

      // Build fleets with placeholder 'unknown' health
      const enriched: FleetWithHealth[] = data.fleets.map((s) => ({
        ...s,
        instances: s.instances.map((inst) => ({ ...inst, health: 'unknown' as NodeHealth })),
      }))
      setFleets(enriched)

      // Async health checks per instance
      data.fleets.forEach((s) => {
        s.instances.forEach((inst) => {
          instancesApi
            .health(inst.id)
            .then((r) => {
              const h: NodeHealth = r.data.reachable ? 'healthy' : 'offline'
              setFleets((prev) =>
                prev.map((ps) =>
                  ps.id !== s.id
                    ? ps
                    : {
                        ...ps,
                        instances: ps.instances.map((pi) =>
                          pi.id === inst.id ? { ...pi, health: h } : pi
                        ),
                      }
                )
              )
            })
            .catch(() => {
              setFleets((prev) =>
                prev.map((ps) =>
                  ps.id !== s.id
                    ? ps
                    : {
                        ...ps,
                        instances: ps.instances.map((pi) =>
                          pi.id === inst.id ? { ...pi, health: 'offline' } : pi
                        ),
                      }
                )
              )
            })
        })
      })

      // Auto-select default fleet
      setSelectedId((prev) => {
        if (prev) return prev
        const def = data.fleets.find((s) => s.is_default)
        return def?.id ?? data.fleets[0]?.id ?? null
      })
    } catch {
      // API unavailable — leave summary null
    } finally {
      setLoading(false)
    }
  }, [windowMinutes, metric])

  useEffect(() => {
    void fetchSummary()
    certsApi
      .list()
      .then((r) => setCerts(r.data as { label: string; expires_in_days: number | null }[]))
      .catch(() => setCerts([]))
  }, [fetchSummary])

  // Auto-refresh on the selected interval (0 = off).
  useEffect(() => {
    if (pollRef.current) clearInterval(pollRef.current)
    if (refreshInterval > 0) {
      pollRef.current = setInterval(() => void fetchSummary(), refreshInterval)
    }
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [refreshInterval, fetchSummary])

  // True OS fullscreen via the Fullscreen API (not just a CSS overlay, which
  // left the layout cut off on exit). Sync state from the browser's events.
  useEffect(() => {
    const onChange = () => setFullscreen(!!document.fullscreenElement)
    document.addEventListener('fullscreenchange', onChange)
    return () => document.removeEventListener('fullscreenchange', onChange)
  }, [])

  const toggleFullscreen = () => {
    if (document.fullscreenElement) void document.exitFullscreen()
    else void rootRef.current?.requestFullscreen?.()
  }

  const handleRefresh = () => {
    setLoading(true)
    void fetchSummary()
  }

  // ── Fleet-level derived data ──────────────────────────────────────────────
  const kpis: FleetKpis = {
    fleets: fleets.length,
    instances: summary?.total_instances ?? 0,
    evps: fleets.reduce((a, st) => a + fleetRates(st).evps, 0),
    errps: fleets.reduce((a, st) => a + fleetRates(st).errps, 0),
  }

  // Throughput-by-fleet: top-N + Others bands + shared fleet→colour map.
  // Memoized on `fleets` so scope clicks (which only flip local state) don't
  // re-rank, re-aggregate rates, and re-pad series on every render.
  const { bands, ranked, tail, colorMap } = useMemo(() => fleetBands(fleets), [fleets])

  // Reconcile a stale scope: if the scoped fleet was deleted (or '__others__'
  // when there's no tail), fall back to 'all' so the dropdown and chart never
  // land on a value with no matching option/band.
  const scopeValid =
    scope === 'all' ||
    (scope === '__others__' && tail.length > 0) ||
    ranked.some((f) => f.id === scope)
  const effectiveScope = scopeValid ? scope : 'all'

  const desiredVector = summary?.desired_vector_version ?? ''
  const rollout: Rollout = { converged: 0, pending: 0, failed: 0 }
  const attention: AttentionItem[] = []
  fleets.forEach((st) =>
    st.instances.forEach((i) => {
      if (i.config_push_mode === 'agent') {
        if (i.agent_status === 'validate_failed' || i.agent_status === 'reload_failed') rollout.failed++
        else if (i.applied_generation != null && i.applied_generation === st.generation) rollout.converged++
        else rollout.pending++
      }
      if (i.health === 'offline') attention.push({ kind: 'offline', text: `${i.label} offline · ${st.name}` })
      else if (i.agent_status === 'validate_failed')
        attention.push({ kind: 'failed', text: `${i.label} · config validation failed` })
      else if (i.agent_status === 'reload_failed')
        attention.push({ kind: 'failed', text: `${i.label} · Vector reload failed` })
      else if (desiredVector && i.vector_version && i.vector_version !== desiredVector)
        attention.push({
          kind: 'cert',
          text: `${i.label} on Vector ${i.vector_version} · want ${desiredVector}`,
        })
      // Health signals — can co-occur with an otherwise-green status. Data loss
      // (dropping) is critical/red; failing sink deliveries are a warning/amber.
      const m = i.metrics
      if ((m?.discarded_per_sec ?? 0) > 1)
        attention.push({
          kind: 'failed',
          text: `${i.label} dropping ~${Math.round(m.discarded_per_sec ?? 0)} evt/s · ${st.name}`,
        })
      else if ((m?.sink_failed_per_sec ?? 0) > 0.5)
        attention.push({ kind: 'cert', text: `${i.label} · sink deliveries failing · ${st.name}` })
    }),
  )
  certs.forEach((c) => {
    if (c.expires_in_days != null && c.expires_in_days <= 14) {
      attention.push({
        kind: 'cert',
        text: `Cert "${c.label}" expires in ${c.expires_in_days}d`,
      })
    }
  })

  return (
    <div ref={rootRef} className="flex flex-col h-full overflow-hidden bg-background">
      <FleetBar
        summary={summary}
        kpis={kpis}
        loading={loading}
        onRefresh={handleRefresh}
        refreshInterval={refreshInterval}
        onChangeInterval={setRefreshInterval}
        windowMinutes={windowMinutes}
        onChangeWindow={setWindowMinutes}
        metric={metric}
        onChangeMetric={setMetric}
        fullscreen={fullscreen}
        onToggleFullscreen={toggleFullscreen}
        onShowTopology={() => setShowTopology(true)}
        topologyDisabled={!selectedId}
      />

      <div className="flex-1 min-h-0 overflow-y-auto">
        <div className="max-w-[1200px] mx-auto p-6 space-y-6">
          <ThroughputHero
            bands={bands}
            ranked={ranked}
            tail={tail}
            totalEvps={kpis.evps}
            errps={kpis.errps}
            rollout={rollout}
            scope={effectiveScope}
            onScope={setScope}
            metric={metric}
          />

          <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_340px] gap-6">
            <section>
              <div className="flex items-center justify-between mb-3">
                <h2 className="text-sm font-semibold text-foreground">Fleets</h2>
                <a href="/fleets" className="text-xs text-muted-foreground/70 hover:text-foreground transition-colors">Manage →</a>
              </div>
              {loading && fleets.length === 0 ? (
                <div className="space-y-2">
                  {[...Array(3)].map((_, i) => (
                    <div key={i} className="h-16 bg-card border border-border rounded-xl animate-pulse" />
                  ))}
                </div>
              ) : fleets.length === 0 ? (
                <div className="bg-card border border-border rounded-xl p-8 text-center text-sm text-muted-foreground">
                  No fleets yet.
                </div>
              ) : (
                <div className="space-y-2">
                  {fleets.map((f) => (
                    <FleetRow
                      key={f.id}
                      fleet={f}
                      active={selectedId === f.id}
                      color={colorMap.get(f.id)}
                      onOpen={() => { setSelectedId(f.id); setShowTopology(true) }}
                    />
                  ))}
                </div>
              )}
            </section>

            <section>
              <h2 className="text-sm font-semibold text-foreground mb-3">Needs attention</h2>
              {attention.length === 0 ? (
                <div className="bg-card border border-border rounded-xl p-6 text-center text-xs text-muted-foreground/70">
                  All clear — nothing needs attention.
                </div>
              ) : (
                <Attention items={attention} />
              )}
            </section>
          </div>
        </div>
      </div>

      {showTopology && selectedId && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4"
          onClick={() => setShowTopology(false)}
        >
          <div
            className="bg-card border border-border rounded-xl w-full max-w-5xl h-[80vh] flex flex-col overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="px-5 py-3 border-b border-border flex items-center justify-between flex-shrink-0">
              <h3 className="text-sm font-semibold text-foreground">
                Fleet topology — {fleets.find((s) => s.id === selectedId)?.name ?? ''}
              </h3>
              <button
                onClick={() => setShowTopology(false)}
                className="text-muted-foreground hover:text-foreground transition-colors"
              >
                <X size={16} />
              </button>
            </div>
            <FleetTopologyCanvas
              fleetId={selectedId}
              onRouteClick={(id) => {
                window.location.assign(`/transforms?route=${id}`)
              }}
            />
          </div>
        </div>
      )}
    </div>
  )
}
