import type { On } from 'claude-code'
import { describe, expect, test } from 'claude-code/testing'

import type { Explanation } from '../types'
import { resolveConfig } from '../hooks/config'
import { collectRefChecks, fileStem, slugify, textCheck, validateStructure } from '../hooks/model'
import { runPipeline, type PipelineIO } from '../hooks/pipeline'
import { buildHtml, readPageMeta } from '../hooks/viewer'
import { compactRenderInput, compactResult, outputText } from '../hooks/register'

const MODEL: Explanation = {
  version: 1,
  topic: 'Access code issued twice when a guest rebooks',
  scope: { issue: 'LOCK-412', entry: 'bookings/views.py:9' },
  diagrams: [
    {
      id: 'components',
      title: 'Components',
      kind: 'component',
      nodes: [
        { id: 'c.service', label: 'Rebooking service', kind: 'service', code: 'rebook', ref: 'bookings/services.py:6' },
        { id: 'c.locks', label: 'Door code service', kind: 'service', code: 'LockService', ref: 'locks/service.py:7' },
      ],
      edges: [
        { id: 'e1', from: 'c.service', to: 'c.locks', label: 'issue door code', code: 'LockService.issue_code', ref: 'bookings/services.py:11' },
      ],
    },
    {
      id: 'seq',
      title: 'Rebooking',
      kind: 'sequence',
      participants: [
        { id: 'p.service', label: 'Rebooking service', component: 'c.service' },
        { id: 'p.locks', label: 'Door code service', component: 'c.locks' },
      ],
      steps: [
        { id: 's1', type: 'sync', from: 'p.service', to: 'p.locks', label: 'issue door code', code: 'LockService.issue_code', ref: 'bookings/services.py:11' },
        { id: 's2', type: 'return', from: 'p.locks', to: 'p.service', label: 'code' },
      ],
    },
  ],
  blocks: [
    { id: 'b1', title: 'The service rebooks', text: 'The service saves the stay [[ref:bookings/services.py:10]].', highlights: { components: ['c.service'] } },
    { id: 'b2', title: 'It issues a code', text: 'Then it issues a door code [[ref:bookings/services.py:11]].', highlights: { components: ['e1', 'c.locks'], seq: ['s1'] } },
  ],
}

const FILES: Record<string, string> = {
  'bookings/views.py': 'class RebookView:\n    pass\n\n\n\n\n\n\n    def post(self):\n        pass\n',
  'bookings/services.py':
    'from locks.service import LockService\n\n\n\n\ndef rebook(booking):\n    booking.start = 1\n    booking.end = 2\n    booking.status = "rebooked"\n    booking.save()\n    LockService().issue_code(booking)\n',
  'locks/service.py': '\n\n\n\n\n\nclass LockService:\n    def issue_code(self, booking):\n        pass\n',
}

/** Text check only: the python resolver needs a process, which tests do not have. */
const textOnly: PipelineIO = {
  readFile: async p => FILES[p] ?? null,
  runResolver: async () => null,
}
const config = resolveConfig({}, null, '/repo')
const noResolvers = { ...config, resolvers: [] }

const clone = (): Explanation => JSON.parse(JSON.stringify(MODEL))

describe('validation', () => {
  test('a well-formed model passes', async () => {
    const r = await runPipeline(clone(), noResolvers, '/repo', textOnly)
    expect(r.ok).toBe(true)
  })

  test('a dangling highlight id is an error', async () => {
    const x = clone()
    x.blocks[1]!.highlights.seq = ['s1', 's9']
    const r = validateStructure(x)
    expect(r.errors.some(e => e.includes('"s9" is not an element of seq'))).toBe(true)
  })

  test('a highlight of an unknown diagram is an error', async () => {
    const x = clone()
    x.blocks[0]!.highlights.states = ['x']
    expect(validateStructure(x).errors.some(e => e.includes('unknown diagram "states"'))).toBe(true)
  })

  test('a message between unknown participants is an error', async () => {
    const x = clone()
    const seq = x.diagrams[1]!
    if (seq.kind === 'sequence') seq.steps.push({ id: 's3', type: 'sync', from: 'p.ghost', to: 'p.locks', label: 'x' })
    expect(validateStructure(x).errors.some(e => e.includes('from "p.ghost" is not a participant'))).toBe(true)
  })

  test('a missing component or sequence diagram is an error', async () => {
    const x = clone()
    x.diagrams = x.diagrams.filter(d => d.kind !== 'sequence')
    x.blocks[1]!.highlights = { components: ['e1'] }
    expect(validateStructure(x).errors).toContain('diagrams: a sequence diagram is required')
  })
})

