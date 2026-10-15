/** A code location: `path:line` or `path:start-end`, path relative to the repo root. */
export type Ref = string

/** How the mod checked an interaction against the code. */
export type Verification = {
  status: 'verified' | 'unverified'
  /** Which resolver checked it: `python`, `text`, or a configured one. */
  by: string
  reason?: string
}

export type GraphNode = {
  id: string
  label: string
  /** component: service | view | model | task | module | store | external | actor; state: initial | final | state; activity: start | end | action | decision | merge | fork */
  kind?: string
  code?: string
  ref?: Ref
  /** Id of an enclosing node (a package, a Django app). */
  parent?: string
}

export type GraphEdge = {
  id: string
  from: string
  to: string
  label?: string
  code?: string
  ref?: Ref
  type?: 'sync' | 'async' | 'dependency' | 'transition' | 'flow'
  via?: Via
  verification?: Verification
}

export type GraphDiagram = {
  id: string
  title: string
  kind: 'component' | 'state' | 'activity'
  nodes: GraphNode[]
  edges: GraphEdge[]
}

export type Participant = {
  id: string
  label: string
  kind?: 'actor' | 'component' | 'external' | 'store'
  /** Id of the matching node in the component diagram. */
  component?: string
  code?: string
  ref?: Ref
}

export type Via = 'call' | 'url' | 'signal' | 'task' | 'orm' | 'http' | 'event' | 'other'

export type Message = {
  id: string
  type: 'sync' | 'async' | 'return' | 'self' | 'create'
  from: string
  to: string
  label: string
  /** The callee, e.g. `LockService.issue_code`. */
  code?: string
  /** The call site. */
  ref?: Ref
  via?: Via
  verification?: Verification
}

export type Fragment = {
  id: string
  type: 'fragment'
  operator: 'alt' | 'opt' | 'loop' | 'par' | 'break' | 'critical'
  label?: string
  branches: { guard?: string; steps: Step[] }[]
}

export type Collapsed = {
  id: string
  type: 'collapsed'
  from: string
  to?: string
  label: string
  hiddenCalls: number
  refs?: Ref[]
}

export type Note = { id: string; type: 'note'; over: string[]; text: string }

export type Step = Message | Fragment | Collapsed | Note

export type SequenceDiagram = {
  id: string
  title: string
  kind: 'sequence'
  participants: Participant[]
  steps: Step[]
}

export type Diagram = GraphDiagram | SequenceDiagram

export type Block = {
  id: string
  title?: string
  /** Prose in the domain language; code cited inline as [[ref:path:line]]. */
  text: string
  /** Element ids this block covers, per diagram id. */
  highlights: Record<string, string[]>
}

export type Explanation = {
  version: 1
  topic: string
  question?: string
  scope: { issue?: string; entry: Ref; base?: string; focus?: string }
  glossary?: { term: string; code: string }[]
  diagrams: Diagram[]
  blocks: Block[]
}

/** What the pane shows: the last rendered explanation and where it was written. */
export type Rendered = {
  slug: string
  jsonPath: string
  htmlPath: string
  repoRoot: string
  explanation: Explanation
}

export type Selection = { block: string | null; tab: string | null }

declare module 'claude-code' {
  interface PluginState {
    'dcerecedo-skills': { current: Rendered | null; selection: Selection }
  }
}
