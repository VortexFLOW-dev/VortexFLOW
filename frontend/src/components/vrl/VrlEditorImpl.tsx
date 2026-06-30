// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

import '@/lib/monaco-setup' // bundle Monaco locally (no jsdelivr CDN) — must precede <Editor>
import Editor, { useMonaco } from '@monaco-editor/react'
import { useEffect } from 'react'
import { useTheme } from '@/lib/theme'

export interface VrlEditorProps {
  value: string
  onChange?: (value: string) => void
  readOnly?: boolean
  height?: string
  language?: 'vrl' | 'json'
}

const VRL_KEYWORDS = [
  'if', 'else', 'for', 'while', 'loop', 'abort', 'return', 'null', 'true', 'false',
  'del', 'exists', 'assert', 'log', 'to_string', 'to_int', 'to_float', 'to_bool',
  'to_timestamp', 'parse_json', 'parse_syslog', 'parse_regex', 'parse_grok',
  'encode_json', 'encode_base64', 'decode_base64', 'sha256', 'md5',
  'upcase', 'downcase', 'strip_whitespace', 'split', 'join', 'slice',
  'contains', 'starts_with', 'ends_with', 'replace', 'length',
  'push', 'pop', 'flatten', 'compact', 'keys', 'values', 'merge',
  'now', 'format_timestamp', 'parse_timestamp', 'truncate_timestamp',
  'get_hostname', 'get_env_var', 'uuid_v4', 'floor', 'ceil', 'round',
  'ip_subnet', 'ip_cidr_contains', 'is_null', 'is_nullish', 'is_empty',
  'is_string', 'is_integer', 'is_float', 'is_boolean', 'is_array', 'is_object',
]

