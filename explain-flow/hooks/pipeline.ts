/**
 * The render pipeline with its I/O injected, so the hooks module and the
 * tests run the same code: structure → references → resolvers → annotate.
 */
import type { Explanation } from '../types'
import { resolverFor, type Config, type ResolverSpec } from './config'
import {
  annotate,
  collectRefChecks,
  textCheck,
  validateStructure,
  type CheckOutcome,
  type RefCheck,
} from './model'

export type ResolverRequest = {
  root: string
  checks: {
    key: string
    path: string
    line: number
    end: number
    role: RefCheck['role']
    code?: string
    via?: string
  }[]
}

export type ResolverAnswer = {
  results: Record<string, { status: CheckOutcome['status']; reason?: string }>
  notes?: string[]
}

export type PipelineIO = {
  /** The file's text, or null when it does not exist. */
  readFile: (path: string) => Promise<string | null>
  /** Runs a resolver; null when it could not run or answered nonsense. */
  runResolver: (spec: ResolverSpec, mode: 'verify', request: ResolverRequest) => Promise<ResolverAnswer | null>
}

export type PipelineResult =
  | { ok: false; errors: string[]; warnings: string[] }
  | {
      ok: true
      explanation: Explanation
      warnings: string[]
      stats: { refs: number; verified: number; unverified: number; resolvers: string[] }
    }

export async function runPipeline(
  x: Explanation,
  config: Config,
  repoRoot: string,
  io: PipelineIO,
): Promise<PipelineResult> {
  const structure = validateStructure(x)
  if (structure.errors.length) return { ok: false, ...structure }

  const { checks, errors: refFormat } = collectRefChecks(x)
  const errors = [...refFormat]
  const warnings = [...structure.warnings]

  // group the checks by resolver; everything else gets the text check
  const groups = new Map<string, { spec: ResolverSpec; items: { key: string; check: RefCheck }[] }>()
  const plain: RefCheck[] = []
  checks.forEach((check, i) => {
    const spec = resolverFor(config, check.path)
    if (!spec) return plain.push(check)
    const g = groups.get(spec.name) ?? { spec, items: [] }
    g.items.push({ key: String(i), check })
    groups.set(spec.name, g)
  })

  const outcomes: { check: RefCheck; outcome: CheckOutcome; by: string }[] = []
  const usedResolvers: string[] = []
  const fileCache = new Map<string, string | null>()
  const read = async (p: string) => {
    if (!fileCache.has(p)) fileCache.set(p, await io.readFile(p))
    return fileCache.get(p)!
  }

  for (const { spec, items } of groups.values()) {
    const answer = await io.runResolver(spec, 'verify', {
      root: repoRoot,
      checks: items.map(({ key, check }) => ({
        key,
        path: check.path,
        line: check.line,
        end: check.end,
        role: check.role,
        code: check.code,
        via: check.via,
      })),
    })
    if (!answer) {
      warnings.push(`resolver ${spec.name} did not run; its references got the text check only`)
      for (const { check } of items) plain.push(check)
      continue
    }
    usedResolvers.push(spec.name)
    for (const n of answer.notes ?? []) warnings.push(`${spec.name}: ${n}`)
    for (const { key, check } of items) {
      const r = answer.results[key]
      if (!r) {
        plain.push(check)
        continue
      }
      outcomes.push({ check, outcome: { status: r.status, reason: r.reason }, by: spec.name })
    }
  }
  for (const check of plain) outcomes.push({ check, outcome: textCheck(check, await read(check.path)), by: 'text' })

  for (const { check, outcome } of outcomes) {
    if (outcome.status === 'error') errors.push(`${check.where}: ${check.ref}: ${outcome.reason ?? 'invalid reference'}`)
  }
  if (errors.length) return { ok: false, errors, warnings }

  const calls = outcomes.filter(o => o.check.target)
  return {
    ok: true,
    explanation: annotate(x, outcomes),
    warnings,
    stats: {
      refs: outcomes.length,
      verified: calls.filter(o => o.outcome.status === 'verified').length,
      unverified: calls.filter(o => o.outcome.status === 'unverified').length,
      resolvers: [...usedResolvers, ...(plain.length ? ['text'] : [])],
    },
  }
}

export function formatIssues(r: { errors?: string[]; warnings: string[] }): string {
  const parts: string[] = []
  if (r.errors?.length) parts.push('Errors (fix these and call the tool again):\n' + r.errors.map(e => `- ${e}`).join('\n'))
  if (r.warnings.length) parts.push('Warnings:\n' + r.warnings.map(w => `- ${w}`).join('\n'))
  return parts.join('\n\n')
}
