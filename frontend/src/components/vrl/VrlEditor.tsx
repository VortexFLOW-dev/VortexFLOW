// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

import { lazy, Suspense } from 'react'
import type { VrlEditorProps } from './VrlEditorImpl'

// Lazy-load the Monaco-backed editor so Monaco (a large dependency, now bundled
// locally rather than fetched from a CDN) lands in its own chunk and is fetched
// only when an editor is actually shown — keeping it out of the initial bundle.
const VrlEditorImpl = lazy(() => import('./VrlEditorImpl'))

export default function VrlEditor(props: VrlEditorProps) {
  return (
    <Suspense
      fallback={
        <div
          style={{ height: props.height ?? '100%' }}
          className="flex items-center justify-center text-xs text-muted-foreground bg-background"
        >
          Loading editor…
        </div>
      }
    >
      <VrlEditorImpl {...props} />
    </Suspense>
  )
}
