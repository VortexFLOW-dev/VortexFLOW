// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

/**
 * Bundle Monaco locally instead of fetching it from cdn.jsdelivr.net at runtime.
 *
 * `@monaco-editor/react` defaults to loading the editor from a CDN — a runtime
 * phone-home that contradicts VortexFlow's self-hosted / no-telemetry pitch and
 * forces the CSP to allow an external script source. Pointing `loader` at the
 * bundled `monaco-editor` package serves everything from 'self'.
 *
 * Side-effect module: import once before any <Editor> mounts.
 */
import { loader } from '@monaco-editor/react'
import * as monaco from 'monaco-editor'
import editorWorker from 'monaco-editor/esm/vs/editor/editor.worker?worker'
import jsonWorker from 'monaco-editor/esm/vs/language/json/json.worker?worker'

// VRL uses a custom Monarch tokenizer (no worker); JSON uses its language worker.
// Vite bundles these workers locally via the ?worker suffix.
self.MonacoEnvironment = {
  getWorker(_workerId: string, label: string) {
    if (label === 'json') return new jsonWorker()
    return new editorWorker()
  },
}

loader.config({ monaco })
