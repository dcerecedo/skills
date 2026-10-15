import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register, RenderInput } from 'claude-code'

import type { Explanation, Rendered, Selection } from '../types'
import { editorLink, PROJECT_CONFIG, resolveConfig, resolverFor, type Config, type ResolverSpec } from './config'
import { fileStem, formatStamp, inlineRefs, isSequence, parseRef, walkSteps } from './model'
import { formatIssues, runPipeline, type PipelineIO, type ResolverAnswer } from './pipeline'
import { buildHtml, pageMeta, readPageMeta, type PageMeta } from './viewer'

const PANE = 'explain-flow'
const RENDER_TOOL = 'render_flow_explanation'
const SEED_TOOL = 'trace_seed'
const LIST_TOOL = 'list_flow_explanations'
const OPEN_TOOL = 'open_flow_explanation'
const VIEW_COMMAND = 'flow-view'

const current = atom({ plugin: 'dcerecedo-skills', key: 'current' } as const, null as Rendered | null)
const selection = atom({ plugin: 'dcerecedo-skills', key: 'selection' } as const, { block: null, tab: null } as Selection)

const RENDER_DESCRIPTION = `Validate and render a control-flow explanation (see the explain-flow skill for how to build one).
Input: { "explanation": <Explanation> }. The tool checks every id, every highlight and every code reference against the repository (a language resolver for Python/Django, a text check otherwise). On problems it returns errors: fix them by re-reading the code, never by deleting the reference, and call it again. On success it writes the explanation as JSON and as an offline HTML view, opens the terminal pane, and returns where it wrote them.
Explanation shape: { version: 1, topic, question?, scope: { issue?, entry: "path:line", base?, focus? }, glossary?: [{ term, code }], diagrams: Diagram[], blocks: [{ id, title?, text (domain prose with [[ref:path:line]]), highlights: { <diagramId>: [elementId] } }] }.
Diagram is either { id, title, kind: "component" | "state" | "activity", nodes: [{ id, label, kind?, code?, ref?, parent? }], edges: [{ id, from, to, label?, code?, ref?, type?: "sync"|"async"|"dependency"|"transition"|"flow", via? }] }
or { id, title, kind: "sequence", participants: [{ id, label, kind?: "actor"|"component"|"external"|"store", component?: <component node id>, code?, ref? }], steps: Step[] }.
Step is a message { id, type: "sync"|"async"|"return"|"self"|"create", from, to, label, code? (callee), ref? (call site), via?: "call"|"url"|"signal"|"task"|"orm"|"http"|"event"|"other" }, a fragment { id, type: "fragment", operator: "alt"|"opt"|"loop"|"par"|"break"|"critical", label?, branches: [{ guard?, steps }] }, a collapsed run { id, type: "collapsed", from, to?, label, hiddenCalls, refs? } or a note { id, type: "note", over: [participantId], text }.`

const LIST_DESCRIPTION = `List the control-flow explanations saved for this repository, newest first: number, title, issue, date, question, page link and name. Use it when the user asks for an explanation made before, to find the one they mean; open it with ${OPEN_TOOL}.`

const OPEN_DESCRIPTION = `Reopen a saved control-flow explanation in the pane and rebuild its page, by the name or number ${LIST_TOOL} gave. Input: { "name": string }. It does not trace or validate anything again; to explain a flow anew, build a new explanation and call ${RENDER_TOOL}.`

const SEED_DESCRIPTION = `Static call map from the function containing an entry point, built by the language resolver (Python/Django today: direct calls, Celery tasks, signal receivers). Input: { "entry": "path:line", "depth"?: number (default 3) }. Use it as a map of what to read, not as the explanation: dynamic dispatch and framework routing can add hops it does not list, and edges marked "possible" depend on run-time values.`

// ------------------------------------------------------------------ helpers

async function repoRootOf($: EngineInterface): Promise<string> {
  const cwd = await $.session.cwd()
  try {
    const r = await $.process.run(['git', 'rev-parse', '--show-toplevel'], { cwd, timeoutMs: 5000 })
    if (r.exitCode === 0 && r.stdout.trim()) return r.stdout.trim()
  } catch {
    // not a git checkout: the working directory is the root
  }
  return cwd
}

