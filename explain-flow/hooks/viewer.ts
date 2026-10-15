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

/** What a saved page says about itself in its <head>, for listings. */
export type PageMeta = {
  title: string
  description: string
  issue?: string
  repo?: string
  generated?: string
}

const META_PREFIX = 'explain-flow:'
const DESCRIPTION_MAX = 200

function clip(s: string, max: number): string {
  const flat = s.replace(/\[\[ref:[^\]]*\]\]/g, '').replace(/\s+/g, ' ').trim()
  return flat.length > max ? `${flat.slice(0, max - 1).trimEnd()}…` : flat
}

/** The question if there is one, else the first block: what the reader asked. */
export function pageMeta(x: Explanation, repoRoot: string, generatedAt: string): PageMeta {
  const first = x.blocks[0]
  const description = x.question || x.scope.focus || (first ? `${first.title ? `${first.title}: ` : ''}${first.text}` : '')
  return {
    title: x.topic,
    description: clip(description, DESCRIPTION_MAX),
    issue: x.scope.issue,
    repo: repoRoot.replace(/\/+$/, '').split('/').pop() || undefined,
    generated: generatedAt,
  }
}

function metaTags(m: PageMeta): string {
  const tag = (name: string, value: string | undefined) =>
    value ? `<meta name="${name}" content="${escapeHtml(value)}">` : ''
  return [
    tag('description', m.description),
    tag(`${META_PREFIX}issue`, m.issue),
    tag(`${META_PREFIX}repo`, m.repo),
    tag(`${META_PREFIX}generated`, m.generated),
  ]
    .filter(Boolean)
    .join('\n')
}

function unescapeHtml(s: string): string {
  return s.replace(/&(amp|lt|gt|quot|#39);/g, (_, e: string) => ({ amp: '&', lt: '<', gt: '>', quot: '"', '#39': "'" })[e]!)
}

/** Reads `pageMeta` back from a saved page's <head>; null when it has none. */
export function readPageMeta(html: string): PageMeta | null {
  const head = /<head>([\s\S]*?)<\/head>/i.exec(html)?.[1] ?? html.slice(0, 8192)
  const title = /<title>([\s\S]*?)<\/title>/i.exec(head)?.[1]
  if (title === undefined) return null
  const meta = (name: string) => {
    const m = new RegExp(`<meta name="${name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}" content="([^"]*)">`, 'i').exec(head)
    return m ? unescapeHtml(m[1]!) : undefined
  }
  return {
    title: unescapeHtml(title.trim()),
    description: meta('description') ?? '',
    issue: meta(`${META_PREFIX}issue`),
    repo: meta(`${META_PREFIX}repo`),
    generated: meta(`${META_PREFIX}generated`),
  }
}

export function buildHtml(template: string, elkSource: string, data: ViewerData): string {
  // one pass with a replacer function: inserted text is never re-scanned and
  // its `$` sequences are taken literally
  const values: Record<string, string> = {
    __TITLE__: escapeHtml(data.explanation.topic),
    __META__: metaTags(pageMeta(data.explanation, data.repoRoot, data.generatedAt)),
    __MODEL_JSON__: scriptJson(data),
    '/*__ELK__*/': elkSource.replace(/<\/script/gi, '<\\/script'),
  }
  return template.replace(/__TITLE__|__META__|__MODEL_JSON__|\/\*__ELK__\*\//g, m => values[m]!)
}
