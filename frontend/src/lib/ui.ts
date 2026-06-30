// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

// Shared style tokens so button/input vocabulary is uniform across the app
// instead of being copy-pasted (and drifting) per page.

export const btnPrimary =
  'bg-primary hover:bg-primary/90 text-primary-foreground font-medium text-sm px-4 py-2 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed'

export const btnSecondary =
  'text-muted-foreground hover:text-foreground text-sm px-4 py-2 rounded-lg hover:bg-secondary transition-colors disabled:opacity-50'

export const btnGhost =
  'text-muted-foreground hover:text-foreground text-xs px-2 py-1.5 rounded transition-colors hover:bg-secondary'

export const btnDanger =
  'text-destructive hover:text-destructive text-sm px-4 py-2 rounded-lg hover:bg-destructive/10 transition-colors disabled:opacity-50'

export const inputCls =
  'w-full bg-background border border-border rounded-lg px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary focus:border-primary'

// Uppercase section label used inside page bodies / panels.
export const sectionLabel = 'text-[11px] uppercase tracking-wider text-muted-foreground/50'