async function readText($: EngineInterface, path: string): Promise<string | null> {
  try {
    const t = await $.fs.read(path)
    return typeof t === 'string' ? t : null
  } catch {
    return null
  }
}

async function loadConfig($: EngineInterface, options: Record<string, unknown>, root: string): Promise<Config> {
  const raw = await readText($, `${root}/${PROJECT_CONFIG}`)
  let project: unknown = null
  if (raw) {
    try {
      project = JSON.parse(raw)
    } catch {
      $.ui.toast(`explain-flow: ${PROJECT_CONFIG} is not valid JSON; using plugin settings`)
    }
  }
  return resolveConfig(options, project, root)
}

function resolverArgv($: EngineInterface, spec: ResolverSpec, config: Config, mode: string): string[] {
  return [
    ...spec.command.map(a => a.replaceAll('{python}', config.python).replaceAll('{pluginRoot}', $.plugin.root)),
    mode,
  ]
}

function pipelineIO($: EngineInterface, config: Config, root: string): PipelineIO {
  return {
    readFile: p => readText($, p.startsWith('/') ? p : `${root}/${p}`),
    runResolver: async (spec, mode, request) => {
      try {
        const r = await $.process.run(resolverArgv($, spec, config, mode), {
          cwd: root,
          stdin: JSON.stringify(request),
          timeoutMs: 120_000,
        })
        if (r.exitCode !== 0) return null
        const answer = JSON.parse(r.stdout) as ResolverAnswer
        return answer && typeof answer.results === 'object' ? answer : null
      } catch {
        return null
      }
    },
  }
}

function absPath(root: string, p: string) {
  return p.startsWith('/') ? p : `${root.replace(/\/$/, '')}/${p}`
}

async function openInBrowser($: EngineInterface, config: Config, rendered: Rendered, sel?: Selection) {
  const hash = new URLSearchParams()
  if (sel?.tab) hash.set('tab', sel.tab)
  if (sel?.block) hash.set('block', sel.block)
  const query = hash.toString()
  const url = `file://${encodeURI(rendered.htmlPath)}${query ? `#${query}` : ''}`
  const argv = [...config.browserCommand.split(/\s+/).filter(Boolean), url]
  try {
    const r = await $.process.run(argv, { timeoutMs: 15_000 })
    if (r.exitCode !== 0) $.ui.toast(`explain-flow: ${argv[0]} exited ${r.exitCode}; open ${rendered.htmlPath} yourself`)
  } catch {
    $.ui.toast(`explain-flow: could not run ${argv[0]}; open ${rendered.htmlPath} yourself`)
  }
}

const fileUrl = (path: string) => `file://${encodeURI(path)}`

type Saved = { stem: string; htmlPath: string; jsonPath: string | null; meta: PageMeta; mtimeMs: number }

/**
 * The explanations in the output folder, newest first, read from what is
 * there now: a page without its model can be opened in the browser, not in
 * the pane. Titles come from the model, or from the page's <head>.
 */
async function listSaved($: EngineInterface, dir: string): Promise<Saved[]> {
  let entries: { name: string; kind: string; mtimeMs: number }[]
  try {
    entries = await $.fs.list(dir)
  } catch {
    return []
  }
  const names = new Set(entries.map(e => e.name))
  const pages = entries.filter(e => e.kind === 'file' && e.name.endsWith('.html')).sort((a, b) => b.mtimeMs - a.mtimeMs)
  const out: Saved[] = []
  for (const page of pages) {
    const stem = page.name.replace(/\.html$/, '')
    const htmlPath = `${dir}/${page.name}`
    const jsonPath = names.has(`${stem}.json`) ? `${dir}/${stem}.json` : null
    let meta: PageMeta | null = null
    if (jsonPath) {
      try {
        const x = JSON.parse((await readText($, jsonPath)) ?? '') as Explanation
        meta = pageMeta(x, '', '')
      } catch {
        meta = null
      }
    }
    if (!meta) meta = readPageMeta((await readText($, htmlPath)) ?? '')
    out.push({ stem, htmlPath, jsonPath, mtimeMs: page.mtimeMs, meta: meta ?? { title: stem, description: '' } })
  }
  return out
}

