import dagre from '@dagrejs/dagre'
import {
  Background,
  Controls,
  MiniMap,
  Handle,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { Download, Maximize2, Search } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { Graph, GraphNode, Level } from '../../lib/api'
import { put } from '../../lib/api'
import { LEVEL_HEX, LEVEL_ORDER, LEVEL_RU } from '../../lib/risk'
import { nodesForRisk, useSelection } from '../../lib/selection'
import { download, NODE_TITLE, svgToPng, toSvg, type Positions } from './graphExport'

interface PData extends Record<string, unknown> {
  label: string
  kind: GraphNode['kind']
  level: Level | null
  weight: number
  dim: boolean
  active: boolean
  hiddenCount: number
  resolved: boolean
  past: Level | null
  count: number
  title: string
}

const SIZE: Record<GraphNode['kind'], number> = { center: 60, topic: 44, question: 34, norm: 24, risk: 34 }
/** Радиус растёт логарифмически от числа связей: ключевые для пользователя нормы и темы заметнее, но граф не «раздувается». */
const nodeSize = (n: { kind: GraphNode['kind']; weight: number }) =>
  SIZE[n.kind] + (n.kind === 'norm' || n.kind === 'topic' ? Math.round(Math.min(16, Math.log2(Math.max(1, n.weight)) * 7)) : 0)

function PortraitNode({ data }: NodeProps<Node<PData>>) {
  const size = nodeSize({ kind: data.kind, weight: data.weight })
  const color = LEVEL_HEX[data.level ?? 'none']
  // «Эффект портрета»: цвет меняется плавно, снятый риск оставляет тонкую обводку прежнего цвета.
  const base: React.CSSProperties = {
    width: size, height: size, opacity: data.dim ? 0.3 : 1,
    borderColor: data.kind === 'center' ? '#2f2e2b' : data.level ? color : data.past ? LEVEL_HEX[data.past] : color,
    transition: 'background-color 400ms ease, border-color 400ms ease, opacity 200ms ease',
  }
  let shape: React.CSSProperties
  switch (data.kind) {
    case 'center': shape = { ...base, borderRadius: '50%', background: '#2f2e2b' }; break
    case 'topic': shape = { ...base, borderRadius: '50%', background: data.level ? color : '#e9e9e7', borderWidth: 2 }; break
    case 'question': shape = { ...base, borderRadius: 8, background: '#fff', borderWidth: 3 }; break
    case 'norm': shape = { ...base, borderRadius: 4, background: '#fff', borderWidth: 2, transform: 'rotate(45deg)' }; break
    default: shape = { ...base, borderRadius: '50%', background: data.resolved ? '#fff' : color, borderWidth: 4, borderStyle: data.resolved ? 'dashed' : 'solid' }
  }
  const short = data.label.length > 30 ? `${data.label.slice(0, 29)}…` : data.label
  return (
    <div className="flex flex-col items-center" title={data.title}>
      <Handle type="target" position={Position.Top} className="!opacity-0" />
      <div className="relative">
        <div style={{ ...shape, borderStyle: shape.borderStyle ?? 'solid', outline: data.active ? '3px solid #7a3447' : 'none', outlineOffset: 2 }} className="border" />
        {data.count > 0 && (
          <span
            className="absolute -right-1.5 -top-1.5 flex min-w-4 items-center justify-center rounded-full px-1 text-[10px] font-medium text-white"
            style={{ background: color, transition: 'background-color 400ms ease' }}
            aria-hidden
          >{data.count}</span>
        )}
      </div>
      <span className="mt-1 max-w-[120px] text-center text-[12px] leading-tight text-ink" style={{ opacity: data.dim ? 0.35 : 1 }}>
        {short}
        {data.hiddenCount > 0 && <span className="block text-muted">+{data.hiddenCount} скрыто</span>}
      </span>
      <Handle type="source" position={Position.Bottom} className="!opacity-0" />
    </div>
  )
}
const nodeTypes = { portrait: PortraitNode }

function computeLayout(nodes: GraphNode[], edges: Graph['edges'], keep: Positions): Positions {
  const g = new dagre.graphlib.Graph()
  g.setGraph({ rankdir: 'TB', nodesep: 20, ranksep: 64 })
  g.setDefaultEdgeLabel(() => ({}))
  for (const n of nodes) { const s = nodeSize(n); g.setNode(n.id, { width: s + 70, height: s + 40 }) }
  const ids = new Set(nodes.map((n) => n.id))
  for (const e of edges) {
    if (!ids.has(e.source) || !ids.has(e.target)) continue
    if (e.kind === 'belongs_to' || e.kind === 'asks_about') g.setEdge(e.target, e.source)
    else g.setEdge(e.source, e.target)
  }
  dagre.layout(g)
  const out: Positions = {}
  for (const n of nodes) {
    const k = keep[n.id]
    if (k) { out[n.id] = k; continue }
    const p = g.node(n.id)
    out[n.id] = { x: p.x - (nodeSize(n) + 70) / 2, y: p.y - (nodeSize(n) + 40) / 2 }
  }
  return out
}

export interface GraphFilters { topic: string; kinds: Record<'question' | 'norm' | 'risk', boolean>; showResolved: boolean; collapsed: string[]; minLevel: Level | ''; lastN: number }
// Риск по умолчанию — не отдельный узел, а окраска связанных узлов и бейдж с количеством (kinds.risk = false).
const defaultFilters: GraphFilters = { topic: '', kinds: { question: true, norm: true, risk: false }, showResolved: true, collapsed: [], minLevel: '', lastN: 0 }

function Inner({ sessionId, graph }: { sessionId: string; graph: Graph }) {
  const { sel, selectNode, selectMessage, openCitation, clear } = useSelection()
  const rf = useReactFlow()
  const saved = graph.filters as Partial<GraphFilters>
  const [filters, setFilters] = useState<GraphFilters>(() => {
    const base = { ...defaultFilters, ...saved, kinds: { ...defaultFilters.kinds, ...(saved.kinds ?? {}) } }
    if (saved.collapsed === undefined && graph.nodes.length > 60) { // большой граф: свернуть все темы, кроме последней
      const topics = graph.nodes.filter((n) => n.kind === 'topic').map((n) => n.id)
      base.collapsed = topics.slice(0, -1)
    }
    return base
  })
  const [query, setQuery] = useState('')
  const positions = useRef<Positions>({ ...(graph.positions as Positions) })
  const [, force] = useState(0)
  const timer = useRef<number | undefined>(undefined)

  const hidden = useMemo(() => {
    const byId = new Map(graph.nodes.map((n) => [n.id, n]))
    const collapsedQuestions = new Set<string>()
    for (const e of graph.edges) if (e.kind === 'asks_about' && filters.collapsed.includes(e.target)) collapsedQuestions.add(e.source)
    const hide = new Set<string>()
    const hiddenBy = new Map<string, number>()
    for (const n of graph.nodes) {
      const resolvedRisk = n.kind === 'risk' && n.data['status'] !== undefined && !['open', 'in_progress'].includes(String(n.data['status']))
      if ((n.kind === 'question' && (!filters.kinds.question || collapsedQuestions.has(n.id))) || (n.kind === 'norm' && !filters.kinds.norm) || (n.kind === 'risk' && (!filters.kinds.risk || (resolvedRisk && !filters.showResolved)))) hide.add(n.id)
    }
    for (const n of graph.nodes) { // нормы/риски, связанные только со скрытыми узлами
      if (n.kind !== 'norm' && n.kind !== 'risk') continue
      const nb = graph.edges.filter((e) => e.source === n.id || e.target === n.id).map((e) => (e.source === n.id ? e.target : e.source))
      if (nb.length && nb.every((x) => hide.has(x) || byId.get(x)?.kind === 'norm' || byId.get(x)?.kind === 'risk') && nb.some((x) => collapsedQuestions.has(x))) hide.add(n.id)
    }
    if (filters.minLevel) {  // показать только высокие и критические
      const min = LEVEL_ORDER.indexOf(filters.minLevel)
      for (const n of graph.nodes) {
        if (n.kind !== 'question' && n.kind !== 'norm') continue
        const lv = n.risk_level ? LEVEL_ORDER.indexOf(n.risk_level) : -1
        if (lv < min) hide.add(n.id)
      }
    }
    if (filters.lastN > 0) {  // последние N вопросов
      const qs = graph.nodes.filter((n) => n.kind === 'question')
      const keep = new Set(qs.slice(-filters.lastN).map((n) => n.id))
      for (const n of qs) if (!keep.has(n.id)) hide.add(n.id)
    }
    if (filters.topic) {
      const inTopic = new Set(graph.edges.filter((e) => e.kind === 'asks_about' && e.target === filters.topic).map((e) => e.source))
      for (const n of graph.nodes) if (n.kind === 'question' && !inTopic.has(n.id)) hide.add(n.id)
      for (const n of graph.nodes) if (n.kind === 'topic' && n.id !== filters.topic) hide.add(n.id)
    }
    for (const t of filters.collapsed) hiddenBy.set(t, graph.edges.filter((e) => e.kind === 'asks_about' && e.target === t).length)
    return { hide, hiddenBy }
  }, [graph, filters])

  const visible = useMemo(() => graph.nodes.filter((n) => !hidden.hide.has(n.id)), [graph.nodes, hidden.hide])

  const layout = useMemo(() => {
    const p = computeLayout(visible, graph.edges, positions.current)
    positions.current = { ...positions.current, ...p }
    return p
  }, [visible, graph.edges])

  const highlight = useMemo(() => (sel.riskId ? nodesForRisk(graph, sel.riskId) : sel.nodeId ? new Set([sel.nodeId]) : sel.messageId ? new Set(graph.nodes.filter((n) => n.data['message_id'] === sel.messageId).map((n) => n.id)) : new Set<string>()), [graph, sel])
  const match = useMemo(() => (query.trim() ? new Set(graph.nodes.filter((n) => n.label.toLowerCase().includes(query.trim().toLowerCase())).map((n) => n.id)) : new Set<string>()), [graph.nodes, query])
  const marked = match.size ? match : highlight

  const nodes: Node<PData>[] = useMemo(
    () => visible.map((n) => ({
      id: n.id, type: 'portrait', position: layout[n.id] ?? { x: 0, y: 0 },
      data: {
        label: n.label, kind: n.kind, level: n.risk_level ?? null, weight: n.weight,
        dim: marked.size > 0 && !marked.has(n.id), active: marked.has(n.id), hiddenCount: hidden.hiddenBy.get(n.id) ?? 0,
        resolved: n.kind === 'risk' && !n.risk_level, past: n.resolved_level ?? null, count: n.risk_count, title: NODE_TITLE(n),
      },
    })),
    [visible, layout, marked, hidden.hiddenBy],
  )
  const edges: Edge[] = useMemo(() => graph.edges.filter((e) => !hidden.hide.has(e.source) && !hidden.hide.has(e.target)).map((e) => ({ id: e.id, source: e.source, target: e.target, animated: false, style: { strokeDasharray: e.kind === 'follow_up_of' ? '5 4' : undefined, opacity: marked.size && !(marked.has(e.source) && marked.has(e.target)) ? 0.25 : 1 } })), [graph.edges, hidden.hide, marked])

  const persist = useCallback((f: GraphFilters) => {
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => { void put(`/sessions/${sessionId}/layout`, { positions: positions.current, filters: f }).catch(() => undefined) }, 600)
  }, [sessionId])
  const setF = (f: GraphFilters) => { setFilters(f); persist(f) }

  useEffect(() => { const t = window.setTimeout(() => rf.fitView({ padding: 0.15, duration: 0 }), 50); return () => window.clearTimeout(t) }, [rf, graph.nodes.length])
  useEffect(() => {
    if (match.size === 1) { const id = [...match][0]; const p = id ? positions.current[id] : undefined; if (p) void rf.setCenter(p.x + 30, p.y + 30, { zoom: 1.1, duration: 250 }) }
  }, [match, rf])

  const exportGraph = useCallback(async (fmt: 'svg' | 'png') => {
    const svg = toSvg(visible, graph.edges, positions.current as Positions, (n) => nodeSize(n), `DoorAIn — цифровой слепок, ${new Date().toLocaleDateString('ru-RU')}`)
    if (!svg) return
    const stamp = new Date().toISOString().slice(0, 10)
    if (fmt === 'svg') { download(`doorain-portrait-${stamp}.svg`, new Blob([svg], { type: 'image/svg+xml' })); return }
    const png = await svgToPng(svg)
    if (png) download(`doorain-portrait-${stamp}.png`, png)
  }, [visible, graph.edges])

  const topics = graph.nodes.filter((n) => n.kind === 'topic')
  const anySel = !!(sel.riskId || sel.nodeId || sel.messageId)
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-2 text-small">
        <label className="relative">
          <span className="sr-only">Поиск по карте</span>
          <Search className="pointer-events-none absolute left-2 top-1/2 size-4 -translate-y-1/2 text-muted" aria-hidden />
          <input className="input !min-h-8 !w-36 !pl-7" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Поиск" />
        </label>
        <label className="flex items-center gap-1"><span className="sr-only">Тема</span>
          <select className="input !min-h-8 !w-40" value={filters.topic} onChange={(e) => setF({ ...filters, topic: e.target.value })}>
            <option value="">Все темы</option>
            {topics.map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}
          </select>
        </label>
        {(['question', 'norm', 'risk'] as const).map((k) => (
          <label key={k} className="flex items-center gap-1"><input type="checkbox" checked={filters.kinds[k]} onChange={(e) => setF({ ...filters, kinds: { ...filters.kinds, [k]: e.target.checked } })} />{k === 'question' ? 'Вопросы' : k === 'norm' ? 'Нормы' : 'Риски'}</label>
        ))}
        <label className="flex items-center gap-1"><span className="sr-only">Уровень риска</span>
          <select className="input !min-h-8 !w-36" value={filters.minLevel} onChange={(e) => setF({ ...filters, minLevel: e.target.value as Level | '' })}>
            <option value="">Любой риск</option>
            <option value="high">Высокие и выше</option>
            <option value="critical">Только критические</option>
          </select>
        </label>
        <label className="flex items-center gap-1"><span className="sr-only">Интервал вопросов</span>
          <select className="input !min-h-8 !w-36" value={filters.lastN} onChange={(e) => setF({ ...filters, lastN: Number(e.target.value) })}>
            <option value={0}>Все вопросы</option>
            <option value={5}>Последние 5</option>
            <option value={10}>Последние 10</option>
          </select>
        </label>
        <label className="flex items-center gap-1"><input type="checkbox" checked={filters.showResolved} onChange={(e) => setF({ ...filters, showResolved: e.target.checked })} />Снятые</label>
        <button className="btn" onClick={() => setF({ ...filters, collapsed: filters.collapsed.length ? [] : topics.map((t) => t.id) })}>{filters.collapsed.length ? 'Развернуть темы' : 'Свернуть темы'}</button>
        <button className="btn btn-icon" aria-label="Уместить всё" onClick={() => void rf.fitView({ padding: 0.15, duration: 200 })}><Maximize2 className="size-4" aria-hidden /></button>
        <button className="btn" onClick={() => exportGraph('svg')}><Download className="size-4" aria-hidden />SVG</button>
        <button className="btn" onClick={() => void exportGraph('png')}>PNG</button>
        {anySel && <button className="btn" onClick={clear}>Снять выделение</button>}
      </div>
      <div className="relative min-h-0 flex-1">
        <ReactFlow
          nodes={nodes} edges={edges} nodeTypes={nodeTypes} minZoom={0.15} maxZoom={2} fitView proOptions={{ hideAttribution: true }} nodesConnectable={false} deleteKeyCode={null}
          onNodeClick={(_, n) => {
            selectNode(n.id)
            const gn = graph.nodes.find((x) => x.id === n.id)
            if (gn?.kind === 'question' && gn.data['message_id']) selectMessage(String(gn.data['message_id']))
            if (gn?.kind === 'norm' && gn.data['citation_id']) openCitation(String(gn.data['citation_id']))
          }}
          onNodeDoubleClick={(_, n) => { const gn = graph.nodes.find((x) => x.id === n.id); if (gn?.kind === 'topic') setF({ ...filters, collapsed: filters.collapsed.includes(n.id) ? filters.collapsed.filter((x) => x !== n.id) : [...filters.collapsed, n.id] }) }}
          onNodeDragStop={(_, n) => { positions.current = { ...positions.current, [n.id]: n.position }; force((x) => x + 1); persist(filters) }}
          onPaneClick={clear}
        >
          <Background gap={24} color="#efefed" />
          <Controls showInteractive={false} />
          <MiniMap pannable zoomable ariaLabel="Мини-карта слепка" nodeColor={(n) => LEVEL_HEX[((n.data as PData).level ?? 'none')]} maskColor="rgba(250,250,248,0.75)" style={{ width: 120, height: 84 }} />
        </ReactFlow>
        <ul className="pointer-events-none absolute bottom-2 left-2 flex max-w-[90%] flex-wrap gap-x-3 gap-y-1 rounded-md bg-canvas/90 px-2 py-1 text-[11px] text-muted" aria-label="Легенда">
          {(['low', 'medium', 'high', 'critical'] as const).map((l) => <li key={l} className="flex items-center gap-1"><span className="inline-block size-2.5 rounded-full" style={{ background: LEVEL_HEX[l] }} />{LEVEL_RU[l]}</li>)}
          <li className="flex items-center gap-1"><span className="inline-block size-2.5 rounded-full" style={{ background: LEVEL_HEX.none }} />Нет рисков или мало данных (не «безопасно»)</li>
        </ul>
      </div>
    </div>
  )
}

export function GraphView({ sessionId, graph }: { sessionId: string; graph: Graph }) {
  return <ReactFlowProvider><Inner sessionId={sessionId} graph={graph} /></ReactFlowProvider>
}
