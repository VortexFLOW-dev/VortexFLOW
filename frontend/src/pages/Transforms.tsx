// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

import { useEffect, useState, useCallback, useRef } from 'react'
import { transformsApi } from '@/lib/api'
import type { VrlTransform } from '@/lib/types'
import { useAuth } from '@/lib/auth'
import VrlEditor from '@/components/vrl/VrlEditor'
import AiGenerateModal from '@/components/vrl/AiGenerateModal'
import FleetTransforms from '@/components/transforms/FleetTransforms'
import { btnPrimary, btnSecondary, btnGhost, inputCls } from '@/lib/ui'

const DEFAULT_VRL = `.message = upcase(string!(.message))
.processed_at = now()
del(.unnecessary_field)
`

const DEFAULT_EVENT = `{
  "message": "hello from vector",
  "host": "web-01",
  "unnecessary_field": "remove me",
  "level": "info"
}`


type TestState =
  | { status: 'idle' }
  | { status: 'running' }
  | { status: 'success'; output: object; via?: string }
  | { status: 'error'; message: string; via?: string }

export default function Transforms() {
  const { user } = useAuth()
  const isEditor = user?.role === 'admin' || user?.role === 'editor'

  const [pageMode, setPageMode] = useState<'transforms' | 'library'>('transforms')
  const [transforms, setTransforms] = useState<VrlTransform[]>([])
  const [loadingLib, setLoadingLib] = useState(true)
  const [selected, setSelected] = useState<VrlTransform | null>(null)
  const [showSaveModal, setShowSaveModal] = useState(false)

  const [vrl, setVrl] = useState(DEFAULT_VRL)
  const [eventJson, setEventJson] = useState(DEFAULT_EVENT)
  const [testState, setTestState] = useState<TestState>({ status: 'idle' })
  const [dirty, setDirty] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [aiEnabled, setAiEnabled] = useState(false)
  const [showAi, setShowAi] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  const loadLibrary = useCallback(() => {
    setLoadingLib(true)
    transformsApi
      .list()
      .then((r) => setTransforms(r.data.transforms ?? []))
      .finally(() => setLoadingLib(false))
  }, [])

  useEffect(() => { loadLibrary() }, [loadLibrary])

  // Editor-readable gate for the "New with AI" entry point.
  useEffect(() => {
    if (!isEditor) return
    transformsApi.aiStatus().then((r) => setAiEnabled(!!r.data.enabled)).catch(() => {})
  }, [isEditor])

  const selectTransform = (t: VrlTransform) => {
    setSelected(t)
    setVrl(t.source_vrl)
    setDirty(false)
    setTestState({ status: 'idle' })
  }

  const newTransform = () => {
    setSelected(null)
    setVrl(DEFAULT_VRL)
    setDirty(false)
    setTestState({ status: 'idle' })
  }

  const handleVrlChange = (v: string) => {
    setVrl(v)
    setDirty(true)
  }

  const parseEvent = (): object | null => {
    try {
      return JSON.parse(eventJson)
    } catch {
      setTestState({ status: 'error', message: 'Event JSON is invalid — fix it before testing.' })
      return null
    }
  }

  // Run against a live Vector instance (full execution path, via GraphQL testRemap).
  const runTest = async () => {
    const parsed = parseEvent()
    if (!parsed) return
    setTestState({ status: 'running' })
    try {
      const r = await transformsApi.test({ vrl, event: parsed })
      const { success, output, error, instance_id } = r.data
      const via = instance_id ? `instance ${instance_id}` : undefined
      if (success) {
        setTestState({ status: 'success', output: output ?? {}, via })
      } else {
        setTestState({ status: 'error', message: error ?? 'Unknown error', via })
      }
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setTestState({ status: 'error', message: msg ?? 'Request failed' })
    }
  }

  // Validate/run with the bundled Vector binary — instant, needs no instance.
  const runValidate = async () => {
    const parsed = parseEvent()
    if (!parsed) return
    setTestState({ status: 'running' })
    try {
      const r = await transformsApi.validate({ vrl, event: parsed })
      const { ok, output, error, source } = r.data
      const via = source === 'vector-cli' ? 'bundled Vector' : undefined
      if (ok) {
        setTestState({ status: 'success', output: output ?? {}, via })
      } else {
        setTestState({ status: 'error', message: error ?? 'Validation failed', via })
      }
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setTestState({ status: 'error', message: msg ?? 'Request failed' })
    }
  }

  // ── Import / export (P1) ──────────────────────────────────────────────────
  const slug = (s: string) =>
    s.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'transform'

  const download = (filename: string, content: string, type: string) => {
    const url = URL.createObjectURL(new Blob([content], { type }))
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.click()
    URL.revokeObjectURL(url)
  }

  const exportCurrent = () =>
    download(`${slug(selected?.name ?? 'transform')}.vrl`, vrl, 'text/plain;charset=utf-8')

  const exportAll = () => {
    const bundle = {
      vortexflow_pack: 'vrl-transforms',
      version: 1,
      transforms: transforms.map((t) => ({
        name: t.name,
        description: t.description,
        source_vrl: t.source_vrl,
      })),
    }
    download('vrl-library.json', JSON.stringify(bundle, null, 2), 'application/json')
  }

  const importFile = async (file: File) => {
    setError(null)
    const text = await file.text()
    type ImportItem = { name?: string; description?: string | null; source_vrl?: unknown }
    let items: ImportItem[]
    if (file.name.toLowerCase().endsWith('.json')) {
      let data: unknown
      try {
        data = JSON.parse(text)
      } catch {
        setError('Invalid JSON file.')
        return
      }
      const d = data as { transforms?: ImportItem[]; source_vrl?: unknown }
      if (Array.isArray(d?.transforms)) items = d.transforms
      else if (typeof d?.source_vrl === 'string') items = [d as ImportItem]
      else {
        setError('Unrecognized file — expected a transform or a vrl-transforms pack.')
        return
      }
    } else {
      // .vrl / .txt → one transform, name from the filename
      items = [{ name: file.name.replace(/\.(vrl|txt)$/i, ''), source_vrl: text }]
    }

    let created = 0
    for (const it of items) {
      if (typeof it.source_vrl !== 'string' || !it.source_vrl.trim()) continue
      try {
        await transformsApi.create({
          name: String(it.name ?? 'imported').slice(0, 255) || 'imported',
          description: it.description ?? null,
          source_vrl: it.source_vrl,
        })
        created++
      } catch {
        /* skip a row that fails (e.g. duplicate name) and keep going */
      }
    }
    if (created === 0) setError('Nothing imported — check the file contents (names may already exist).')
    else loadLibrary()
  }

  const onFilePicked = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.currentTarget.files?.[0]
    e.currentTarget.value = '' // allow re-importing the same file
    if (f) void importFile(f)
  }

  const handleSave = async (name: string, description: string) => {
    if (selected) {
      await transformsApi.update(selected.id, { name, description, source_vrl: vrl })
    } else {
      await transformsApi.create({ name, description, source_vrl: vrl })
    }
    setDirty(false)
    setShowSaveModal(false)
    loadLibrary()
  }

  const handleDelete = async (t: VrlTransform) => {
    try {
      await transformsApi.delete(t.id)
      if (selected?.id === t.id) newTransform()
      loadLibrary()
    } catch {
      setError('Failed to delete transform. You may not have permission.')
    }
  }

  return (
    <div className="flex flex-col h-screen overflow-hidden">
      {/* Mode toggle: the active fleet's transforms vs the global reusable library */}
      <div className="flex-shrink-0 border-b border-border bg-card px-4 py-2 flex items-center gap-2">
        <div className="flex rounded-lg border border-border overflow-hidden">
          {(['transforms', 'library'] as const).map((m) => (
            <button
              key={m}
              onClick={() => setPageMode(m)}
              className={`px-3 py-1.5 text-xs font-medium transition-colors ${
                pageMode === m ? 'bg-primary/15 text-primary' : 'text-muted-foreground hover:text-foreground bg-background'
              } ${m === 'library' ? 'border-l border-border' : ''}`}
            >
              {m === 'transforms' ? 'Transforms' : 'Library'}
            </button>
          ))}
        </div>
        <p className="text-xs text-muted-foreground/60">
          {pageMode === 'transforms'
            ? "The active fleet's transforms — remap & route. Click one to edit it on Flow."
            : 'Library · reusable VRL templates, shared across fleets.'}
        </p>
      </div>

      {pageMode === 'transforms' ? (
        <FleetTransforms />
      ) : (
    <div className="flex flex-1 min-h-0 overflow-hidden">
      {/* ── Left panel: library ── */}
      <aside className="w-56 flex-shrink-0 bg-card border-r border-border flex flex-col">
        <div className="px-4 py-4 border-b border-border">
          <div className="flex items-center justify-between">
            <span className="text-[11px] uppercase tracking-wider text-muted-foreground/50">Library</span>
            {isEditor && (
              <button onClick={newTransform} className="text-primary hover:text-primary/80 transition-colors" title="New transform">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="h-4 w-4">
                  <path d="M12 5v14M5 12h14" strokeLinecap="round" />
                </svg>
              </button>
            )}
          </div>
          <p className="text-[11px] text-muted-foreground/50 mt-1">Shared across all fleets</p>
          <div className="flex items-center gap-1.5 mt-2">
            {isEditor && (
              <button
                onClick={() => fileRef.current?.click()}
                className={`${btnGhost} flex-1`}
                title="Import a .vrl file or a vrl-transforms .json pack"
              >
                ⤒ Import
              </button>
            )}
            <button
              onClick={exportAll}
              disabled={transforms.length === 0}
              className={`${btnGhost} flex-1 disabled:opacity-40`}
              title="Export the whole library as a .json pack"
            >
              ⤓ Export all
            </button>
            <input
              ref={fileRef}
              type="file"
              accept=".vrl,.json,.txt"
              onChange={onFilePicked}
              className="hidden"
            />
          </div>
          {isEditor && aiEnabled && (
            <button
              onClick={() => setShowAi(true)}
              className={`${btnGhost} w-full mt-1.5`}
              title="Generate a new VRL transform with AI"
            >
              ✨ New with AI
            </button>
          )}
        </div>

        {error && (
          <div className="mx-2 mt-2 rounded-lg bg-destructive/10 px-2 py-1.5 flex items-start gap-1.5">
            <span className="text-xs text-destructive flex-1">{error}</span>
            <button onClick={() => setError(null)} className="text-destructive/60 hover:text-destructive text-xs">✕</button>
          </div>
        )}

        <div className="flex-1 overflow-y-auto py-2">
          {loadingLib ? (
            <div className="space-y-1 px-2">
              {[...Array(4)].map((_, i) => (
                <div key={i} className="h-8 bg-secondary rounded-lg animate-pulse" />
              ))}
            </div>
          ) : transforms.length === 0 ? (
            <p className="text-xs text-muted-foreground px-4 py-3">No saved transforms yet.</p>
          ) : (
            transforms.map((t) => (
              <button
                key={t.id}
                onClick={() => selectTransform(t)}
                className={`w-full text-left px-3 py-2 rounded-lg mx-1 text-xs transition-colors group flex items-center justify-between gap-1 ${
                  selected?.id === t.id
                    ? 'bg-primary/10 text-primary'
                    : 'text-muted-foreground hover:text-foreground hover:bg-secondary'
                }`}
              >
                <span className="truncate">{t.name}</span>
                {isEditor && (
                  <span
                    role="button"
                    onClick={(e) => { e.stopPropagation(); void handleDelete(t) }}
                    className="opacity-0 group-hover:opacity-100 text-muted-foreground/50 hover:text-destructive transition-all flex-shrink-0"
                    title="Delete"
                  >
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="h-3.5 w-3.5">
                      <path d="M18 6L6 18M6 6l12 12" strokeLinecap="round" />
                    </svg>
                  </span>
                )}
              </button>
            ))
          )}
        </div>
      </aside>

      {/* ── Main: editor + preview ── */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* Toolbar */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-border flex-shrink-0 bg-background">
          <div className="flex items-center gap-3 min-w-0">
            <span className="text-sm font-medium text-foreground truncate">
              {selected ? selected.name : 'New transform'}
            </span>
            {dirty && <span className="text-xs text-muted-foreground flex-shrink-0">● unsaved</span>}
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            <button onClick={exportCurrent} className={btnGhost} title="Download this VRL as a .vrl file">
              ⤓ Export
            </button>
            <button
              onClick={runValidate}
              disabled={testState.status === 'running'}
              className={btnSecondary}
              title="Compile-check and run with the bundled Vector — no instance needed"
            >
              Validate
            </button>
            <button onClick={runTest} disabled={testState.status === 'running'} className={btnPrimary} title="Run against a live Vector instance">
              {testState.status === 'running' ? (
                <span className="flex items-center gap-2">
                  <span className="h-3.5 w-3.5 border-2 border-primary-foreground/30 border-t-primary-foreground rounded-full animate-spin" />
                  Running…
                </span>
              ) : (
                'Run ▶'
              )}
            </button>
            {isEditor && (
              <button onClick={() => setShowSaveModal(true)} className={btnSecondary}>
                {selected && !dirty ? 'Saved' : 'Save'}
              </button>
            )}
          </div>
        </div>

        {/* Split: VRL editor (top) + input/output (bottom) */}
        <div className="flex-1 min-h-0 flex flex-col">
          <div className="flex-[55] min-h-0 border-b border-border">
            <VrlEditor value={vrl} onChange={isEditor ? handleVrlChange : undefined} readOnly={!isEditor} />
          </div>

          <div className="flex-[45] min-h-0 flex divide-x divide-border">
            {/* Input event */}
            <div className="flex-1 flex flex-col min-w-0">
              <div className="flex items-center justify-between px-4 py-2 border-b border-border flex-shrink-0">
                <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Input event</span>
                <button onClick={() => setEventJson(DEFAULT_EVENT)} className={btnGhost} title="Reset to example">
                  Reset
                </button>
              </div>
              <div className="flex-1 min-h-0">
                <VrlEditor value={eventJson} onChange={setEventJson} language="json" />
              </div>
            </div>

            {/* Output */}
            <div className="flex-1 flex flex-col min-w-0">
              <div className="px-4 py-2 border-b border-border flex-shrink-0 flex items-center gap-2">
                <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Output</span>
                {testState.status === 'success' && (
                  <span className="text-xs text-primary">✓ success</span>
                )}
                {testState.status === 'error' && (
                  <span className="text-xs text-destructive">✗ error</span>
                )}
                {testState.status !== 'idle' && testState.status !== 'running' && testState.via && (
                  <span className="ml-auto text-xs text-muted-foreground truncate">via {testState.via}</span>
                )}
              </div>
              <div className="flex-1 min-h-0">
                {testState.status === 'idle' && (
                  <div className="h-full flex items-center justify-center px-4 text-center">
                    <p className="text-xs text-muted-foreground">
                      <span className="text-foreground">Validate</span> compile-checks instantly (no instance);{' '}
                      <span className="text-foreground">Run ▶</span> executes on a live instance.
                    </p>
                  </div>
                )}
                {testState.status === 'running' && (
                  <div className="h-full flex items-center justify-center">
                    <div className="h-5 w-5 border-2 border-border border-t-primary rounded-full animate-spin" />
                  </div>
                )}
                {testState.status === 'success' && (
                  <VrlEditor
                    value={JSON.stringify(testState.output, null, 2)}
                    readOnly
                    language="json"
                  />
                )}
                {testState.status === 'error' && (
                  <div className="p-4 h-full overflow-auto">
                    <pre className="text-xs text-destructive whitespace-pre-wrap font-mono leading-relaxed">
                      {testState.message}
                    </pre>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>

      {showSaveModal && (
        <SaveModal
          initial={{ name: selected?.name ?? '', description: selected?.description ?? '' }}
          onSave={handleSave}
          onClose={() => setShowSaveModal(false)}
        />
      )}

      {showAi && (
        <AiGenerateModal
          initialEvent={eventJson}
          onClose={() => setShowAi(false)}
          onAccept={(generated) => {
            // Drop into a fresh draft and prompt to name + save.
            setSelected(null)
            setVrl(generated)
            setDirty(true)
            setTestState({ status: 'idle' })
            setShowSaveModal(true)
          }}
        />
      )}
    </div>
      )}
    </div>
  )
}

function SaveModal({
  initial,
  onSave,
  onClose,
}: {
  initial: { name: string; description: string }
  onSave: (name: string, description: string) => Promise<void>
  onClose: () => void
}) {
  const [name, setName] = useState(initial.name)
  const [description, setDescription] = useState(initial.description)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim()) { setError('Name is required'); return }
    setSaving(true)
    try {
      await onSave(name.trim(), description.trim())
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(typeof detail === 'string' ? detail : 'Failed to save transform — check your connection and retry.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div className="bg-card border border-border rounded-xl w-full max-w-md shadow-xl">
        <div className="flex items-center justify-between px-6 py-4 border-b border-border">
          <h2 className="text-sm font-semibold text-foreground">Save transform</h2>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="h-4 w-4">
              <path d="M18 6L6 18M6 6l12 12" strokeLinecap="round" />
            </svg>
          </button>
        </div>
        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-muted-foreground">Name <span className="text-destructive">*</span></label>
            <input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} placeholder="parse-nginx-access" autoFocus />
          </div>
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-muted-foreground">Description</label>
            <input className={inputCls} value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Parses nginx access logs into structured fields" />
          </div>
          {error && <p className="text-xs text-destructive">{error}</p>}
          <div className="flex justify-end gap-3 pt-1">
            <button type="button" onClick={onClose} className={btnSecondary}>Cancel</button>
            <button type="submit" disabled={saving} className={btnPrimary}>
              {saving ? 'Saving…' : 'Save transform'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