function formatList(dir: string, saved: Saved[]): string {
  if (!saved.length) return `No saved explanations in ${dir}.`
  const lines = saved.map((s, i) => {
    const head = [`**${s.meta.title}**`, s.meta.issue, formatStamp(new Date(s.mtimeMs))].filter(Boolean).join(' · ')
    const page = `[page](${fileUrl(s.htmlPath)})${s.jsonPath ? '' : ' (page only)'}`
    return `${i + 1}. ${head}\n   ${s.meta.description ? `${s.meta.description} ` : ''}${page} · \`${s.stem}\``
  })
  return `Explanations in ${dir}, newest first:\n\n${lines.join('\n')}\n\nReopen one in the pane with /${VIEW_COMMAND} <number> or /${VIEW_COMMAND} <name>.`
}

/**
 * Reopens a saved explanation by its number in the listing or its name:
 * rebuilt into the pane when its model is there, else its page in the browser.
 */
async function openSaved(
  $: EngineInterface,
  config: Config,
  root: string,
  dir: string,
  arg: string,
): Promise<{ inPane: boolean; text: string }> {
  const saved = await listSaved($, dir)
  const pick = /^\d+$/.test(arg) ? saved[Number(arg) - 1] : saved.find(x => x.stem === arg.replace(/\.(json|html)$/, ''))
  if (!pick) return { inPane: false, text: `No explanation "${arg}" in ${dir}.\n\n${formatList(dir, saved)}` }
  const page = `[${pick.meta.title}](${fileUrl(pick.htmlPath)})`
  if (!pick.jsonPath) {
    await openExternal($, config, fileUrl(pick.htmlPath))
    return { inPane: false, text: `Its model is gone, so it opened in the browser only: ${page}` }
  }
  let x: Explanation
  try {
    x = JSON.parse((await readText($, pick.jsonPath)) ?? '') as Explanation
  } catch {
    return { inPane: false, text: `${pick.jsonPath} is not valid JSON.` }
  }
  // a saved model was validated when written; republish rebuilds its HTML with this version's viewer
  await publish($, config, root, x, pick.stem)
  return { inPane: true, text: `Opened ${page} in the pane.` }
}

async function openExternal($: EngineInterface, config: Config, url: string) {
  const argv = [...config.browserCommand.split(/\s+/).filter(Boolean), url]
  try {
    await $.process.run(argv, { timeoutMs: 15_000 })
  } catch {
    $.ui.toast(`explain-flow: could not run ${argv[0]} for ${url}`)
  }
}

async function publish(
  $: EngineInterface,
  config: Config,
  root: string,
  explanation: Explanation,
  stem?: string,
): Promise<Rendered> {
  // a reopened explanation keeps its name; a new render gets its own
  const slug = stem ?? fileStem(explanation.topic, new Date())
  const dir = absPath(root, config.outputDir)
  const jsonPath = `${dir}/${slug}.json`
  const htmlPath = `${dir}/${slug}.html`
  const [template, elk] = await Promise.all([
    $.fs.read(`${$.plugin.root}/explain-flow/viewer/template.html`) as Promise<string>,
    $.fs.read(`${$.plugin.root}/explain-flow/viewer/vendor/elk.bundled.js`) as Promise<string>,
  ])
  const html = buildHtml(template, elk, {
    explanation,
    repoRoot: root,
    editorUrl: config.editorUrl,
    generatedAt: new Date().toISOString(),
  })
  await $.fs.write(jsonPath, JSON.stringify(explanation, null, 2) + '\n')
  await $.fs.write(htmlPath, html)
  const rendered: Rendered = { slug, jsonPath, htmlPath, repoRoot: root, explanation }
  await update($, current, () => rendered)
  await update($, selection, () => ({ block: explanation.blocks[0]?.id ?? null, tab: explanation.diagrams[0]?.id ?? null }))
  return rendered
}

