/**
 * Builds the offline browser view: the fixed template with ELK and the
 * explanation inlined, so the file opens anywhere with no network. Pure.
 */
import type { Explanation } from '../types'

export type ViewerData = {
  explanation: Explanation
  repoRoot: string
  editorUrl: string
  generatedAt: string
}

/** JSON that is safe inside a <script> element. */
export function scriptJson(value: unknown): string {
  return JSON.stringify(value)
    .replace(/</g, '\\u003c')
    .replace(/>/g, '\\u003e')
    .replace(/\u2028/g, '\\u2028')
    .replace(/\u2029/g, '\\u2029')
}

function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]!)
}

export function buildHtml(template: string, elkSource: string, data: ViewerData): string {
  // one pass with a replacer function: inserted text is never re-scanned and
  // its `$` sequences are taken literally
  const values: Record<string, string> = {
    __TITLE__: escapeHtml(data.explanation.topic),
    __MODEL_JSON__: scriptJson(data),
    '/*__ELK__*/': elkSource.replace(/<\/script/gi, '<\\/script'),
  }
  return template.replace(/__TITLE__|__MODEL_JSON__|\/\*__ELK__\*\//g, m => values[m]!)
}
