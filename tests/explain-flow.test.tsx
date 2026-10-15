import type { On } from 'claude-code'
import { describe, expect, test } from 'claude-code/testing'

import type { Explanation } from '../types'
import { resolveConfig } from '../hooks/config'
import { collectRefChecks, slugify, textCheck, validateStructure } from '../hooks/model'
import { runPipeline, type PipelineIO } from '../hooks/pipeline'
import { buildHtml } from '../hooks/viewer'

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
const config = resolveConfig({}, { resolvers: [] })
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

  test('slugs are filesystem-safe', async () => {
    expect(slugify('Código emitido dos veces / LOCK-412')).toBe('codigo-emitido-dos-veces-lock-412')
  })
})

// ------------------------------------------------------------------ the tool and the pane, end to end

const PANE = { plugin: 'explain-flow', component: 'Pane', requestId: 'explain-flow' } as const
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
      return { value: '<title>__TITLE__</title><script>__MODEL_JSON__</script><script>/*__ELK__*/</script>' }
    if (e.path.endsWith('/viewer/vendor/elk.bundled.js')) return { value: 'var ELK = function () {}' }
    const rel = e.path.replace(/^\/repo\//, '')
    if (rel in FILES) return { value: FILES[rel]! }
    return { deny: `ENOENT: ${e.path}` }
  })
  on('fs.write', async (_$, e) => {
    written[e.path] = e.text
    return { value: undefined }
  })
  on('process.run', async (_$, e) => {
    ran.push([...e.argv])
    return { value: { exitCode: 1, stdout: '', stderr: 'not available in tests', isStdoutTruncated: false, isStderrTruncated: false } }
  })
  on('ui.open', async () => ({ value: { isPlaced: true } }))
  on('ui.toast', async () => ({ value: undefined }))
  return { written, ran }
}

describe('render tool and pane', () => {
  test('the tool rejects a broken model with the errors to fix', async ($, on) => {
    const host = fakeHost(on)
    const x = clone()
    x.blocks[1]!.highlights.seq = ['s9']
    const r = await $.tool.call({ tool: 'mcp__explain-flow__render_flow_explanation', explanation: x } as never)
    expect(String((r as { deny?: string }).deny ?? (r as { text?: string }).text)).toContain('"s9" is not an element of seq')
    expect(Object.keys(host.written)).toEqual([])
  })

  test('the tool writes the model and the page, then the pane follows block selection on terminal and desktop', async ($, on) => {
    const host = fakeHost(on)
    const r = await $.tool.call({ tool: 'mcp__explain-flow__render_flow_explanation', explanation: clone() } as never)
    const text = JSON.stringify(r)
    expect(text).toContain('Rendered')
    expect(Object.keys(host.written).sort()).toEqual([
      '/repo/.claude/explanations/access-code-issued-twice-when-a-guest-rebooks.html',
      '/repo/.claude/explanations/access-code-issued-twice-when-a-guest-rebooks.json',
    ])
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