describe('references', () => {
  test('a reference to the wrong line is rejected with where the symbol is', async () => {
    const x = clone()
    const seq = x.diagrams[1]!
    if (seq.kind === 'sequence' && seq.steps[0]!.type === 'sync') seq.steps[0]!.ref = 'bookings/services.py:3'
    const r = await runPipeline(x, noResolvers, '/repo', textOnly)
    expect(r.ok).toBe(false)
    if (!r.ok) expect(r.errors.some(e => e.includes('"issue_code" is not within 3 lines') && e.includes('line 11'))).toBe(true)
  })

  test('a reference past the end of the file is rejected', async () => {
    const x = clone()
    x.blocks[0]!.text = 'See [[ref:bookings/services.py:400]].'
    const r = await runPipeline(x, noResolvers, '/repo', textOnly)
    expect(r.ok).toBe(false)
    if (!r.ok) expect(r.errors.some(e => e.includes('line 400 is past the end'))).toBe(true)
  })

  test('a reference to a missing file is rejected', async () => {
    const x = clone()
    x.scope.entry = 'nope/views.py:1'
    const r = await runPipeline(x, noResolvers, '/repo', textOnly)
    expect(r.ok).toBe(false)
  })

  test('without a resolver, calls are marked unverified, never verified', async () => {
    const r = await runPipeline(clone(), noResolvers, '/repo', textOnly)
    expect(r.ok).toBe(true)
    if (r.ok) {
      expect(r.stats.verified).toBe(0)
      expect(r.stats.unverified).toBe(2)
      const seq = r.explanation.diagrams[1]!
      if (seq.kind === 'sequence' && seq.steps[0]!.type === 'sync') expect(seq.steps[0]!.verification?.status).toBe('unverified')
    }
  })

  test('a resolver verdict annotates the interaction', async () => {
    const io: PipelineIO = {
      readFile: textOnly.readFile,
      runResolver: async (_spec, _mode, req) => ({
        results: Object.fromEntries(
          req.checks.map(c => [c.key, c.role === 'call' ? { status: 'verified', reason: 'direct call' } : { status: 'ok' }]),
        ),
      }),
    }
    const r = await runPipeline(clone(), config, '/repo', io)
    expect(r.ok).toBe(true)
    if (r.ok) {
      expect(r.stats.verified).toBe(2)
      expect(r.stats.resolvers).toContain('python')
    }
  })

  test('a resolver that cannot run falls back to the text check with a warning', async () => {
    const r = await runPipeline(clone(), config, '/repo', textOnly)
    expect(r.ok).toBe(true)
    if (r.ok) expect(r.warnings.some(w => w.includes('resolver python did not run'))).toBe(true)
  })

  test('the text check matches whole words only', async () => {
    const { checks } = collectRefChecks(clone())
    const call = checks.find(c => c.role === 'call')!
    expect(textCheck({ ...call, code: 'issue' }, FILES['bookings/services.py']!).status).toBe('error')
  })
})