/** Labels of the elements a block highlights in one diagram, for the pane. */
function highlightedLabels(x: Explanation, diagramId: string, blockId: string): string[] {
  const d = x.diagrams.find(dd => dd.id === diagramId)
  const b = x.blocks.find(bb => bb.id === blockId)
  if (!d || !b) return []
  const ids = new Set(b.highlights[diagramId] ?? [])
  const out: string[] = []
  if (isSequence(d)) {
    for (const p of d.participants) if (ids.has(p.id)) out.push(p.label)
    let n = 0
    walkSteps(d.steps, s => {
      const isMsg = s.type !== 'fragment' && s.type !== 'collapsed' && s.type !== 'note'
      if (isMsg && s.type !== 'return') n++
      if (!ids.has(s.id)) return
      if (s.type === 'fragment') out.push(`[${s.operator}${s.label ? ` ${s.label}` : ''}]`)
      else if (s.type === 'collapsed') out.push(`… ${s.label}`)
      else if (s.type === 'note') out.push(`note: ${s.text}`)
      else {
        const mark = s.verification?.status === 'unverified' ? ' ?' : ''
        out.push(`${s.type === 'return' ? '←' : `${n}.`} ${s.label}${mark}`)
      }
    })
  } else {
    const nodes = new Map(d.nodes.map(nd => [nd.id, nd.label]))
    for (const nd of d.nodes) if (ids.has(nd.id)) out.push(nd.label || nd.kind || nd.id)
    for (const e of d.edges)
      if (ids.has(e.id)) out.push(`${nodes.get(e.from) || e.from} → ${nodes.get(e.to) || e.to}${e.label ? `: ${e.label}` : ''}`)
  }
  return out
}

function plainText(text: string): string {
  return text.replace(/\[\[ref:([^\]]+)\]\]/g, (_, r: string) => {
    const p = parseRef(r)
    return p ? `(${p.path.split('/').pop()}:${p.line})` : `(${r})`
  })
}

// ------------------------------------------------------------------ compact tool rows

/** The text a tool row's stored output holds, whatever shape the surface stored it in. */
export function outputText(output: unknown): string {
  if (typeof output === 'string') return output
  if (Array.isArray(output))
    return output.map(b => (b && typeof b === 'object' && 'text' in b ? String((b as { text: unknown }).text) : '')).join('\n')
  if (output && typeof output === 'object') {
    const o = output as Record<string, unknown>
    if (typeof o.result === 'string') return o.result
    if ('content' in o) return outputText(o.content)
    if (typeof o.text === 'string') return o.text
  }
  return ''
}

/** What the render call's row shows instead of the whole model. */
export function compactRenderInput(input: unknown): Record<string, unknown> {
  const x = (input as { explanation?: unknown } | null)?.explanation
  if (!x || typeof x !== 'object') return input as Record<string, unknown>
  const m = x as Partial<Explanation>
  return {
    topic: m.topic,
    ...(m.scope?.issue ? { issue: m.scope.issue } : {}),
    diagrams: (m.diagrams ?? []).map(d => d.kind).join(', '),
    blocks: (m.blocks ?? []).length,
  }
}

type ResultLine = { text: string; links: { label: string; href: string }[] }

/** One line for a successful result: the counts, and links to what was written. */
export function compactResult(short: string, text: string): ResultLine | null {
  if (short === RENDER_TOOL) {
    const refs = /References checked: (\d+)[^;]*; interactions verified: (\d+), not verifiable statically: (\d+)/.exec(text)
    const page = /^Page: \[[^\]]*\]\(([^)]+)\)/m.exec(text)?.[1]
    const model = /^Model: (.+)$/m.exec(text)?.[1]
    const warnings = /\nWarnings/i.test(text) ? ' · with warnings' : ''
    return {
      text: refs ? `${refs[1]} references checked · ${refs[2]} calls verified, ${refs[3]} not verifiable${warnings}` : 'Rendered',
      links: [
        ...(page ? [{ label: 'page', href: page }] : []),
        ...(model ? [{ label: 'model', href: fileUrl(model.trim()) }] : []),
      ],
    }
  }
  if (short === LIST_TOOL) {
    const n = (text.match(/^\d+\. /gm) ?? []).length
    return { text: n ? `${n} saved explanation${n === 1 ? '' : 's'}` : 'No saved explanations', links: [] }
  }
  if (short === SEED_TOOL) {
    try {
      const seed = JSON.parse(text) as { functions?: unknown[]; edges?: unknown[] }
      return { text: `${seed.functions?.length ?? 0} functions, ${seed.edges?.length ?? 0} calls mapped`, links: [] }
    } catch {
      return null
    }
  }
  return null
}


