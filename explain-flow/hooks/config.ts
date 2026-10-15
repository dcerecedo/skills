/**
 * Settings: the plugin's userConfig, overridden per repo by
 * `.claude/explain-flow.json` (same keys, plus `resolvers`).
 */

export type ResolverSpec = {
  name: string
  /** File extensions this resolver checks, e.g. [".py"]. */
  extensions: string[]
  /**
   * Command run with the check request as JSON on stdin; it answers JSON on
   * stdout (see resolvers/PROTOCOL.md). `{python}` and `{pluginRoot}` are
   * substituted.
   */
  command: string[]
}

export type Config = {
  editorUrl: string
  outputDir: string
  openBrowser: boolean
  browserCommand: string
  python: string
  resolvers: ResolverSpec[]
}

export const PROJECT_CONFIG = '.claude/explain-flow.json'

export const BUILTIN_RESOLVERS: ResolverSpec[] = [
  {
    name: 'python',
    extensions: ['.py'],
    command: ['{python}', '-I', '{pluginRoot}/explain-flow/resolvers/python/resolve.py'],
  },
]

export const DEFAULTS: Config = {
  editorUrl: 'vscode://file/{abs}:{line}',
  outputDir: '.claude/explanations',
  openBrowser: true,
  browserCommand: 'xdg-open',
  python: 'python3',
  resolvers: BUILTIN_RESOLVERS,
}

const pickString = (v: unknown, fallback: string) =>
  typeof v === 'string' && v.trim() !== '' ? v : fallback

const pickBool = (v: unknown, fallback: boolean) => (typeof v === 'boolean' ? v : fallback)

function parseResolvers(v: unknown): ResolverSpec[] {
  if (!Array.isArray(v)) return []
  return v.flatMap(r => {
    if (!r || typeof r !== 'object') return []
    const { name, extensions, command } = r as Record<string, unknown>
    if (typeof name !== 'string') return []
    if (!Array.isArray(extensions) || !extensions.every(x => typeof x === 'string')) return []
    if (!Array.isArray(command) || !command.every(x => typeof x === 'string') || command.length === 0)
      return []
    return [{ name, extensions: extensions as string[], command: command as string[] }]
  })
}

/**
 * Plugin options first, then the project file on top. A project resolver
 * with a built-in's name replaces it; `"resolvers": []` keeps the built-ins.
 */
export function resolveConfig(options: Record<string, unknown>, project: unknown): Config {
  const base: Config = {
    editorUrl: pickString(options.editorUrl, DEFAULTS.editorUrl),
    outputDir: pickString(options.outputDir, DEFAULTS.outputDir),
    openBrowser: pickBool(options.openBrowser, DEFAULTS.openBrowser),
    browserCommand: pickString(options.browserCommand, DEFAULTS.browserCommand),
    python: pickString(options.python, DEFAULTS.python),
    resolvers: BUILTIN_RESOLVERS,
  }
  if (!project || typeof project !== 'object') return base
  const p = project as Record<string, unknown>
  const extra = parseResolvers(p.resolvers)
  const names = new Set(extra.map(r => r.name))
  return {
    editorUrl: pickString(p.editorUrl, base.editorUrl),
    outputDir: pickString(p.outputDir, base.outputDir),
    openBrowser: pickBool(p.openBrowser, base.openBrowser),
    browserCommand: pickString(p.browserCommand, base.browserCommand),
    python: pickString(p.python, base.python),
    resolvers: [...extra, ...base.resolvers.filter(r => !names.has(r.name))],
  }
}

export function resolverFor(config: Config, path: string): ResolverSpec | undefined {
  const lower = path.toLowerCase()
  return config.resolvers.find(r => r.extensions.some(ext => lower.endsWith(ext.toLowerCase())))
}

export function editorLink(template: string, repoRoot: string, path: string, line: number): string {
  const abs = path.startsWith('/') ? path : `${repoRoot.replace(/\/$/, '')}/${path}`
  return template
    .replaceAll('{abs}', encodeURI(abs))
    .replaceAll('{path}', encodeURI(path))
    .replaceAll('{line}', String(line))
}