describe('reference roles', () => {
  const withGraphs = (): Explanation => {
    const x = clone()
    x.diagrams.push(
      {
        id: 'act',
        title: 'Steps',
        kind: 'activity',
        nodes: [{ id: 'a1', label: 'save the booking', code: 'rebook', ref: 'bookings/services.py:10' }],
        edges: [],
      },
      {
        id: 'st',
        title: 'Status',
        kind: 'state',
        nodes: [{ id: 'n1', label: 'rebooked' }, { id: 'n2', label: 'active' }],
        edges: [{ id: 't1', from: 'n2', to: 'n1', label: 'rebook', code: 'rebook', ref: 'bookings/services.py:9', type: 'transition' }],
      },
    )
    return x
  }

  test('nodes and edges of state and activity diagrams point inside a function, component ones at definitions and calls', () => {
    const { checks, errors } = collectRefChecks(withGraphs())
    expect(errors).toEqual([])
    const role = (where: string) => checks.find(c => c.where === where)?.role
    expect(role('act/a1')).toBe('within')
    expect(role('st/t1')).toBe('within')
    expect(role('components/c.service')).toBe('def')
    expect(checks.filter(c => c.where.startsWith('components/') && c.code && !c.where.startsWith('components/c.')).every(c => c.role === 'call')).toBe(true)
  })

  test('a code that is an expression or has a subscript is rejected with what to do instead', () => {
    const x = withGraphs()
    const act = x.diagrams.find(d => d.id === 'act') as { nodes: { code?: string }[] }
    act.nodes[0]!.code = 'results[key.pin_status]'
    const { checks, errors } = collectRefChecks(x)
    expect(errors.join('\n')).toContain('act/a1: code "results[key.pin_status]" must name a function, method or class')
    expect(checks.some(c => c.where === 'act/a1')).toBe(false)
  })

  test('the text check accepts a within ref below the function name and rejects one above it', () => {
    const file = FILES['bookings/services.py']!
    const at = (line: number) =>
      textCheck({ where: 'act/a1', ref: `bookings/services.py:${line}`, path: 'bookings/services.py', line, end: line, role: 'within', code: 'rebook' }, file)
    expect(at(10).status).toBe('ok')
    expect(at(2).status).toBe('error')
  })
})

describe('config', () => {
  test('the project section beats shared keys, which beat plugin options', () => {
    const c = resolveConfig(
      { editorUrl: 'option://{abs}', python: 'option-python', explainFlowOpenBrowser: false },
      { editorUrl: 'shared://{abs}', python: 'shared-python', 'explain-flow': { python: 'own-python' } },
      '/repo',
    )
    expect(c.editorUrl).toBe('shared://{abs}')
    expect(c.python).toBe('own-python')
    expect(c.openBrowser).toBe(false)
  })

  test('{repo} in the output folder is the repository folder name', () => {
    expect(resolveConfig({ explainFlowOutputDir: '/tmp/explain-flow/{repo}' }, null, '/home/me/shop/').outputDir).toBe('/tmp/explain-flow/shop')
    expect(resolveConfig({}, { 'explain-flow': { outputDir: 'docs/{repo}' } }, '/w/api').outputDir).toBe('docs/api')
  })

  test('resolvers are read from the skill section only and replace built-ins by name', () => {
    const ruby = { name: 'ruby', extensions: ['.rb'], command: ['ruby', 'r.rb'] }
    const python = { name: 'python', extensions: ['.py'], command: ['my-py'] }
    expect(resolveConfig({}, { resolvers: [ruby] }, '/r').resolvers.map(r => r.name)).toEqual(['python'])
    const c = resolveConfig({}, { 'explain-flow': { resolvers: [ruby, python] } }, '/r')
    expect(c.resolvers).toEqual([ruby, python])
  })
})

describe('viewer', () => {
  test('the model is inlined safely inside the page', async () => {
    const x = clone()
    x.topic = 'Breaks </script><script>alert(1)</script> $& $1'
    const html = buildHtml('<title>__TITLE__</title><script>__MODEL_JSON__</script><script>/*__ELK__*/</script>', 'var elk="</script>"', {
      explanation: x,
      repoRoot: '/repo',
      editorUrl: 'vscode://file/{abs}:{line}',
      generatedAt: '2026-10-15T00:00:00Z',
    })
    expect(html.includes('</script><script>alert')).toBe(false)
    expect(html.includes('$&amp; $1')).toBe(true)
    expect(html.includes('var elk="<\\/script>"')).toBe(true)
  })

  test('the page carries its title, description and issue in its head, readable back', async () => {
    const x = clone()
    x.question = 'Why is the "door code" sent twice & when?'
    const html = buildHtml('<head><title>__TITLE__</title>\n__META__</head><script>__MODEL_JSON__</script>', '', {
      explanation: x,
      repoRoot: '/home/me/shop',
      editorUrl: 'vscode://file/{abs}:{line}',
      generatedAt: '2026-10-15T09:30:00Z',
    })
    expect(readPageMeta(html)).toEqual({
      title: x.topic,
      description: 'Why is the "door code" sent twice & when?',
      issue: 'LOCK-412',
      repo: 'shop',
      generated: '2026-10-15T09:30:00Z',
    })
  })

  test('saved files are named by local time then topic, so a listing sorts by time', async () => {
    expect(fileStem('Código emitido / LOCK-412', new Date(2026, 9, 5, 9, 7))).toBe('2026-10-05-0907-codigo-emitido-lock-412')
  })

  test('slugs are filesystem-safe', async () => {
    expect(slugify('Código emitido dos veces / LOCK-412')).toBe('codigo-emitido-dos-veces-lock-412')
  })
})

