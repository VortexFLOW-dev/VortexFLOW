// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

import { useState } from 'react'
import { transformsApi } from '@/lib/api'
import Modal from '@/components/ui/Modal'
import VrlEditor from '@/components/vrl/VrlEditor'
import { btnPrimary, btnSecondary, inputCls } from '@/lib/ui'

const labelCls = 'block text-xs font-medium text-muted-foreground mb-1'

const DEFAULT_EVENT = `{
  "message": "hello from vector",
  "host": "web-01",
  "level": "info"
}`

interface GenResult {
  ok: boolean
  vrl: string
  before?: Record<string, unknown> | null
  after?: Record<string, unknown> | null
  attempts: number
  error?: string | null
  source: string
}

// Shared "generate VRL with AI" panel — used by the Library ("New with AI") and
// the Flow node drawer ("Generate with AI"). Intent + sample event in; a
// validated VRL candidate + before/after out; `onAccept` hands the VRL back.
export default function AiGenerateModal({
  onClose,
  onAccept,
  initialEvent,
  currentVrl,
}: {
  onClose: () => void
  onAccept: (vrl: string) => void
  initialEvent?: string
  currentVrl?: string
}) {
  const [intent, setIntent] = useState('')
  const [eventText, setEventText] = useState(initialEvent?.trim() || DEFAULT_EVENT)
  const [generating, setGenerating] = useState(false)
  const [result, setResult] = useState<GenResult | null>(null)
  const [editedVrl, setEditedVrl] = useState('')
  const [error, setError] = useState<string | null>(null)

  const generate = async () => {
    setError(null)
    if (!intent.trim()) {
      setError('Describe what the transform should do.')
      return
    }
    let event: object
    try {
      event = JSON.parse(eventText)
    } catch {
      setError('Sample event is not valid JSON.')
      return
    }
    setGenerating(true)
    setResult(null)
    try {
      const r = await transformsApi.aiGenerate({
        intent: intent.trim(),
        event,
        current_vrl: currentVrl,
      })
      const data = r.data as GenResult
      setResult(data)
      setEditedVrl(data.vrl ?? '')
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail ?? 'Generation request failed.')
    } finally {
      setGenerating(false)
    }
  }

  return (
    <Modal title="Generate VRL with AI" onClose={onClose} maxWidth="max-w-2xl">
      <div className="p-5 space-y-4">
        <p className="text-xs text-muted-foreground leading-relaxed">
          Describe what you want; the assistant writes VRL, compiles it with{' '}
          <code>vector</code>, and self-repairs on error — you only ever see VRL that compiles.
          The sample below is sent to your configured model (redacted fields excluded).
        </p>

        <div>
          <label className={labelCls}>What should this transform do?</label>
          <textarea
            className={`${inputCls} min-h-[64px] resize-y`}
            value={intent}
            onChange={(e) => setIntent(e.target.value)}
            placeholder="e.g. Parse the JSON in .message into top-level fields and drop debug logs"
          />
        </div>

        <div>
          <label className={labelCls}>Sample event (JSON)</label>
          <textarea
            className={`${inputCls} font-mono text-xs min-h-[100px] resize-y`}
            value={eventText}
            onChange={(e) => setEventText(e.target.value)}
            spellCheck={false}
          />
          <p className="text-[11px] text-muted-foreground/60 mt-1">
            Grounds the generation. The result is validated against this event.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button onClick={() => void generate()} disabled={generating} className={btnPrimary}>
            {generating ? 'Generating…' : result ? 'Regenerate' : 'Generate'}
          </button>
          {error && <span className="text-xs text-destructive">{error}</span>}
        </div>

        {result && (
          <div className="space-y-3 border-t border-border pt-4">
            {!result.ok && (
              <div className="text-xs rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-destructive">
                Couldn't produce valid VRL after {result.attempts} attempt
                {result.attempts === 1 ? '' : 's'}
                {result.source === 'unavailable'
                  ? ' (the server-side Vector validator is unavailable on this deployment).'
                  : '. The model may be too small for VRL — try a more capable model or rephrase the intent.'}
                {result.error && (
                  <pre className="mt-1 whitespace-pre-wrap font-mono text-[11px] opacity-80 max-h-32 overflow-auto">
                    {result.error}
                  </pre>
                )}
              </div>
            )}

            <div>
              <label className={labelCls}>
                Generated VRL{' '}
                {result.ok && (
                  <span className="text-emerald-400">
                    ✓ validated ({result.attempts} attempt{result.attempts === 1 ? '' : 's'})
                  </span>
                )}
              </label>
              <div className="h-48 border border-border rounded-lg overflow-hidden">
                <VrlEditor value={editedVrl} onChange={setEditedVrl} />
              </div>
            </div>

            {result.ok && (
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className={labelCls}>Before</label>
                  <pre className="text-[11px] font-mono bg-background border border-border rounded-lg p-2 max-h-40 overflow-auto">
                    {JSON.stringify(result.before ?? {}, null, 2)}
                  </pre>
                </div>
                <div>
                  <label className={labelCls}>After</label>
                  <pre className="text-[11px] font-mono bg-background border border-border rounded-lg p-2 max-h-40 overflow-auto">
                    {JSON.stringify(result.after ?? {}, null, 2)}
                  </pre>
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      <div className="border-t border-border px-5 py-3 flex items-center gap-2 flex-shrink-0">
        <button
          onClick={() => {
            onAccept(editedVrl)
            onClose()
          }}
          disabled={!editedVrl.trim()}
          className={btnPrimary + ' disabled:opacity-40'}
        >
          Use this VRL
        </button>
        <button onClick={onClose} className={btnSecondary}>
          Cancel
        </button>
      </div>
    </Modal>
  )
}