/** The one-line result row, or null to let the engine draw its own (errors included). */
function compactResultRow($: EngineInterface, e: RenderInput<'ToolResult'>, short: string) {
  if (e.props.isErrored) return null
  const line = compactResult(short, outputText(e.props.output))
  if (!line) return null
  const { Box, Text, Link } = $.ui.resolve(e)
  return (
    <Box flexDirection="row" gap={1}>
      <Text dimColor>{line.text}</Text>
      {line.links.map(l => (
        <Link key={l.label} href={l.href} label={l.label} />
      ))}
    </Box>
  )
}

// ------------------------------------------------------------------ register

export const register: Register = (on, options) => {
  const opts = (options ?? {}) as Record<string, unknown>

  on('session.start', async ($, e, next) => {
    const started = await next(e)
    await $.tool.register({
      name: RENDER_TOOL,
      description: RENDER_DESCRIPTION,
      inputSchema: {
        type: 'object',
        properties: { explanation: { type: 'object', description: 'The explanation model; see the tool description.' } },
        required: ['explanation'],
      },
    })
    await $.tool.register({
      name: SEED_TOOL,
      description: SEED_DESCRIPTION,
      inputSchema: {
        type: 'object',
        properties: {
          entry: { type: 'string', description: 'path:line inside the function to start from' },
          depth: { type: 'number', description: 'How many call levels to follow (default 3)' },
        },
        required: ['entry'],
      },
    })
    await $.tool.register({
      name: LIST_TOOL,
      description: LIST_DESCRIPTION,
      inputSchema: { type: 'object', properties: {} },
    })
    await $.tool.register({
      name: OPEN_TOOL,
      description: OPEN_DESCRIPTION,
      inputSchema: {
        type: 'object',
        properties: { name: { type: 'string', description: 'The name (`2026-10-15-0930-…`) or the number from list_flow_explanations' } },
        required: ['name'],
      },
    })
    await $.command.register({
      name: 'flow-view',
      description: 'Show the last control-flow explanation in a pane; "/flow-view list" lists the saved ones with titles, "/flow-view <number or name>" reopens one',
    })
    return started
  })

  // ---- the render tool
  on('tool.call', { tool: 'mcp__dcerecedo-skills__render_flow_explanation' }, async ($, e) => {
    const input = e as unknown as { explanation?: unknown }
    let x = input.explanation as Explanation | string | undefined
    if (typeof x === 'string') {
      try {
        x = JSON.parse(x) as Explanation
      } catch {
        return { deny: 'explanation must be a JSON object, not a string that fails to parse' }
      }
    }
    if (!x || typeof x !== 'object') return { deny: 'explanation is missing' }
    const root = await repoRootOf($)
    const config = await loadConfig($, opts, root)
    const result = await runPipeline(x, config, root, pipelineIO($, config, root))
    if (!result.ok) return { deny: formatIssues(result) }

    const rendered = await publish($, config, root, result.explanation)
    await $.ui.open({ id: PANE, title: 'Flow' })
    if (config.openBrowser) void openInBrowser($, config, rendered)

    const s = result.stats
    const entry = parseRef(result.explanation.scope.entry)
    const example = entry
      ? `[${entry.path.split('/').pop()}:${entry.line}](${editorLink(config.editorUrl, root, entry.path, entry.line)})`
      : ''
    const summary = [
      `Rendered "${result.explanation.topic}".`,
      `Page: [${result.explanation.topic}](${fileUrl(rendered.htmlPath)})`,
      `Model: ${rendered.jsonPath}`,
      `In your reply, link the page as above and every code reference as [file:line](${config.editorUrl}) with {abs} the absolute path, {path} the repo-relative path and {line} the line${example ? `, e.g. ${example}` : ''}.`,
      `References checked: ${s.refs} (${s.resolvers.join(', ')}); interactions verified: ${s.verified}, not verifiable statically: ${s.unverified}.`,
    ]
    const warnings = formatIssues({ warnings: result.warnings })
    return { result: summary.join('\n') + (warnings ? `\n\n${warnings}` : '') }
  }).catch(() => ({ deny: 'explain-flow could not render the explanation (an internal error; run claude --debug for details). The model was not saved.' }))

  // ---- the seed tool
  on('tool.call', { tool: 'mcp__dcerecedo-skills__trace_seed' }, async ($, e) => {
    const input = e as unknown as { entry?: string; depth?: number }
    const p = input.entry ? parseRef(input.entry) : null
    if (!p) return { deny: 'entry must be a path:line reference' }
    const root = await repoRootOf($)
    const config = await loadConfig($, opts, root)
    const spec = resolverFor(config, p.path)
    if (!spec) return { deny: `no resolver handles ${p.path}; trace it by reading the code` }
    try {
      const r = await $.process.run(resolverArgv($, spec, config, 'seed'), {
        cwd: root,
        stdin: JSON.stringify({ root, entry: `${p.path}:${p.line}`, depth: input.depth ?? 3, maxNodes: 120 }),
        timeoutMs: 120_000,
      })
      if (r.exitCode !== 0) return { deny: `resolver ${spec.name} failed: ${r.stderr.slice(0, 1500)}` }
      return { result: r.stdout }
    } catch (err) {
      return { deny: `resolver ${spec.name} could not run (${String(err)}); check the "python" setting` }
    }
  }).catch(() => ({ deny: 'trace_seed failed internally; trace the flow by reading the code instead.' }))

  // ---- saved explanations, for the model
  on('tool.call', { tool: 'mcp__dcerecedo-skills__list_flow_explanations' }, async $ => {
    const root = await repoRootOf($)
    const config = await loadConfig($, opts, root)
    const dir = absPath(root, config.outputDir)
    return { result: formatList(dir, await listSaved($, dir)) }
  }).catch(() => ({ deny: 'list_flow_explanations failed internally; ask the user to run /flow-view list.' }))

  on('tool.call', { tool: 'mcp__dcerecedo-skills__open_flow_explanation' }, async ($, e) => {
    const name = String((e as unknown as { name?: unknown }).name ?? '').trim()
    if (!name) return { deny: 'name is required: a name or number from list_flow_explanations' }
    const root = await repoRootOf($)
    const config = await loadConfig($, opts, root)
    const r = await openSaved($, config, root, absPath(root, config.outputDir), name)
    if (r.inPane) await $.ui.open({ id: PANE, title: 'Flow' })
    return { result: r.text }
  }).catch(() => ({ deny: 'open_flow_explanation failed internally; ask the user to run /flow-view with the name.' }))

  // ---- /flow-view
  on('command.run', { command: 'flow-view' }, async ($, e) => {
    const arg = String((e as unknown as { args?: string }).args ?? '').trim()
    const root = await repoRootOf($)
    const config = await loadConfig($, opts, root)
    const dir = absPath(root, config.outputDir)
    if (arg === 'list') return { text: formatList(dir, await listSaved($, dir)) }
    if (arg) {
      const r = await openSaved($, config, root, dir, arg)
      if (!r.inPane) return { text: r.text }
    }
    if (!(await read($, current))) return { text: 'Nothing rendered yet in this session. Ask for an explanation of the current flow, or /flow-view list.' }
    await $.ui.open({ id: PANE, title: 'Flow', focus: true })
    return { text: 'Flow pane opened.' }
  })

  // ---- compact transcript rows: one line per call, as the built-in tools draw;
  // the model still reads the whole result, and errors show in full
  on('ui.render', { component: 'ToolUse', props: { tool: 'mcp__dcerecedo-skills__render_flow_explanation' } }, ($, e, next) =>
    next({ ...e, props: { ...e.props, input: compactRenderInput(e.props.input) } }),
  ).catch(($, e, next) => next(e))

  on('ui.render', { component: 'ToolResult', props: { tool: 'mcp__dcerecedo-skills__render_flow_explanation' } }, ($, e, next) =>
    compactResultRow($, e, RENDER_TOOL) ?? next(e),
  ).catch(($, e, next) => next(e))
  on('ui.render', { component: 'ToolResult', props: { tool: 'mcp__dcerecedo-skills__trace_seed' } }, ($, e, next) =>
    compactResultRow($, e, SEED_TOOL) ?? next(e),
  ).catch(($, e, next) => next(e))
  on('ui.render', { component: 'ToolResult', props: { tool: 'mcp__dcerecedo-skills__list_flow_explanations' } }, ($, e, next) =>
    compactResultRow($, e, LIST_TOOL) ?? next(e),
  ).catch(($, e, next) => next(e))

  // ---- the pane
  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text, Button, Link } = $.ui.resolve(e)
    const r = await read($, current)
    if (!r) {
      return (
        <Box flexDirection="column">
          <Text dimColor>No explanation yet. Ask Claude to explain the flow you are working on.</Text>
        </Box>
      )
    }
    const x = r.explanation
    const sel = await read($, selection)
    const tab = x.diagrams.find(d => d.id === sel.tab)?.id ?? x.diagrams[0]!.id
    const blockIdx = Math.max(0, x.blocks.findIndex(b => b.id === sel.block))
    const block = x.blocks[blockIdx]!
    const config = await loadConfig($, opts, r.repoRoot)
    const labels = highlightedLabels(x, tab, block.id)
    const otherTabs = x.diagrams.filter(d => d.id !== tab && (block.highlights[d.id] ?? []).length > 0)
    const refs = inlineRefs(block.text).flatMap(ref => {
      const p = parseRef(ref)
      return p ? [{ ref, p }] : []
    })
    const go = (patch: Partial<Selection>) => () => update($, selection, s => ({ ...s, ...patch }))

    return (
      <Box flexDirection="column" gap={1}>
        <Box flexDirection="column">
          <Text bold>{x.topic}</Text>
          {x.scope.issue ? <Text dimColor>{x.scope.issue}</Text> : null}
        </Box>
        <Box flexDirection="row" gap={1} flexWrap="wrap">
          {x.diagrams.map((d, i) => (
            <Button
              key={`tab-${d.id}`}
              label={d.id === tab ? `▸ ${d.title}` : d.title}
              hotkey={i < 9 ? String(i + 1) : undefined}
              dimColor={d.id !== tab}
              onPress={go({ tab: d.id })}
            />
          ))}
        </Box>
        <Box flexDirection="column">
          {x.blocks.map((b, i) => (
            <Button
              key={`block-${b.id}`}
              plain
              label={`${b.id === block.id ? '●' : '○'} ${b.title ?? `Step ${i + 1}`}`}
              dimColor={b.id !== block.id}
              onPress={go({ block: b.id })}
            />
          ))}
        </Box>
        <Box flexDirection="column">
          <Text>{plainText(block.text)}</Text>
          {refs.length ? (
            <Box flexDirection="row" gap={2} flexWrap="wrap">
              {refs.map(({ p }) => {
                const href = editorLink(config.editorUrl, r.repoRoot, p.path, p.line)
                const label = `${p.path}:${p.line}`
                // the terminal makes any scheme a link; other surfaces only https, so they get a button
                return e.surface === 'terminal' ? (
                  <Link href={href} label={label} />
                ) : (
                  <Button key={`ref-${label}`} plain dimColor label={label} onPress={() => openExternal($, config, href)} />
                )
              })}
            </Box>
          ) : null}
        </Box>
        <Box flexDirection="column">
          <Text dimColor>
            In {x.diagrams.find(d => d.id === tab)!.title}:
            {labels.length ? '' : ' nothing'}
            {labels.length === 0 && otherTabs.length ? ` (see ${otherTabs.map(d => d.title).join(', ')})` : ''}
          </Text>
          {labels.map(l => (
            <Text color="yellow">  {l}</Text>
          ))}
        </Box>
        <Box flexDirection="row" gap={1}>
          <Button key="prev" label="Prev" hotkey="k" onPress={go({ block: x.blocks[Math.max(0, blockIdx - 1)]!.id })} />
          <Button key="next" label="Next" hotkey="j" onPress={go({ block: x.blocks[Math.min(x.blocks.length - 1, blockIdx + 1)]!.id })} />
          <Button
            key="open"
            label="Open diagrams in browser"
            hotkey="o"
            onPress={() => openInBrowser($, config, r, { block: block.id, tab })}
          />
        </Box>
      </Box>
    )
  })
}