// ------------------------------------------------------------------ the tool and the pane, end to end

const PANE = { plugin: 'dcerecedo-skills', component: 'Pane', requestId: 'explain-flow' } as const
const paneProps = { title: 'Flow', isFocused: true, bodyColumns: 80, placement: 'dock' } as never

/**
 * The engine beneath the plugin: a repo at /repo holding FILES, no git, no
 * python, and a record of what the plugin writes and opens.
 */
function fakeHost(on: On) {
  const written: Record<string, string> = {}
  const ran: string[][] = []
  on('session.cwd', async () => ({ value: '/repo' }))
  on('fs.read', async (_$, e) => {
    if (e.path.endsWith('/viewer/template.html'))
      return { value: '<head><title>__TITLE__</title>\n__META__</head><script>__MODEL_JSON__</script><script>/*__ELK__*/</script>' }
    if (e.path.endsWith('/viewer/vendor/elk.bundled.js')) return { value: 'var ELK = function () {}' }
    if (e.path in written) return { value: written[e.path]! }
    const rel = e.path.replace(/^\/repo\//, '')
    if (rel in FILES) return { value: FILES[rel]! }
    return { deny: `ENOENT: ${e.path}` }
  })
  const mtime: Record<string, number> = {}
  on('fs.write', async (_$, e) => {
    written[e.path] = e.text
    mtime[e.path] = Object.keys(mtime).length + 1
    return { value: undefined }
  })
  on('fs.list', async (_$, e) => {
    const inDir = Object.keys(written).filter(p => p.startsWith(`${e.path}/`))
    if (!inDir.length) return { deny: `ENOENT: ${e.path}` }
    return { value: inDir.map(p => ({ name: p.slice(e.path.length + 1), kind: 'file' as const, size: written[p]!.length, mtimeMs: mtime[p]! })) }
  })
  on('process.run', async (_$, e) => {
    ran.push([...e.argv])
    return { value: { exitCode: 1, stdout: '', stderr: 'not available in tests', isStdoutTruncated: false, isStderrTruncated: false } }
  })
  const opened: string[] = []
  on('ui.open', async (_$, e) => {
    opened.push(e.id)
    return { value: { isPlaced: true } }
  })
  on('ui.toast', async () => ({ value: undefined }))
  return { written, ran, opened }
}

describe('saved explanations', () => {
  test('list reads titles and descriptions from the folder, newest first, and a number reopens one', async ($, on) => {
    const host = fakeHost(on)
    const older = clone()
    older.topic = 'Older flow'
    older.question = 'What happened before?'
    await $.tool.call({ tool: 'mcp__dcerecedo-skills__render_flow_explanation', explanation: older } as never)
    await $.tool.call({ tool: 'mcp__dcerecedo-skills__render_flow_explanation', explanation: clone() } as never)

    const { text } = (await $.command.run({ command: 'flow-view', args: 'list' })) as { text: string }
    expect(text.indexOf(clone().topic)).toBeLessThan(text.indexOf('Older flow'))
    expect(text).toContain('LOCK-412')
    expect(text).toContain('What happened before?')
    expect(text).toContain('[page](file:///repo/.claude/explanations/')

    const before = Object.keys(host.written).length
    await $.command.run({ command: 'flow-view', args: '2' })
    // reopening rebuilds the same files, never a new pair
    expect(Object.keys(host.written).length).toBe(before)
  })

  test('a page whose model was deleted is listed from its head and marked page only', async ($, on) => {
    const host = fakeHost(on)
    await $.tool.call({ tool: 'mcp__dcerecedo-skills__render_flow_explanation', explanation: clone() } as never)
    for (const p of Object.keys(host.written)) if (p.endsWith('.json')) delete host.written[p]
    const { text } = (await $.command.run({ command: 'flow-view', args: 'list' })) as { text: string }
    expect(text).toContain(`**${clone().topic}**`)
    expect(text).toContain('(page only)')
  })
})

describe('saved explanations, for the model', () => {
  test('the list tool lists by number and name, and the open tool reopens one into the pane without new files', async ($, on) => {
    const host = fakeHost(on)
    const opened = host.opened
    await $.tool.call({ tool: 'mcp__dcerecedo-skills__render_flow_explanation', explanation: clone() } as never)
    const listed = JSON.stringify(await $.tool.call({ tool: 'mcp__dcerecedo-skills__list_flow_explanations' } as never))
    expect(listed).toContain('1. **Access code issued twice')
    const stem = /`(\d{4}-\d{2}-\d{2}-\d{4}-[a-z0-9-]+)`/.exec(listed)?.[1]
    expect(stem).toBeDefined()

    const before = Object.keys(host.written).length
    opened.length = 0
    const r = JSON.stringify(await $.tool.call({ tool: 'mcp__dcerecedo-skills__open_flow_explanation', name: stem } as never))
    expect(r).toContain('Opened [Access code issued twice')
    expect(opened).toEqual(['explain-flow'])
    expect(Object.keys(host.written).length).toBe(before)
  })

  test('an unknown name answers with the list to choose from', async ($, on) => {
    fakeHost(on)
    await $.tool.call({ tool: 'mcp__dcerecedo-skills__render_flow_explanation', explanation: clone() } as never)
    const r = JSON.stringify(await $.tool.call({ tool: 'mcp__dcerecedo-skills__open_flow_explanation', name: '7' } as never))
    expect(r).toContain('No explanation \\"7\\"')
    expect(r).toContain('1. **Access code issued twice')
  })
})

describe('compact tool rows', () => {
  test('the render call shows topic, issue, diagram kinds and block count instead of the model', () => {
    expect(compactRenderInput({ explanation: clone() })).toEqual({
      topic: clone().topic,
      issue: 'LOCK-412',
      diagrams: clone().diagrams.map(d => d.kind).join(', '),
      blocks: clone().blocks.length,
    })
  })

  test('a render result becomes one line with links to the page and the model', async ($, on) => {
    fakeHost(on)
    const r = (await $.tool.call({ tool: 'mcp__dcerecedo-skills__render_flow_explanation', explanation: clone() } as never)) as { text?: string }
    const line = compactResult('render_flow_explanation', outputText(r.text ?? r))
    expect(line?.text).toMatch(/^\d+ references checked · \d+ calls verified, \d+ not verifiable/)
    expect(line?.links.map(l => l.label)).toEqual(['page', 'model'])
    expect(line?.links.every(l => l.href.startsWith('file:///repo/.claude/explanations/'))).toBe(true)
  })

  test('stored outputs are read whatever shape they come in', () => {
    expect(outputText('a')).toBe('a')
    expect(outputText([{ type: 'text', text: 'a' }, { type: 'text', text: 'b' }])).toBe('a\nb')
    expect(outputText({ content: [{ type: 'text', text: 'c' }] })).toBe('c')
    expect(outputText({ result: 'd' })).toBe('d')
  })

  for (const surface of ['terminal', 'desktop'] as const)
    test(`on ${surface}, the rows are compact on success and the engine's own on error`, async ($, on) => {
      const seen: { component: string; props: Record<string, unknown> }[] = []
      // the engine's own rows, beneath the plugin
      on('ui.render', { component: 'ToolUse' }, async (e$, e) => {
        seen.push({ component: e.component, props: e.props as never })
        const { Text } = e$.ui.resolve(e)
        return <Text>engine row</Text>
      })
      on('ui.render', { component: 'ToolResult' }, async (e$, e) => {
        seen.push({ component: e.component, props: e.props as never })
        const { Text } = e$.ui.resolve(e)
        return <Text>engine result</Text>
      })
      const tool = 'mcp__dcerecedo-skills__render_flow_explanation'
      const use = await $.ui.mount({
        plugin: 'dcerecedo-skills',
        surface,
        component: 'ToolUse',
        props: { tool_use_id: 't1', tool, input: { explanation: clone() }, isRunning: false, isErrored: false, isInterrupted: false } as never,
      })
      expect(seen[0]?.props.input).toEqual(compactRenderInput({ explanation: clone() }))
      await use.unmount()

      const text = 'Rendered "x".\nPage: [x](file:///tmp/x.html)\nModel: /tmp/x.json\nReferences checked: 9 (python); interactions verified: 4, not verifiable statically: 1.'
      const ok = await $.ui.mount({ plugin: 'dcerecedo-skills', surface, component: 'ToolResult', props: { tool_use_id: 't1', tool, output: text, isErrored: false } as never })
      expect(await ok.find({ type: 'Text', text: '9 references checked · 4 calls verified, 1 not verifiable' })).toBeDefined()
      expect(seen.filter(x => x.component === 'ToolResult')).toHaveLength(0)
      await ok.unmount()

      const bad = await $.ui.mount({ plugin: 'dcerecedo-skills', surface, component: 'ToolResult', props: { tool_use_id: 't2', tool, output: 'Errors: …', isErrored: true } as never })
      expect(seen.filter(x => x.component === 'ToolResult')).toHaveLength(1)
      await bad.unmount()
    })
})

describe('render tool and pane', () => {
  test('the tool rejects a broken model with the errors to fix', async ($, on) => {
    const host = fakeHost(on)
    const x = clone()
    x.blocks[1]!.highlights.seq = ['s9']
    const r = await $.tool.call({ tool: 'mcp__dcerecedo-skills__render_flow_explanation', explanation: x } as never)
    expect(String((r as { deny?: string }).deny ?? (r as { text?: string }).text)).toContain('"s9" is not an element of seq')
    expect(Object.keys(host.written)).toEqual([])
  })

  test('the tool writes the model and the page, then the pane follows block selection on terminal and desktop', async ($, on) => {
    const host = fakeHost(on)
    const r = await $.tool.call({ tool: 'mcp__dcerecedo-skills__render_flow_explanation', explanation: clone() } as never)
    const text = JSON.stringify(r)
    expect(text).toContain('Rendered')
    const names = Object.keys(host.written).sort()
    expect(names).toHaveLength(2)
    expect(names[0]).toMatch(/^\/repo\/\.claude\/explanations\/\d{4}-\d{2}-\d{2}-\d{4}-access-code-issued-twice-when-a-guest-rebooks\.html$/)
    expect(names[1]).toBe(names[0]!.replace(/\.html$/, '.json'))
    // the reply can link the page and the code
    expect(text).toContain(`(file://${names[0]})`)
    expect(text).toContain('[views.py:9](vscode://file//repo/bookings/views.py:9)')
    // the browser was asked to open the page
    expect(host.ran.some(a => a[0] === 'xdg-open' && a[1]!.startsWith('file:///repo/.claude/explanations/'))).toBe(true)

    for (const surface of ['terminal', 'desktop'] as const) {
      const ui = await $.ui.mount({ ...PANE, surface, props: paneProps })
      // first block selected after a render
      expect(await ui.find({ type: 'Text', text: /Rebooking service/ })).toBeDefined()

      await ui.press({ key: 'block-b2' })
      expect(await ui.find({ type: 'Text', text: /Rebooking service → Door code service: issue door code/ })).toBeDefined()
      expect(await ui.find({ text: 'bookings/services.py:11' })).toBeDefined()

      await ui.press({ key: 'tab-seq' })
      expect(await ui.find({ type: 'Text', text: /1\. issue door code \?/ })).toBeDefined()

      await ui.press({ key: 'prev' })
      expect(await ui.find({ type: 'Text', text: /\(see Components\)/ })).toBeDefined()

      await ui.press({ key: 'tab-components' })
      await ui.unmount()
    }
  })
})
