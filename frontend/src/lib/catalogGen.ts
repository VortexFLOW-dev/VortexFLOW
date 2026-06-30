// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

/**
 * Runtime Vector-schema → catalog converter.
 *
 * Single source of truth for turning Vector's `generate-schema` JSON into
 * source/sink config forms. Used both at runtime (the Catalog fetches the live
 * schema from the backend's bundled Vector) and at build time (scripts/gen-catalog
 * regenerates the bundled fallback). Keep it pure — no DOM, no fs.
 *
 * Ported from the original gen-catalog script; the conversion logic is unchanged.
 */
import type { CatalogComponent, CatalogField, FieldType } from './catalog'

/* eslint-disable @typescript-eslint/no-explicit-any */
type Node = any

const GROUPED_BLOCKS: Record<string, string> = {
  batch: 'Reliability',
  buffer: 'Reliability',
  acknowledgements: 'Reliability',
  healthcheck: 'Reliability',
  request: 'Request',
  tls: 'TLS',
  encoding: 'Encoding',
  decoding: 'Encoding',
  framing: 'Encoding',
  auth: 'Auth',
}
const MAX_DEPTH = 2
const SKIP_TYPES = new Set(['unit_test', 'unit_test_stream'])

export function schemaToCatalog(schema: Node): {
  sources: CatalogComponent[]
  sinks: CatalogComponent[]
} {
  const DEFS: Record<string, Node> = (schema && schema.definitions) || {}

  const refKey = (ref: string) => ref.replace(/^#\/definitions\//, '')

  function deref(node: Node): Node {
    let cur = node
    let guard = 0
    while (cur && cur.$ref && guard++ < 32) {
      const target = DEFS[refKey(cur.$ref)]
      if (!target) break
      const { $ref, ...siblings } = cur
      cur = { ...target, ...siblings }
    }
    return cur || node
  }

  function unwrapOption(node: Node): Node {
    if (!node) return node
    const union = node.oneOf || node.anyOf
    if (Array.isArray(union)) {
      const nonNull = union.filter((b: Node) => !(b && b.type === 'null'))
      if (nonNull.length === 1 && nonNull.length < union.length) {
        const { oneOf, anyOf, ...rest } = node
        return { ...rest, ...nonNull[0] }
      }
    }
    return node
  }

  const constValue = (branch: Node) =>
    branch && typeof branch.const === 'string' ? branch.const : undefined

  function extractEnum(node: Node): string[] | undefined {
    if (!node) return undefined
    if (Array.isArray(node.enum)) {
      const vals = node.enum.filter((v: Node) => typeof v === 'string')
      if (vals.length) return vals
    }
    for (const key of ['oneOf', 'anyOf']) {
      const union = node[key]
      if (!Array.isArray(union)) continue
      const consts = union.map(constValue).filter((v: Node) => v !== undefined)
      if (
        consts.length &&
        consts.length === union.filter((b: Node) => !(b && b.type === 'null')).length
      ) {
        return consts
      }
      for (const branch of union) {
        const nested = branch.oneOf || branch.anyOf
        if (Array.isArray(nested)) {
          const nc = nested.map(constValue).filter((v: Node) => v !== undefined)
          if (nc.length && nc.length === nested.length) return nc
        }
      }
    }
    return undefined
  }

  function scalarType(node: Node): string | undefined {
    let t = node.type
    if (Array.isArray(t)) t = t.find((x: string) => x !== 'null')
    return t
  }

  const humanize = (s: string) =>
    s
      .replace(/[_-]+/g, ' ')
      .replace(/::/g, ' ')
      .trim()
      .replace(/\s+/g, ' ')
      .replace(/^\w/, (c) => c.toUpperCase())

  function firstSentence(desc?: string): string | undefined {
    if (!desc) return undefined
    let s = desc.replace(/\n+/g, ' ').replace(/\s+/g, ' ').trim()
    s = s.replace(/\[([^\]]+)\]\[[^\]]+\]/g, '$1').replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    const m = s.match(/^(.*?[.!?])(\s|$)/)
    return (m ? m[1] : s).slice(0, 200)
  }

  function exampleString(node: Node): string | undefined {
    const ex = node._metadata && node._metadata['docs::examples']
    if (ex === undefined || ex === null) return undefined
    const v = Array.isArray(ex) ? ex[0] : ex
    if (typeof v === 'string') return v
    if (typeof v === 'number' || typeof v === 'boolean') return String(v)
    return undefined
  }

  function mergeObject(node: Node): Node {
    let n = unwrapOption(deref(node))
    if (Array.isArray(n.allOf)) {
      const merged: Node = {
        type: 'object',
        properties: {},
        required: [],
        _metadata: n._metadata,
      }
      for (const part of n.allOf) {
        const p = mergeObject(part)
        Object.assign(merged.properties, p.properties || {})
        if (Array.isArray(p.required)) merged.required.push(...p.required)
        if (p.description && !merged.description) merged.description = p.description
      }
      if (n.properties) Object.assign(merged.properties, n.properties)
      if (Array.isArray(n.required)) merged.required.push(...n.required)
      return merged
    }
    return n
  }

  function normalize(node: Node): Node {
    let n = node
    for (let i = 0; i < 8; i++) {
      const before = n
      n = deref(n)
      n = unwrapOption(n)
      if (
        n === before ||
        (!n.$ref && !(n.oneOf && n.oneOf.some((b: Node) => b && b.type === 'null')))
      )
        break
    }
    return n
  }

  function pushField(fields: CatalogField[], f: Node): void {
    if (fields.some((x) => x.key === f.key)) return
    const clean: Node = {}
    for (const [k, v] of Object.entries(f)) if (v !== undefined) clean[k] = v
    fields.push(clean as CatalogField)
  }

  function walkProperties(
    objNode: Node,
    fields: CatalogField[],
    opts: { prefix: string; group?: string; depth: number },
  ): void {
    const node = mergeObject(objNode)
    const props = node.properties || {}
    const required = new Set<string>(node.required || [])
    for (const [name, rawChild] of Object.entries(props)) {
      if (name === 'type') continue
      const child = deref(rawChild)
      const meta = child._metadata || {}
      if (meta['docs::hidden'] || child.deprecated) continue
      const prefix = opts.prefix
      const dottedKey = prefix ? `${prefix}.${name}` : name
      const group = opts.group || (prefix ? undefined : GROUPED_BLOCKS[name])
      emitField({ key: dottedKey, node: child, required: required.has(name), group, depth: opts.depth, fields })
    }
  }

  function emitField(args: {
    key: string
    node: Node
    required: boolean
    group?: string
    depth: number
    fields: CatalogField[]
  }): void {
    const { key, required, group, depth, fields } = args
    const node = normalize(args.node)
    const meta = node._metadata || {}
    const label = humanize(meta['docs::human_name'] || key.split('.').pop())
    const hint = firstSentence(node.description || node.title)
    const placeholder = exampleString(node)

    const enumVals = extractEnum(node)
    if (enumVals && enumVals.length) {
      pushField(fields, {
        key,
        label,
        type: 'select',
        required,
        default: typeof node.default === 'string' ? node.default : undefined,
        hint,
        group,
        options: enumVals.map((v) => ({ value: v, label: humanize(v) })),
      })
      return
    }

    const t = scalarType(node)
    const merged = node.allOf ? mergeObject(node) : node
    const hasProps = merged.properties && Object.keys(merged.properties).length > 0
    const isMap = (node.additionalProperties || merged.additionalProperties) && !hasProps
    if (t === 'object' || hasProps || isMap) {
      if (isMap) {
        pushField(fields, { key, label, type: 'textarea', required, hint, group, placeholder })
        return
      }
      if (hasProps) {
        const cap = group ? 1 : MAX_DEPTH
        const nextDepth = depth + 1
        if (nextDepth > cap) return
        walkProperties(merged, fields, { prefix: key, group, depth: nextDepth })
        return
      }
      return
    }

    let type: FieldType
    if (t === 'boolean') type = 'boolean'
    else if (t === 'integer' || t === 'number') type = 'number'
    else if (t === 'array') {
      const items = node.items ? unwrapOption(deref(node.items)) : undefined
      const it = items ? scalarType(items) : undefined
      if (it === 'object') return
      type = 'array'
    } else if (t === 'string' || t === undefined) {
      type = 'string'
    } else {
      return
    }

    let def: string | number | boolean | undefined
    if (type === 'number' && typeof node.default === 'number') def = node.default
    else if (type === 'boolean' && typeof node.default === 'boolean') def = node.default
    else if (type === 'string' && typeof node.default === 'string') def = node.default

    pushField(fields, { key, label, type, required, default: def, hint, group, placeholder })
  }

  function collectDiscriminator(node: Node, propName: string): string[] {
    const out = new Set<string>()
    const seen = new Set<string>()
    const visit = (raw: Node) => {
      if (!raw || typeof raw !== 'object') return
      let n = unwrapOption(raw)
      if (n.$ref) n = deref(n)
      const props = n.properties
      if (props && props[propName] && typeof props[propName].const === 'string') {
        out.add(props[propName].const)
      }
      for (const key of ['oneOf', 'anyOf', 'allOf']) {
        if (Array.isArray(n[key])) {
          for (const branch of n[key]) {
            const sig = branch && branch.$ref
            if (sig) {
              if (seen.has(sig)) continue
              seen.add(sig)
            }
            visit(branch)
          }
        }
      }
    }
    visit(node)
    return [...out]
  }

  function collapseEncoding(objNode: Node, fields: CatalogField[]): boolean {
    const node = mergeObject(objNode)
    const enc = node.properties && node.properties.encoding
    if (!enc) return false
    const codecs = collectDiscriminator(deref(enc), 'codec')
    if (!codecs.length) return false
    pushField(fields, {
      key: 'encoding.codec',
      label: 'Encoding',
      type: 'select',
      group: 'Encoding',
      options: codecs.map((v) => ({ value: v, label: humanize(v) })),
    })
    return true
  }

  function collapseAuth(objNode: Node, fields: CatalogField[]): boolean {
    const node = mergeObject(objNode)
    const auth = node.properties && node.properties.auth
    if (!auth) return false
    const strategies = collectDiscriminator(unwrapOption(deref(auth)), 'strategy')
    if (!strategies.length) return false
    pushField(fields, {
      key: 'auth.strategy',
      label: 'Auth strategy',
      type: 'select',
      group: 'Auth',
      default: '',
      options: [
        { value: '', label: 'None' },
        ...strategies.map((v) => ({ value: v, label: humanize(v) })),
      ],
    })
    return true
  }

  function buildComponent(typeName: string, configRef: string, description?: string): CatalogComponent {
    const config = mergeObject({ $ref: configRef })
    const fields: CatalogField[] = []
    const hasEncoding = collapseEncoding(config, fields)
    const hasAuth = collapseAuth(config, fields)
    const props = config.properties || {}
    const required = new Set<string>(config.required || [])
    for (const [name, rawChild] of Object.entries(props)) {
      if (name === 'type') continue
      if (name === 'encoding' && hasEncoding) continue
      if (name === 'auth' && hasAuth) continue
      const child = deref(rawChild)
      const meta = child._metadata || {}
      if (meta['docs::hidden'] || child.deprecated) continue
      const group = GROUPED_BLOCKS[name]
      emitField({ key: name, node: child, required: required.has(name), group, depth: 0, fields })
    }
    return {
      type: typeName,
      name: humanize(typeName),
      description: firstSentence(description) || `Vector ${typeName} component.`,
      category: 'Generated',
      generated: true,
      fields,
    }
  }

  function resolveUnion(outerRef: string): Node {
    const outer = deref({ $ref: outerRef })
    if (outer.oneOf || outer.anyOf) return outer
    if (Array.isArray(outer.allOf)) {
      for (const part of outer.allOf) {
        const p = deref(part)
        if (p.oneOf || p.anyOf) return p
      }
    }
    return outer
  }

  function isBetter(a: CatalogComponent, b: CatalogComponent): boolean {
    if (a.fields.length !== b.fields.length) return a.fields.length > b.fields.length
    const aUrl = a.description.startsWith('http')
    const bUrl = b.description.startsWith('http')
    return aUrl !== bUrl ? !aUrl : false
  }

  function buildKind(outerRef: string): CatalogComponent[] {
    const union = resolveUnion(outerRef)
    const variants = union.oneOf || union.anyOf || []
    const byType = new Map<string, CatalogComponent>()
    for (const variant of variants) {
      const parts = variant.allOf || []
      let configRef: string | undefined
      let typeName: string | undefined
      const description = variant.description
      for (const part of parts) {
        if (part.$ref) configRef = part.$ref
        const typeConst = part.properties && part.properties.type && part.properties.type.const
        if (typeof typeConst === 'string') typeName = typeConst
      }
      if (!configRef || !typeName || SKIP_TYPES.has(typeName)) continue
      const component = buildComponent(typeName, configRef, description)
      const prev = byType.get(typeName)
      if (!prev || isBetter(component, prev)) byType.set(typeName, component)
    }
    return [...byType.values()].sort((a, b) => a.type.localeCompare(b.type))
  }

  return {
    sources: buildKind('vector::config::source::SourceOuter'),
    sinks: buildKind('vector::config::sink::SinkOuter<alloc::string::String>'),
  }
}
