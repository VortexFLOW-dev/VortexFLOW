// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

/**
 * NodeTap — collapsible "Live output" section for the Flow node drawer. Taps the
 * selected node's live events in place (reusing the Live Tap engine), with a
 * before/after toggle for remaps — so you see what a transform does to real data
 * without leaving the canvas.
 */

import { useState } from 'react'
import { useTapStream, TapLog } from '@/components/shared/LiveTap'

interface Props {
  // Which Vector instance to tap (a reachable node in the fleet), or null.
  instanceId: string | null
  // The node's rendered Vector id (its output), or undefined if not tappable.
  vectorId?: string
  // For a remap: the rendered ids of its inputs → enables before/after.
  inputIds?: string[]
  nodeName: string
}

export default function NodeTap({ instanceId, vectorId, inputIds, nodeName }: Props) {
  const [open, setOpen] = useState(false)
  const [compare, setCompare] = useState(false)
  const after = useTapStream()
  const before = useTapStream()

  const canCompare = (inputIds?.length ?? 0) > 0
  const comparing = compare && canCompare
  const running = after.running || before.running
  const tappable = !!vectorId && !!instanceId

  const start = () => {
    if (!instanceId || !vectorId) return
    void after.start(instanceId, vectorId, 50)
    if (comparing) void before.start(instanceId, (inputIds ?? []).join(','), 50)
  }
  const stop = () => {
    after.stop()
    before.stop()
  }
  const clearAll = () => {
    after.clear()
    before.clear()
  }

  return (
    <div className="flex-shrink-0 border-t border-border">
      <div className="flex items-center justify-between px-4 py-2">
        <button
          onClick={() => setOpen((o) => !o)}
          className="text-xs text-muted-foreground hover:text-foreground transition-colors"
        >
          {open ? '▾' : '▸'} Live output
        </button>
        {open && tappable && (
          <button
            onClick={running ? stop : start}
            className="text-xs text-primary hover:text-primary/80 transition-colors"
          >
            {running ? 'Stop' : '▶ Start'}
          </button>
        )}
      </div>

      {open && (
        <div className="px-2 pb-2">
          {!tappable ? (
            <p className="px-2 pb-2 text-xs text-muted-foreground/60">
              {!instanceId
                ? 'No reachable instance in this fleet to tap.'
                : 'This node has no output to tap.'}
            </p>
          ) : (
            <>
              {canCompare && (
                <label className="flex items-center gap-2 px-2 py-1.5 text-[11px] text-foreground cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={compare}
                    onChange={(e) => setCompare(e.target.checked)}
                    disabled={running}
                    className="accent-primary"
                  />
                  Compare before / after
                </label>
              )}
              {comparing ? (
                <div className="grid grid-cols-2 gap-2">
                  <TapLog
                    title="Before"
                    stream={before}
                    running={running}
                    onClear={clearAll}
                    heightClass="h-[220px]"
                  />
                  <TapLog
                    title="After"
                    stream={after}
                    running={running}
                    onClear={clearAll}
                    heightClass="h-[220px]"
                  />
                </div>
              ) : (
                <TapLog
                  title={nodeName}
                  waitingFor={nodeName}
                  stream={after}
                  running={running}
                  onClear={clearAll}
                  heightClass="h-[220px]"
                />
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}
