// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

/*
 * gen-catalog-manifest.ts — emit catalog.manifest.json, a small, language-neutral
 * read surface for the Contract Drift Sentinel.
 *
 * It captures, from the SAME merged catalog the picker shows the user:
 *   - sources / sinks: the full set of selectable component types (curated +
 *     generated). This is the single source of truth for "what a user can pick".
 *   - inputs: a sha256 per file the catalog is derived from. The Sentinel's A1
 *     check recomputes these in Python (no node needed) to prove the committed
 *     catalog was regenerated after any input changed.
 *
 * It also emits the BACKEND's accepted-type list (backend/app/data/catalog_types.json,
 * kind-aware) from the same in-memory data — so the backend accepts exactly what
 * the picker offers and the allowlist can never drift from the catalog. The
 * Sentinel's C1 check guards that the two stay equal.
 *
 * Run via `pnpm gen:catalog` (chained after gen-catalog.ts) or standalone
 * `pnpm gen:catalog-manifest`. Regenerate whenever the catalog or schema changes.
 */
import crypto from 'crypto'
import fs from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'
import { SINKS, SOURCES } from '../src/lib/catalog'
import { GENERATED_SCHEMA_VERSION } from '../src/lib/catalog.generated'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const FE = path.join(__dirname, '..')
const OUT_PATH = path.join(FE, 'src', 'lib', 'catalog.manifest.json')
const BACKEND_OUT_PATH = path.join(FE, '..', 'backend', 'app', 'data', 'catalog_types.json')

const sha256 = (rel: string): string =>
  crypto
    .createHash('sha256')
    .update(fs.readFileSync(path.join(FE, rel)))
    .digest('hex')

// Every file the merged catalog is derived from. If any changes, the committed
// catalog (and this manifest) must be regenerated — A1 enforces that.
const INPUT_FILES = [
  `schema/vector-${GENERATED_SCHEMA_VERSION}-schema.json`,
  'src/lib/catalogGen.ts',
  'src/lib/catalog.ts',
  'src/lib/catalog.generated.ts',
]

const types = (list: { type: string }[]): string[] =>
  Array.from(new Set(list.map((c) => c.type))).sort()

const manifest = {
  // DO NOT EDIT BY HAND — regenerate with `pnpm gen:catalog-manifest`.
  schema_version: GENERATED_SCHEMA_VERSION,
  sources: types(SOURCES),
  sinks: types(SINKS),
  inputs: Object.fromEntries(INPUT_FILES.map((f) => [f, sha256(f)])),
}

fs.writeFileSync(OUT_PATH, JSON.stringify(manifest, null, 2) + '\n')
console.log(`Wrote src/lib/catalog.manifest.json`)
console.log(`  sources: ${manifest.sources.length}`)
console.log(`  sinks:   ${manifest.sinks.length}`)

// Backend accepted-type list (kind-aware), derived from the same data so the
// backend allowlist accepts exactly what the picker offers. Shipped in the
// backend image; read at import by app/schemas/component.py.
const backendTypes = {
  // DO NOT EDIT BY HAND — regenerate with `make catalog` / `pnpm gen:catalog`.
  schema_version: GENERATED_SCHEMA_VERSION,
  sources: manifest.sources,
  sinks: manifest.sinks,
}
fs.mkdirSync(path.dirname(BACKEND_OUT_PATH), { recursive: true })
fs.writeFileSync(BACKEND_OUT_PATH, JSON.stringify(backendTypes, null, 2) + '\n')
console.log(`Wrote backend/app/data/catalog_types.json`)