export default function VrlEditorImpl({ value, onChange, readOnly = false, height = '100%', language = 'vrl' }: VrlEditorProps) {
  const monaco = useMonaco()
  const { theme } = useTheme()

  useEffect(() => {
    if (!monaco) return

    const langs = monaco.languages.getLanguages()
    const themesRegistered = langs.find((l) => l.id === 'vrl')

    if (!themesRegistered) {
      monaco.languages.register({ id: 'vrl', extensions: ['.vrl'], aliases: ['VRL', 'vrl'] })

      monaco.languages.setMonarchTokensProvider('vrl', {
        keywords: VRL_KEYWORDS,
        tokenizer: {
          root: [
            [/#[^\n]*/, 'comment'],
            [/"([^"\\]|\\.)*"/, 'string'],
            [/'([^'\\]|\\.)*'/, 'string'],
            [/\b\d+(\.\d+)?\b/, 'number'],
            [/\.([\w]+)/, 'variable.other'],
            [/\b(true|false|null)\b/, 'keyword'],
            [new RegExp(`\\b(${VRL_KEYWORDS.join('|')})\\b`), 'keyword'],
            [/[a-zA-Z_][\w]*/, 'identifier'],
            [/[{}()[\]]/, 'delimiter.bracket'],
            [/[<>!=]=?|&&|\|\|/, 'operator'],
          ],
        },
      })

      monaco.languages.setLanguageConfiguration('vrl', {
        comments: { lineComment: '#' },
        brackets: [['(', ')'], ['{', '}'], ['[', ']']],
        autoClosingPairs: [
          { open: '(', close: ')' },
          { open: '{', close: '}' },
          { open: '[', close: ']' },
          { open: '"', close: '"' },
        ],
        surroundingPairs: [
          { open: '(', close: ')' },
          { open: '{', close: '}' },
          { open: '"', close: '"' },
        ],
      })

      monaco.editor.defineTheme('vortexflow-dark', {
        base: 'vs-dark',
        inherit: true,
        rules: [
          { token: 'comment', foreground: '71717a', fontStyle: 'italic' },
          { token: 'string', foreground: '86efac' },
          { token: 'number', foreground: 'fb923c' },
          { token: 'keyword', foreground: '818cf8' },
          { token: 'variable.other', foreground: '2dd4bf' },
          { token: 'operator', foreground: 'e4e4e7' },
          { token: 'identifier', foreground: 'e4e4e7' },
          { token: 'delimiter.bracket', foreground: '71717a' },
        ],
        colors: {
          'editor.background': '#09090b',
          'editor.foreground': '#e4e4e7',
          'editor.lineHighlightBackground': '#18181b',
          'editor.selectionBackground': '#3f3f4680',
          'editorLineNumber.foreground': '#3f3f46',
          'editorLineNumber.activeForeground': '#71717a',
          'editorIndentGuide.background1': '#27272a',
          'editorCursor.foreground': '#14b8a6',
          'editor.inactiveSelectionBackground': '#3f3f4640',
          'scrollbar.shadow': '#00000000',
          'scrollbarSlider.background': '#3f3f4660',
          'scrollbarSlider.hoverBackground': '#52525b80',
          'editorWidget.background': '#18181b',
          'editorSuggestWidget.background': '#18181b',
          'editorSuggestWidget.border': '#3f3f46',
          'editorSuggestWidget.selectedBackground': '#27272a',
        },
      })

      monaco.editor.defineTheme('vortexflow-light', {
        base: 'vs',
        inherit: true,
        rules: [
          { token: 'comment', foreground: '71717a', fontStyle: 'italic' },
          { token: 'string', foreground: '16a34a' },
          { token: 'number', foreground: 'd97706' },
          { token: 'keyword', foreground: '4f46e5' },
          { token: 'variable.other', foreground: '0d9488' },
          { token: 'operator', foreground: '18181b' },
          { token: 'identifier', foreground: '18181b' },
          { token: 'delimiter.bracket', foreground: '71717a' },
        ],
        colors: {
          'editor.background': '#ffffff',
          'editor.foreground': '#18181b',
          'editor.lineHighlightBackground': '#f4f4f5',
          'editor.selectionBackground': '#0d948820',
          'editorLineNumber.foreground': '#d4d4d8',
          'editorLineNumber.activeForeground': '#a1a1aa',
          'editorIndentGuide.background1': '#e4e4e7',
          'editorCursor.foreground': '#0d9488',
          'editor.inactiveSelectionBackground': '#0d948810',
          'scrollbar.shadow': '#00000000',
          'scrollbarSlider.background': '#d4d4d860',
          'scrollbarSlider.hoverBackground': '#a1a1aa80',
          'editorWidget.background': '#ffffff',
          'editorSuggestWidget.background': '#ffffff',
          'editorSuggestWidget.border': '#e4e4e7',
          'editorSuggestWidget.selectedBackground': '#f4f4f5',
        },
      })
    }

    monaco.editor.setTheme(theme === 'dark' ? 'vortexflow-dark' : 'vortexflow-light')
  }, [monaco, theme])

  return (
    <Editor
      height={height}
      language={language === 'vrl' ? 'vrl' : 'json'}
      value={value}
      theme={theme === 'dark' ? 'vortexflow-dark' : 'vortexflow-light'}
      onChange={(v) => onChange?.(v ?? '')}
      options={{
        readOnly,
        fontSize: 13,
        fontFamily: '"JetBrains Mono", "Fira Code", "Cascadia Code", monospace',
        fontLigatures: true,
        lineNumbers: 'on',
        minimap: { enabled: false },
        scrollBeyondLastLine: false,
        wordWrap: 'on',
        tabSize: 2,
        padding: { top: 12, bottom: 12 },
        renderLineHighlight: 'line',
        smoothScrolling: true,
        cursorBlinking: 'smooth',
        bracketPairColorization: { enabled: true },
        suggest: { showKeywords: true },
        overviewRulerLanes: 0,
        hideCursorInOverviewRuler: true,
        scrollbar: { verticalScrollbarSize: 4, horizontalScrollbarSize: 4 },
      }}
    />
  )
}
