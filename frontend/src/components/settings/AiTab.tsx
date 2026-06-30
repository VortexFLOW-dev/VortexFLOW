// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

import { useEffect, useState } from 'react'
import { settingsApi } from '@/lib/api'
import { btnPrimary, btnSecondary, inputCls } from '@/lib/ui'

const labelCls = 'block text-xs font-medium text-muted-foreground mb-1'

// Sentinel the backend understands as "keep the stored key unchanged".
const MASK = '••••••••'

type Provider = 'anthropic' | 'openai' | 'self_hosted'

const PROVIDERS: { value: Provider; label: string; badge: string }[] = [
  { value: 'anthropic', label: 'Anthropic (Claude)', badge: 'Hosted' },
  { value: 'openai', label: 'OpenAI', badge: 'Hosted' },
  { value: 'self_hosted', label: 'Self-hosted (Ollama / vLLM)', badge: 'No egress' },
]

const MODEL_HINT: Record<Provider, string> = {
  anthropic: 'e.g. claude-opus-4-8, claude-sonnet-4-6',
  openai: 'e.g. gpt-4o, gpt-4o-mini',
  self_hosted: 'e.g. llama3.1, qwen2.5-coder — whatever your endpoint serves',
}

function Toggle({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      type="button"
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-5 w-9 flex-shrink-0 rounded-full border-2 border-transparent transition-colors focus:outline-none ${
        checked ? 'bg-primary' : 'bg-secondary'
      }`}
    >
      <span
        className={`inline-block h-4 w-4 rounded-full bg-background border border-border shadow-sm transition-transform ${
          checked ? 'translate-x-4' : 'translate-x-0'
        }`}
      />
    </button>
  )
}

export default function AiTab() {
  const [enabled, setEnabled] = useState(false)
  const [provider, setProvider] = useState<Provider>('anthropic')
  const [baseUrl, setBaseUrl] = useState('')
  const [model, setModel] = useState('claude-opus-4-8')
  const [redactFields, setRedactFields] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [keySet, setKeySet] = useState(false)
  const [keyError, setKeyError] = useState(false)

  const [loaded, setLoaded] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{
    ok: boolean
    latency_ms?: number | null
    error?: string | null
  } | null>(null)

  useEffect(() => {
    settingsApi
      .getAi()
      .then((r) => {
        const d = r.data
        setEnabled(!!d.enabled)
        setProvider((d.provider as Provider) ?? 'anthropic')
        setBaseUrl(d.base_url ?? '')
        setModel(d.model ?? '')
        setRedactFields((d.redact_fields ?? []).join(', '))
        setKeySet(!!d.api_key_set)
        setKeyError(!!d.key_error)
      })
      .catch(() => setError('Failed to load AI settings'))
      .finally(() => setLoaded(true))
  }, [])

  const save = async () => {
    setSaving(true)
    setError(null)
    try {
      // Empty input + a stored key ⇒ send MASK to preserve it. A typed value
      // replaces it. Empty + no stored key ⇒ send empty (no key).
      const keyToSend = apiKey.trim() ? apiKey.trim() : keySet ? MASK : ''
      const r = await settingsApi.putAi({
        enabled,
        provider,
        base_url: baseUrl.trim(),
        model: model.trim(),
        redact_fields: redactFields
          .split(',')
          .map((f) => f.trim())
          .filter(Boolean),
        api_key: keyToSend,
      })
      setKeySet(!!r.data.api_key_set)
      setKeyError(!!r.data.key_error)
      setApiKey('')
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail ?? 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  // Explicitly remove the stored key (empty input alone only preserves it).
  const clearKey = async () => {
    setSaving(true)
    setError(null)
    try {
      const r = await settingsApi.putAi({
        enabled: false, // can't stay enabled on a keyed provider with no key
        provider,
        base_url: baseUrl.trim(),
        model: model.trim(),
        redact_fields: redactFields.split(',').map((f) => f.trim()).filter(Boolean),
        clear_api_key: true,
      })
      setEnabled(!!r.data.enabled)
      setKeySet(!!r.data.api_key_set)
      setKeyError(!!r.data.key_error)
      setApiKey('')
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(detail ?? 'Failed to clear the key')
    } finally {
      setSaving(false)
    }
  }

  // Tests the *saved* config — the key never round-trips through the request.
  const test = async () => {
    setTesting(true)
    setTestResult(null)
    try {
      const r = await settingsApi.testAi()
      setTestResult({ ok: r.data.ok, latency_ms: r.data.latency_ms, error: r.data.error })
    } catch {
      setTestResult({ ok: false, error: 'Test request failed' })
    } finally {
      setTesting(false)
    }
  }

  if (!loaded) {
    return <div className="h-40 bg-card border border-border rounded-xl animate-pulse" />
  }

  const keyless = provider === 'self_hosted'

  return (
    <div className="space-y-6 max-w-lg">
      <div className="p-3 bg-secondary/50 rounded-lg text-xs text-muted-foreground leading-relaxed">
        The AI assistant writes <strong>validated</strong> VRL from a description and a sample event
        — every suggestion is compiled with <code>vector vrl</code> and self-repaired before you see
        it. It's <strong>opt-in</strong> and
        <strong> bring-your-own-model</strong>: VortexFlow never phones home. Point it at a
        self-hosted endpoint (Ollama / vLLM) for a fully air-gapped, no-egress setup.
      </div>

      {/* Enable */}
      <div className="flex items-center gap-4 border border-border rounded-xl px-5 py-4 bg-card">
        <Toggle checked={enabled} onChange={setEnabled} />
        <div className="flex-1 min-w-0">
          <div className="text-sm font-medium text-foreground">Enable AI assistant</div>
          <p className="text-xs text-muted-foreground mt-0.5">
            When off, no events are ever sent to any model.
          </p>
        </div>
        {enabled && (
          <span className="text-xs text-emerald-400 bg-emerald-400/10 px-2 py-0.5 rounded-full">
            Enabled
          </span>
        )}
      </div>

      {/* Provider */}
      <div>
        <label className={labelCls}>Provider</label>
        <select
          className="w-full bg-background border border-border rounded-lg px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
          value={provider}
          onChange={(e) => setProvider(e.target.value as Provider)}
        >
          {PROVIDERS.map((p) => (
            <option key={p.value} value={p.value}>
              {p.label} — {p.badge}
            </option>
          ))}
        </select>
        {keyless && (
          <p className="text-[11px] text-muted-foreground mt-1">
            Self-hosted endpoints on your own network keep event data fully in your control — this
            is the privacy/air-gapped path. An API key is optional.
          </p>
        )}
      </div>

      {/* Base URL (required for self-hosted) */}
      <div>
        <label className={labelCls}>
          {keyless ? 'Endpoint URL' : 'Base URL'}{' '}
          {keyless && <span className="text-destructive">*</span>}
        </label>
        <input
          className={inputCls}
          value={baseUrl}
          onChange={(e) => setBaseUrl(e.target.value)}
          placeholder={
            keyless ? 'http://localhost:11434/v1' : 'optional — override the default API endpoint'
          }
        />
        <p className="text-[11px] text-muted-foreground/60 mt-1">
          {keyless
            ? 'OpenAI-compatible endpoint (Ollama, vLLM, LiteLLM, …).'
            : 'Leave blank to use the provider default.'}
        </p>
      </div>

      {/* Model */}
      <div>
        <label className={labelCls}>Model</label>
        <input
          className={inputCls}
          value={model}
          onChange={(e) => setModel(e.target.value)}
          placeholder={MODEL_HINT[provider]}
        />
        <p className="text-[11px] text-muted-foreground/60 mt-1">{MODEL_HINT[provider]}</p>
      </div>

      {/* API key */}
      <div>
        <label className={labelCls}>
          API key {!keyless && <span className="text-destructive">*</span>}
        </label>
        <input
          type="password"
          className={`${inputCls} font-mono`}
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          placeholder={
            keySet ? `${MASK} (stored — leave blank to keep)` : keyless ? 'optional' : 'sk-…'
          }
          autoComplete="new-password"
        />
        <div className="flex items-center justify-between mt-1">
          <p className="text-[11px] text-muted-foreground/60">
            Stored encrypted at rest. Never shown again after saving.
          </p>
          {keySet && (
            <button
              type="button"
              onClick={() => void clearKey()}
              disabled={saving}
              className="text-[11px] text-muted-foreground hover:text-destructive transition-colors"
            >
              Clear stored key
            </button>
          )}
        </div>
        {keyError && (
          <p className="text-[11px] text-amber-400 mt-1">
            A key is stored but can't be decrypted — VORTEXFLOW_SECRET_KEY may have changed.
            Re-enter the key or clear it.
          </p>
        )}
      </div>

      {/* Redaction */}
      <div>
        <label className={labelCls}>Redact fields before sending (optional)</label>
        <input
          className={inputCls}
          value={redactFields}
          onChange={(e) => setRedactFields(e.target.value)}
          placeholder="e.g. message, user.ssn, headers.authorization"
        />
        <p className="text-[11px] text-muted-foreground/60 mt-1">
          Comma-separated dotted field paths. These are stripped from the sample event before it
          reaches the model. Default sends the raw sample.
        </p>
      </div>

      <div className="flex items-center gap-3 pt-1">
        <button onClick={() => void save()} disabled={saving} className={btnPrimary}>
          {saving ? 'Saving…' : 'Save'}
        </button>
        <button
          onClick={() => void test()}
          disabled={testing || saving}
          className={btnSecondary + ' disabled:opacity-50'}
          title="Tests the saved configuration"
        >
          {testing ? 'Testing…' : 'Test connection'}
        </button>
        {saved && <span className="text-xs text-emerald-400">✓ Saved</span>}
        {error && <span className="text-xs text-destructive">{error}</span>}
      </div>

      {testResult && (
        <div
          className={`text-xs rounded-lg border px-3 py-2 ${
            testResult.ok
              ? 'border-emerald-400/30 bg-emerald-400/10 text-emerald-400'
              : 'border-destructive/30 bg-destructive/10 text-destructive'
          }`}
        >
          {testResult.ok
            ? `✓ Connected${testResult.latency_ms != null ? ` (${testResult.latency_ms} ms)` : ''}`
            : `✗ ${testResult.error ?? 'Connection failed'}`}
          <span className="block text-[11px] text-muted-foreground/70 mt-0.5">
            Tests the saved configuration — save first if you've made changes.
          </span>
        </div>
      )}
    </div>
  )
}
