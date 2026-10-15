/**
 * Settings: the plugin's userConfig, overridden per repo by
 * `.claude/dcerecedo-skills.json`, whose top-level keys are shared by the
 * plugin's skills and whose `explain-flow` section is this skill's own.
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

export const PROJECT_CONFIG = '.claude/dcerecedo-skills.json'
export const SECTION = 'explain-flow'

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

const asRecord = (v: unknown): Record<string, unknown> =>
  v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : {}

/**
 * Defaults, then plugin options, then the project file's shared keys, then its
 * `explain-flow` section. A project resolver with a built-in's name replaces
 * it; `"resolvers": []` keeps the built-ins. `{repo}` in `outputDir` is the
 * repository folder's name, so one absolute folder can serve every repo.
 */
export function resolveConfig(options: Record<string, unknown>, project: unknown, repoRoot: string): Config {
  const shared = asRecord(project)
  const own = asRecord(shared[SECTION])
  const str = (key: string, option: unknown, fallback: string) =>
    pickString(own[key], pickString(shared[key], pickString(option, fallback)))
  const extra = parseResolvers(own.resolvers)
  const names = new Set(extra.map(r => r.name))
  const repo = repoRoot.replace(/\/+$/, '').split('/').pop() || 'repo'
  return {
    editorUrl: str('editorUrl', options.editorUrl, DEFAULTS.editorUrl),
    outputDir: pickString(own.outputDir, pickString(options.explainFlowOutputDir, DEFAULTS.outputDir)).replaceAll('{repo}', repo),
    openBrowser: pickBool(own.openBrowser, pickBool(options.explainFlowOpenBrowser, DEFAULTS.openBrowser)),
    browserCommand: str('browserCommand', options.browserCommand, DEFAULTS.browserCommand),
    python: str('python', options.python, DEFAULTS.python),
    resolvers: [...extra, ...BUILTIN_RESOLVERS.filter(r => !names.has(r.name))],
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
