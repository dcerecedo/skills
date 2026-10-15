/**
 * Structural checks on an explanation the model hands the render tool, and
 * the list of code references to check against the repo. Pure: no `$`.
 */
import type {
  Block,
  Diagram,
  Explanation,
  GraphDiagram,
  Message,
  SequenceDiagram,
  Step,
  Via,
} from '../types'

export type ParsedRef = { path: string; line: number; end: number }

/** What a reference is expected to point at. */
export type Role = 'def' | 'call' | 'any'

export type RefCheck = {
  /** Where in the model it sits, for error messages: `seq/s3`, `block b2`. */
  where: string
  ref: string
  path: string
  line: number
  end: number
  role: Role
  code?: string
  via?: Via
  /** Diagram and element id when the outcome annotates an interaction. */
  target?: { diagram: string; element: string }
}

export type Issues = { errors: string[]; warnings: string[] }

export const MAX_STEPS = 25
export const SOFT_MAX_STEPS = 15
export const MAX_BLOCKS = 12

const REF_RE = /^(?<path>[^:\s][^:]*?):(?<line>\d+)(?:-(?<end>\d+))?$/
const INLINE_REF_RE = /\[\[ref:([^\]]+)\]\]/g

export function parseRef(ref: string): ParsedRef | null {
  const m = REF_RE.exec(ref.trim())
  if (!m?.groups) return null
  const line = Number(m.groups.line)
  const end = m.groups.end ? Number(m.groups.end) : line
  if (line < 1 || end < line) return null
  return { path: m.groups.path!.replace(/^\.\//, ''), line, end }
}

export function inlineRefs(text: string): string[] {
  return [...text.matchAll(INLINE_REF_RE)].map(m => m[1]!.trim())
}

export function slugify(topic: string): string {
  const s = topic
    .toLowerCase()
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 60)
  return s || 'explanation'
}

export function isSequence(d: Diagram): d is SequenceDiagram {
  return d.kind === 'sequence'
}

export function walkSteps(steps: Step[], visit: (s: Step) => void) {
  for (const s of steps) {
    visit(s)
    if (s.type === 'fragment') for (const b of s.branches ?? []) walkSteps(b.steps ?? [], visit)
  }
}

export function isMessage(s: Step): s is Message {
  return s.type !== 'fragment' && s.type !== 'collapsed' && s.type !== 'note'
}

/** Every element id a block may highlight in a diagram. */
export function elementIds(d: Diagram): Set<string> {
  const ids = new Set<string>()
  if (isSequence(d)) {
    for (const p of d.participants ?? []) ids.add(p.id)
    walkSteps(d.steps ?? [], s => ids.add(s.id))
  } else {
    for (const n of d.nodes ?? []) ids.add(n.id)
    for (const e of d.edges ?? []) ids.add(e.id)
  }
  return ids
}

function checkUnique(ids: string[], where: string, errors: string[]) {
  const seen = new Set<string>()
  for (const id of ids) {
    if (typeof id !== 'string' || id === '') errors.push(`${where}: an element has no id`)
    else if (seen.has(id)) errors.push(`${where}: id "${id}" is used twice`)
    seen.add(id)
  }
}

function checkGraph(d: GraphDiagram, issues: Issues) {
  const w = `diagram ${d.id}`
  if (!Array.isArray(d.nodes) || d.nodes.length === 0) issues.errors.push(`${w}: has no nodes`)
  if (!Array.isArray(d.edges)) issues.errors.push(`${w}: edges must be a list`)
  const nodes = new Set((d.nodes ?? []).map(n => n.id))
  for (const n of d.nodes ?? []) {
    const pseudo = ['initial', 'final', 'start', 'end', 'fork'].includes(n.kind ?? '')
    if (!n.label && !pseudo) issues.errors.push(`${w}/${n.id}: node has no label`)
    if (n.parent && !nodes.has(n.parent))
      issues.errors.push(`${w}/${n.id}: parent "${n.parent}" is not a node`)
  }
  for (const e of d.edges ?? []) {
    if (!nodes.has(e.from)) issues.errors.push(`${w}/${e.id}: from "${e.from}" is not a node`)
    if (!nodes.has(e.to)) issues.errors.push(`${w}/${e.id}: to "${e.to}" is not a node`)
  }
}

function checkSequence(d: SequenceDiagram, issues: Issues, componentIds: Set<string>) {
  const w = `diagram ${d.id}`
  if (!Array.isArray(d.participants) || d.participants.length < 2)
    issues.errors.push(`${w}: needs at least two participants`)
  if (!Array.isArray(d.steps) || d.steps.length === 0) issues.errors.push(`${w}: has no steps`)
  const parts = new Set((d.participants ?? []).map(p => p.id))
  for (const p of d.participants ?? []) {
    if (!p.label) issues.errors.push(`${w}/${p.id}: participant has no label`)
    if (p.component && !componentIds.has(p.component))
      issues.errors.push(`${w}/${p.id}: component "${p.component}" is not a node of a component diagram`)
  }
  let messages = 0
  walkSteps(d.steps ?? [], s => {
    const at = `${w}/${s.id}`
    if (s.type === 'fragment') {
      if (!Array.isArray(s.branches) || s.branches.length === 0)
        issues.errors.push(`${at}: fragment has no branches`)
      return
    }
    if (s.type === 'note') {
      for (const p of s.over ?? []) if (!parts.has(p)) issues.errors.push(`${at}: note over unknown "${p}"`)
      return
    }
    if (s.type === 'collapsed') {
      if (!parts.has(s.from)) issues.errors.push(`${at}: from "${s.from}" is not a participant`)
      if (s.to && !parts.has(s.to)) issues.errors.push(`${at}: to "${s.to}" is not a participant`)
      if (!(s.hiddenCalls >= 1)) issues.errors.push(`${at}: hiddenCalls must be at least 1`)
      return
    }
    messages++
    if (!['sync', 'async', 'return', 'self', 'create'].includes(s.type))
      issues.errors.push(`${at}: unknown step type "${(s as { type: string }).type}"`)
    if (!parts.has(s.from)) issues.errors.push(`${at}: from "${s.from}" is not a participant`)
    if (!parts.has(s.to)) issues.errors.push(`${at}: to "${s.to}" is not a participant`)
    if (!s.label) issues.errors.push(`${at}: message has no label`)
    if (s.type !== 'return' && !s.ref)
      issues.warnings.push(`${at}: message has no ref; it cannot be verified`)
  })
  if (messages > MAX_STEPS)
    issues.errors.push(
      `${w}: ${messages} messages; compact to ${SOFT_MAX_STEPS} or fewer, or split the flow into two sequence diagrams by phase`,
    )
  else if (messages > SOFT_MAX_STEPS)
    issues.warnings.push(`${w}: ${messages} messages; consider compacting to ${SOFT_MAX_STEPS} or fewer`)
}

function checkBlocks(blocks: Block[], diagrams: Diagram[], issues: Issues) {
  const byId = new Map(diagrams.map(d => [d.id, d]))
  const ids = new Map(diagrams.map(d => [d.id, elementIds(d)]))
  const covered = new Map(diagrams.map(d => [d.id, new Set<string>()]))
  if (blocks.length === 0) issues.errors.push('blocks: at least one prose block is needed')
  if (blocks.length > MAX_BLOCKS) issues.errors.push(`blocks: ${blocks.length} blocks; keep it to ${MAX_BLOCKS} or fewer`)
  for (const b of blocks) {
    const w = `block ${b.id}`
    if (!b.text?.trim()) issues.errors.push(`${w}: has no text`)
    const hl = b.highlights ?? {}
    if (Object.keys(hl).length === 0) issues.errors.push(`${w}: highlights nothing in any diagram`)
    for (const [diagram, list] of Object.entries(hl)) {
      if (!byId.has(diagram)) {
        issues.errors.push(`${w}: highlights unknown diagram "${diagram}"`)
        continue
      }
      for (const el of list ?? []) {
        if (!ids.get(diagram)!.has(el)) issues.errors.push(`${w}: "${el}" is not an element of ${diagram}`)
        else covered.get(diagram)!.add(el)
      }
    }
  }
  for (const d of diagrams) {
    if (isSequence(d)) {
      const missing: string[] = []
      walkSteps(d.steps ?? [], s => {
        if (isMessage(s) && s.type !== 'return' && !covered.get(d.id)!.has(s.id)) missing.push(s.id)
      })
      if (missing.length)
        issues.warnings.push(`diagram ${d.id}: no block explains ${missing.join(', ')}`)
    }
  }
}

/** Structural validation. Errors block rendering; warnings go back with the result. */
export function validateStructure(x: Explanation): Issues {
  const issues: Issues = { errors: [], warnings: [] }
  if (!x || typeof x !== 'object') return { errors: ['explanation must be an object'], warnings: [] }
  if (!x.topic?.trim()) issues.errors.push('topic is empty')
  if (!x.scope?.entry) issues.errors.push('scope.entry is missing')
  if (!Array.isArray(x.diagrams)) return { ...issues, errors: [...issues.errors, 'diagrams must be a list'] }
  if (!Array.isArray(x.blocks)) return { ...issues, errors: [...issues.errors, 'blocks must be a list'] }

  checkUnique(x.diagrams.map(d => d.id), 'diagrams', issues.errors)
  checkUnique(x.blocks.map(b => b.id), 'blocks', issues.errors)
  if (!x.diagrams.some(d => d.kind === 'component')) issues.errors.push('diagrams: a component diagram is required')
  if (!x.diagrams.some(d => d.kind === 'sequence')) issues.errors.push('diagrams: a sequence diagram is required')

  const componentIds = new Set(
    x.diagrams.filter(d => d.kind === 'component').flatMap(d => (d as GraphDiagram).nodes?.map(n => n.id) ?? []),
  )
  for (const d of x.diagrams) {
    if (!d.title) issues.errors.push(`diagram ${d.id}: has no title`)
    if (isSequence(d)) {
      const ids: string[] = (d.participants ?? []).map(p => p.id)
      walkSteps(d.steps ?? [], s => ids.push(s.id))
      checkUnique(ids, `diagram ${d.id}`, issues.errors)
      checkSequence(d, issues, componentIds)
    } else if (d.kind === 'component' || d.kind === 'state' || d.kind === 'activity') {
      checkUnique([...(d.nodes ?? []).map(n => n.id), ...(d.edges ?? []).map(e => e.id)], `diagram ${d.id}`, issues.errors)
      checkGraph(d, issues)
    } else {
      issues.errors.push(`diagram ${(d as { id: string }).id}: unknown kind "${(d as { kind: string }).kind}"`)
    }
  }
  if (issues.errors.length === 0) checkBlocks(x.blocks, x.diagrams, issues)
  return issues
}

/** Every reference in the model, with what it should point at. */
export function collectRefChecks(x: Explanation): { checks: RefCheck[]; errors: string[] } {
  const checks: RefCheck[] = []
  const errors: string[] = []
  const add = (where: string, ref: string | undefined, role: Role, extra: Partial<RefCheck> = {}) => {
    if (!ref) return
    const p = parseRef(ref)
    if (!p) {
      errors.push(`${where}: "${ref}" is not a path:line reference`)
      return
    }
    checks.push({ where, ref, ...p, role, ...extra })
  }
  add('scope.entry', x.scope.entry, 'any')
  for (const d of x.diagrams) {
    if (isSequence(d)) {
      for (const p of d.participants) add(`${d.id}/${p.id}`, p.ref, 'def', { code: p.code })
      walkSteps(d.steps, s => {
        if (isMessage(s)) {
          const role: Role = s.type === 'return' ? 'any' : 'call'
          add(`${d.id}/${s.id}`, s.ref, role, {
            code: s.code,
            via: s.via,
            target: role === 'call' ? { diagram: d.id, element: s.id } : undefined,
          })
        } else if (s.type === 'collapsed') {
          for (const r of s.refs ?? []) add(`${d.id}/${s.id}`, r, 'any')
        }
      })
    } else {
      for (const n of d.nodes) add(`${d.id}/${n.id}`, n.ref, 'def', { code: n.code })
      for (const e of d.edges)
        add(`${d.id}/${e.id}`, e.ref, e.code ? 'call' : 'any', {
          code: e.code,
          via: e.via,
          target: e.code ? { diagram: d.id, element: e.id } : undefined,
        })
    }
  }
  for (const b of x.blocks) for (const r of inlineRefs(b.text)) add(`block ${b.id}`, r, 'any')
  return { checks, errors }
}

/** The last identifier of a dotted symbol: `LockService.issue_code` → `issue_code`. */
export function lastSegment(code: string): string {
  const cleaned = code.replace(/\(.*$/s, '').trim()
  const parts = cleaned.split(/[.#:]+|::/).filter(Boolean)
  return parts[parts.length - 1] ?? cleaned
}

export type CheckOutcome = {
  status: 'ok' | 'verified' | 'unverified' | 'error'
  reason?: string
}

/**
 * The stack-agnostic check: the file exists and holds the line, and the
 * symbol's last segment appears within three lines of it. Never `verified`:
 * text search can place a name, not prove a call.
 */
export function textCheck(check: RefCheck, fileText: string | null): CheckOutcome {
  if (fileText === null) return { status: 'error', reason: `${check.path} does not exist` }
  const lines = fileText.split('\n')
  if (check.end > lines.length)
    return { status: 'error', reason: `${check.path} has ${lines.length} lines; line ${check.end} is past the end` }
  if (!check.code || check.role === 'any') return { status: 'ok' }
  const name = lastSegment(check.code)
  const word = new RegExp(`(^|[^A-Za-z0-9_$])${name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}([^A-Za-z0-9_$]|$)`)
  const from = Math.max(0, check.line - 4)
  const to = Math.min(lines.length, check.end + 3)
  for (let i = from; i < to; i++) {
    if (word.test(lines[i]!)) {
      return check.role === 'call'
        ? { status: 'unverified', reason: `"${name}" appears at line ${i + 1}; no resolver checked the call` }
        : { status: 'ok' }
    }
  }
  const elsewhere = lines.findIndex(l => word.test(l))
  return {
    status: 'error',
    reason:
      elsewhere >= 0
        ? `"${name}" is not within 3 lines of ${check.ref}; it appears at line ${elsewhere + 1}`
        : `"${name}" does not appear in ${check.path}`,
  }
}

/** Writes call outcomes onto the interactions they belong to. */
export function annotate(
  x: Explanation,
  outcomes: { check: RefCheck; outcome: CheckOutcome; by: string }[],
): Explanation {
  const copy: Explanation = JSON.parse(JSON.stringify(x))
  const byTarget = new Map<string, { status: 'verified' | 'unverified'; by: string; reason?: string }>()
  for (const { check, outcome, by } of outcomes) {
    if (!check.target) continue
    if (outcome.status !== 'verified' && outcome.status !== 'unverified') continue
    byTarget.set(`${check.target.diagram}\u0000${check.target.element}`, {
      status: outcome.status,
      by,
      reason: outcome.reason,
    })
  }
  for (const d of copy.diagrams) {
    if (isSequence(d)) {
      walkSteps(d.steps, s => {
        if (isMessage(s)) {
          const v = byTarget.get(`${d.id}\u0000${s.id}`)
          if (v) s.verification = v
        }
      })
    } else {
      for (const e of d.edges) {
        const v = byTarget.get(`${d.id}\u0000${e.id}`)
        if (v) e.verification = v
      }
    }
  }
  return copy
}
