// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

import { useState, useEffect } from 'react'
import { transformStagesApi, transformsApi } from '@/lib/api'
import { deleteGuarded } from '@/lib/deleteGuard'
import type { Component, TransformStage, VrlTransform } from '@/lib/types'
import VrlEditor from '@/components/vrl/VrlEditor'
import AiGenerateModal from '@/components/vrl/AiGenerateModal'
import { btnPrimary, btnSecondary, btnDanger, inputCls } from '@/lib/ui'

const labelCls = 'block text-xs font-medium text-muted-foreground mb-1'
const DEFAULT_VRL = '. = parse_json!(.message)\n'

interface FormState {
  name: string
  mode: 'inline' | 'library'
  source_vrl: string
  transform_id: string
  inputs: string[]
}

const emptyForm: FormState = { name: '', mode: 'inline', source_vrl: DEFAULT_VRL, transform_id: '', inputs: [] }

function formFromStage(s: TransformStage): FormState {
  return {
    name: s.name,
    mode: s.mode,
    source_vrl: s.source_vrl ?? DEFAULT_VRL,
    transform_id: s.transform_id ?? '',
    inputs: s.inputs,
  }
}

// Side-panel editor for a single remap stage. The parent owns the list + data
// loading; this component just edits one stage (inline VRL or a library template)
// and persists it. Reused by the unified Transforms list and (later) the Flow canvas.
export default function StageEditor({
  stage,
  fleetId,
  sources,
  stages,
  library,
  canEdit,
  onSaved,
  onClose,
  onDeleted,
}: {
  stage: TransformStage | 'new'
  fleetId: string
  sources: Component[]
  stages: TransformStage[]
  library: VrlTransform[]
  canEdit: boolean
  onSaved: () => void
  onClose: () => void
  onDeleted: () => void
}) {
  const isNew = stage === 'new'
  const [form, setForm] = useState<FormState>(isNew ? emptyForm : formFromStage(stage))
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [aiEnabled, setAiEnabled] = useState(false)
  const [showAi, setShowAi] = useState(false)

  useEffect(() => {
    if (!canEdit) return
    transformsApi.aiStatus().then((r) => setAiEnabled(!!r.data.enabled)).catch(() => {})
  }, [canEdit])

  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setForm((p) => ({ ...p, [k]: v }))

  const toggleInput = (id: string) =>
    setForm((p) => ({ ...p, inputs: p.inputs.includes(id) ? p.inputs.filter((x) => x !== id) : [...p.inputs, id] }))

  // Inputs the stage being edited can read: sources + other stages (not itself).
  const inputOptions = [
    ...sources.map((s) => ({ id: s.id, label: s.name, kind: 'source' })),
    ...stages.filter((s) => isNew || s.id !== stage.id).map((s) => ({ id: s.id, label: s.name, kind: 'remap' })),
  ]

  const save = async () => {
    if (!form.name.trim()) { setError('Name is required'); return }
    if (form.mode === 'inline' && !form.source_vrl.trim()) { setError('VRL is required'); return }
    if (form.mode === 'library' && !form.transform_id) { setError('Pick a library transform'); return }
    setSaving(true); setError(null)
    try {
      const payload = {
        name: form.name.trim(),
        mode: form.mode,
        source_vrl: form.mode === 'inline' ? form.source_vrl : undefined,
        transform_id: form.mode === 'library' ? form.transform_id : undefined,
        inputs: form.inputs,
      }
      if (isNew) {
        await transformStagesApi.create({ fleet_id: fleetId, ...payload })
      } else {
        await transformStagesApi.update(stage.id, payload)
      }
      onSaved()
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail ?? 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  const remove = async () => {
    if (isNew) return
    if (!confirm('Delete this remap?')) return
    try {
      if (await deleteGuarded((force) => transformStagesApi.delete(stage.id, force))) onDeleted()
    } catch { /* swallow */ }
  }

  return (
    <div className="w-[460px] flex-shrink-0 flex flex-col border-l border-border bg-card overflow-hidden">
      <div className="flex items-center justify-between px-5 py-3 border-b border-border flex-shrink-0">
        <div>
          <span className="text-sm font-medium text-foreground">{isNew ? 'New remap' : stage.name}</span>
          <p className="text-xs text-muted-foreground mt-0.5">
            Vector <code className="text-primary/80">remap</code> transform (VRL)
          </p>
        </div>
        <button onClick={onClose} className="text-muted-foreground hover:text-foreground text-xs">Close</button>
      </div>
      <div className="flex-1 overflow-y-auto p-5 space-y-4">
        <div>
          <label className={labelCls}>Name</label>
          <input className={inputCls} value={form.name} onChange={(e) => set('name', e.target.value)} placeholder="parse_syslog" disabled={!canEdit} />
        </div>

        <div>
          <label className={labelCls}>VRL source</label>
          <div className="flex gap-2 mb-2 items-center">
            {(['inline', 'library'] as const).map((m) => (
              <button key={m} onClick={() => set('mode', m)} disabled={!canEdit}
                className={`text-xs px-3 py-1 rounded-lg transition-colors ${form.mode === m ? 'bg-primary/10 text-primary' : 'text-muted-foreground hover:bg-secondary'}`}>
                {m === 'inline' ? 'Inline VRL' : 'Library template'}
              </button>
            ))}
            {canEdit && aiEnabled && form.mode === 'inline' && (
              <button
                onClick={() => setShowAi(true)}
                className="ml-auto text-xs px-3 py-1 rounded-lg text-primary hover:bg-primary/10 transition-colors"
                title="Generate this remap's VRL with AI"
              >
                ✨ Generate with AI
              </button>
            )}
          </div>
          {form.mode === 'inline' ? (
            <div className="h-48 border border-border rounded-lg overflow-hidden">
              <VrlEditor value={form.source_vrl} onChange={canEdit ? (v) => set('source_vrl', v) : undefined} readOnly={!canEdit} />
            </div>
          ) : (
            <select className={inputCls} value={form.transform_id} onChange={(e) => set('transform_id', e.target.value)} disabled={!canEdit}>
              <option value="">— select a library transform —</option>
              {library.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select>
          )}
        </div>

        <div>
          <label className={labelCls}>Inputs (what this remap reads)</label>
          {inputOptions.length === 0 ? (
            <p className="text-xs text-muted-foreground/60">No sources or remaps to read from yet.</p>
          ) : (
            <div className="space-y-1">
              {inputOptions.map((o) => (
                <label key={o.id} className="flex items-center gap-2 text-xs text-foreground">
                  <input type="checkbox" checked={form.inputs.includes(o.id)} onChange={() => toggleInput(o.id)} disabled={!canEdit} />
                  {o.label}
                  <span className="text-muted-foreground/50">{o.kind}</span>
                </label>
              ))}
            </div>
          )}
        </div>

        {error && <p className="text-xs text-destructive">{error}</p>}
      </div>
      {canEdit && (
        <div className="border-t border-border px-5 py-3 flex items-center gap-2 flex-shrink-0">
          <button onClick={() => { void save() }} disabled={saving} className={btnPrimary}>
            {saving ? 'Saving…' : isNew ? 'Create remap' : 'Save'}
          </button>
          <button onClick={onClose} className={btnSecondary}>Cancel</button>
          {!isNew && (
            <button onClick={() => { void remove() }} className={btnDanger + ' ml-auto'}>Delete</button>
          )}
        </div>
      )}

      {showAi && (
        <AiGenerateModal
          currentVrl={form.source_vrl}
          onClose={() => setShowAi(false)}
          onAccept={(generated) => {
            set('mode', 'inline')
            set('source_vrl', generated)
          }}
        />
      )}
    </div>
  )
}
