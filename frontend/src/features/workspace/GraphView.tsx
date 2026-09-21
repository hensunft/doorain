import {
  Background,
  Controls,
  MarkerType,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  useStore,
  type Edge,
  type Node,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { ArrowLeft, Download, Maximize2, RotateCcw, Search, SlidersHorizontal } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react'
import type { Graph, GraphNode, Level } from '../../lib/api'
import { put } from '../../lib/api'
import { useMessages, useRisks } from '../../lib/queries'
import { LEVEL_ORDER, LEVEL_RU, ROLE_RU } from '../../lib/risk'
import { nodesForRisk, riskIdsForNode, useSelection } from '../../lib/selection'
import { cssVar } from '../../lib/theme'
import { download, NODE_TITLE, svgToPng, toSvg } from './graphExport'
import { branchOf, countersText, dialogThread, lodFor, questionNumbers, radialLayout, short, topicCounters, visibleAt, type Positions } from './graphModel'
import { nodeTypes, type PData } from './GraphNodes'
import { ReasoningDrawer } from './ReasoningDrawer'

export interface GraphFilters { topic: string; kinds: Record<'question' | 'norm' | 'risk', boolean>; showResolved: boolean; minLevel: Level | ''; lastN: number }
// Риск по умолчанию — не отдельный узел, а окраска связанных узлов и ромб-счётчик (kinds.risk = false).
const defaultFilters: GraphFilters = { topic: '', kinds: { question: true, norm: true, risk: false }, showResolved: true, minLevel: '', lastN: 0 }
const KIND_ORDER: Record<GraphNode['kind'], number> = { center: 0, topic: 1, question: 2, norm: 3, risk: 4 }
// ponytail: уровни детализации включаются на больших графах; маленький слепок читается целиком при любом зуме.
const LOD_FROM_NODES = 20

interface Hover { id: string; x: number; y: number }

/** Карточка наведения (уровень 1): без запроса к серверу — только из уже загруженных данных сессии. */
function HoverCard({ graph, hover, sessionId, nums }: { graph: Graph; hover: Hover; sessionId: string; nums: Map<string, number> }) {
  const msgs = useMessages(sessionId)
  const risks = useRisks(sessionId)
  const n = graph.nodes.find((x) => x.id === hover.id)
  if (!n || n.kind === 'center') return null
  const all = risks.data ? [...risks.data.active] : []
  const linked = all.filter((r) => riskIdsForNode(graph, all, n.id).has(r.id))
  const top = [...linked].sort((a, b) => (b.score ?? 0) - (a.score ?? 0))[0]
  const norms = graph.edges.filter((e) => e.kind === 'cites' && e.source === n.id).length
  const body = n.label
  let head: string, conclusion = ''
  if (n.kind === 'question') {
    const mid = String(n.data['message_id'] ?? '')
    const rows = msgs.data ?? []
    const i = rows.findIndex((m) => m.id === mid)
    const asked = rows[i]
    const ans = i >= 0 ? rows.slice(i + 1).find((m) => m.role === 'assistant') : undefined
    const first = ans?.blocks?.find((b) => b.kind === 'claim' && b.state === 'verified')
    conclusion = first ? short(first.text, 160) : ''
    head = `Вопрос №${nums.get(n.id) ?? ''}${asked ? ` · ${new Date(asked.created_at).toLocaleString('ru-RU', { day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit' })}` : ''}`
  } else if (n.kind === 'topic') {
    head = 'Тема'
    const c = topicCounters(graph).get(n.id)
    conclusion = c ? countersText(c) : ''
  } else if (n.kind === 'norm') {
    head = 'Норма · нажмите — цитата и редакция'
  } else {
    head = 'Риск'
  }
  const levelLine = n.kind === 'question'
    ? [`${norms} ${norms === 1 ? 'норма' : norms > 1 && norms < 5 ? 'нормы' : 'норм'}`, `${linked.length} ${linked.length === 1 ? 'риск' : 'риска'}`, top?.level ? `${LEVEL_RU[top.level].toLowerCase()} (${top.score})` : ''].filter(Boolean).join(' · ')
    : n.risk_level ? `${LEVEL_RU[n.risk_level]} риск${top ? ` · ${top.score}` : ''}` : n.resolved_level ? `риск снят (был ${LEVEL_RU[n.resolved_level].toLowerCase()})` : 'рисков нет или мало данных'
  return (
    <div
      className="tooltip-card pointer-events-none absolute z-10 w-80"
      role="tooltip"
      style={{ left: hover.x + 16, top: hover.y + 12 }}
      data-level={n.risk_level ?? 'none'}
    >
      <div className="p-3">
        <p className="overline">{head}</p>
        <p className="body-l mt-1 font-semibold">{short(body, 120)}</p>
        {conclusion && <p className="body-s mt-1 text-muted">{n.kind === 'question' ? `Вывод: ${conclusion}` : conclusion}</p>}
        <p className="mono-m mt-2" style={{ color: `var(--risk-${n.risk_level === 'medium' ? 'mid' : (n.risk_level ?? 'none')})` }}>{levelLine}</p>
      </div>
    </div>
  )
}

function Legend({ questions }: { questions: number }) {
  return (
    <ul className="caption pointer-events-none absolute bottom-2 left-2 flex max-w-[92%] flex-wrap items-center gap-x-4 gap-y-1 rounded-md bg-canvas/90 px-3 py-1.5" aria-label="Легенда">
      <li className="flex items-center gap-1.5"><span className="inline-block h-3 w-6 rounded-full bg-brand" />тема</li>
      <li className="flex items-center gap-1.5"><span className="inline-block h-3 w-5 rounded border-2 border-risk-high bg-alt" />вопрос</li>
      <li className="flex items-center gap-1.5"><svg width="16" height="14" viewBox="0 0 46 40" aria-hidden><polygon points="12,2 34,2 44,20 34,38 12,38 2,20" fill="none" stroke="var(--gold)" strokeWidth="4" /></svg>норма</li>
      <li className="flex items-center gap-1.5"><span className="inline-block size-2.5 rotate-45 rounded-[2px] bg-risk-high" />риск</li>
      {questions > 1 && <li className="flex items-center gap-1.5"><svg width="24" height="4" aria-hidden><line x1="0" y1="2" x2="24" y2="2" stroke="var(--gold)" strokeWidth="2" strokeDasharray="5 3" /></svg>нить диалога 1 → {questions}</li>}
      <li className="flex items-center gap-1.5"><svg width="24" height="4" aria-hidden><line x1="0" y1="2" x2="24" y2="2" stroke="var(--line-strong)" strokeWidth="2" strokeDasharray="1 3" /></svg>основание ответа</li>
      {LEVEL_ORDER.map((l) => <li key={l} className="flex items-center gap-1"><span className="inline-block size-2 rounded-full" style={{ background: `var(--risk-${l === 'medium' ? 'mid' : l})` }} />{LEVEL_RU[l].toLowerCase()}</li>)}
    </ul>
  )
}

function Inner({ sessionId, graph }: { sessionId: string; graph: Graph }) {
  const { sel, selectNode, openCitation, clear, hoverRisks, setHoverRisks } = useSelection()
  const rf = useReactFlow()
  const zoom = useStore((s) => s.transform[2])
  const saved = graph.filters as Partial<GraphFilters>
  const [filters, setFilters] = useState<GraphFilters>(() => ({ ...defaultFilters, ...saved, kinds: { ...defaultFilters.kinds, ...(saved.kinds ?? {}) } }))
  const [query, setQuery] = useState('')
  const [hover, setHover] = useState<Hover | null>(null)
  const [drawer, setDrawer] = useState<string | null>(null)
  const positions = useRef<Positions>({ ...(graph.positions as Positions) })
  const [, force] = useState(0)
  const timer = useRef<number | undefined>(undefined)
  const box = useRef<HTMLDivElement>(null)
  const nums = useMemo(() => questionNumbers(graph), [graph])
  const counters = useMemo(() => topicCounters(graph), [graph])

  const hidden = useMemo(() => {
    const hide = new Set<string>()
    for (const n of graph.nodes) {
      const resolvedRisk = n.kind === 'risk' && n.data['status'] !== undefined && !['open', 'in_progress'].includes(String(n.data['status']))
      if ((n.kind === 'question' && !filters.kinds.question) || (n.kind === 'norm' && !filters.kinds.norm) || (n.kind === 'risk' && (!filters.kinds.risk || (resolvedRisk && !filters.showResolved)))) hide.add(n.id)
    }
    if (filters.minLevel) { // только высокие и критические
      const min = LEVEL_ORDER.indexOf(filters.minLevel)
      for (const n of graph.nodes) {
        if (n.kind !== 'question' && n.kind !== 'norm') continue
        if ((n.risk_level ? LEVEL_ORDER.indexOf(n.risk_level) : -1) < min) hide.add(n.id)
      }
    }
    if (filters.lastN > 0) { // последние N вопросов
      const keep = new Set([...nums.entries()].sort((a, b) => b[1] - a[1]).slice(0, filters.lastN).map(([id]) => id))
      for (const id of nums.keys()) if (!keep.has(id)) hide.add(id)
    }
    if (filters.topic) { // подграф темы (двойной клик по теме)
      const inTopic = new Set(graph.edges.filter((e) => e.kind === 'asks_about' && e.target === filters.topic).map((e) => e.source))
      for (const n of graph.nodes) if ((n.kind === 'question' && !inTopic.has(n.id)) || (n.kind === 'topic' && n.id !== filters.topic)) hide.add(n.id)
    }
    // нормы и риски, связанные только со скрытыми вопросами, не висят в воздухе
    for (const n of graph.nodes) {
      if (n.kind !== 'norm' && n.kind !== 'risk') continue
      const src = graph.edges.filter((e) => (e.kind === 'cites' || e.kind === 'evidences') && e.target === n.id).map((e) => e.source)
      if (src.length && src.every((q) => hide.has(q))) hide.add(n.id)
    }
    return hide
  }, [graph, filters, nums])

  const visible = useMemo(() => graph.nodes.filter((n) => !hidden.has(n.id)).sort((a, b) => KIND_ORDER[a.kind] - KIND_ORDER[b.kind] || (nums.get(a.id) ?? 0) - (nums.get(b.id) ?? 0)), [graph.nodes, hidden, nums])
  const layout = useMemo(() => radialLayout(graph, visible, positions.current), [graph, visible])

  const persist = useCallback((f: GraphFilters) => {
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => { void put(`/sessions/${sessionId}/layout`, { positions: positions.current, filters: f }).catch(() => undefined) }, 600)
  }, [sessionId])
  const setF = (f: GraphFilters) => { setFilters(f); persist(f) }

  // Новые узлы получают позицию один раз и сохраняются: следующий ответ не перетряхивает слепок.
  useEffect(() => {
    const fresh = Object.keys(layout).filter((id) => !positions.current[id])
    if (!fresh.length) return
    positions.current = { ...positions.current, ...layout }
    persist(filters)
  }, [layout, filters, persist])

  const lod = visible.length > LOD_FROM_NODES ? lodFor(zoom) : 'full'
  const branch = useMemo(() => (hover ? branchOf(graph, hover.id) : null), [graph, hover])
  const highlight = useMemo(() => (sel.riskId ? nodesForRisk(graph, sel.riskId) : sel.nodeId ? branchOf(graph, sel.nodeId) : sel.messageId ? new Set(graph.nodes.filter((n) => n.data['message_id'] === sel.messageId).map((n) => n.id)) : new Set<string>()), [graph, sel])
  const match = useMemo(() => (query.trim() ? new Set(graph.nodes.filter((n) => n.label.toLowerCase().includes(query.trim().toLowerCase())).map((n) => n.id)) : new Set<string>()), [graph.nodes, query])
  // наведение на риск в матрице или списке подсвечивает его узлы; остальное приглушается
  const riskHover = useMemo(() => (hoverRisks?.length ? new Set(hoverRisks.flatMap((id) => [...nodesForRisk(graph, id)])) : null), [graph, hoverRisks])
  const marked = branch ?? riskHover ?? (match.size ? match : highlight)
  const role = String(graph.nodes.find((n) => n.kind === 'center')?.data['role'] ?? '')

  const nodes: Node<PData>[] = useMemo(
    () => visible.map((n) => ({
      id: n.id,
      type: n.kind,
      position: layout[n.id] ?? { x: 0, y: 0 },
      hidden: !visibleAt(n.kind, lod),
      ariaLabel: NODE_TITLE(n),
      data: {
        kind: n.kind, label: n.label, level: n.risk_level ?? null, past: n.resolved_level ?? null, count: n.risk_count, weight: n.weight,
        num: nums.get(n.id), counters: n.kind === 'topic' ? countersText(counters.get(n.id) ?? { questions: 0, norms: 0, risks: 0 }) : undefined,
        role: ROLE_RU[role as keyof typeof ROLE_RU] ?? role, dim: marked.size > 0 && !marked.has(n.id), active: !branch && marked.has(n.id), title: NODE_TITLE(n),
      },
    })),
    [visible, layout, lod, nums, counters, role, marked, branch],
  )

  const edges: Edge[] = useMemo(() => {
    const ids = new Set(visible.map((n) => n.id))
    const col = { gold: cssVar('--gold'), line: cssVar('--line-strong'), high: cssVar('--risk-high') }
    const dimmed = (a: string, b: string) => marked.size > 0 && !(marked.has(a) && marked.has(b))
    const base: Edge[] = graph.edges.filter((e) => ids.has(e.source) && ids.has(e.target)).map((e) => {
      const kind = e.kind === 'follow_up_of' ? 'refines' : e.kind === 'cites' ? 'grounded_in' : e.kind === 'evidences' || e.kind === 'grounded_in' ? 'raises' : e.kind
      const style = kind === 'refines' ? { stroke: col.line, strokeDasharray: '4 4', strokeWidth: 1.2 }
        : kind === 'grounded_in' ? { stroke: col.line, strokeDasharray: '1 3', strokeWidth: 1.2 }
          : kind === 'raises' ? { stroke: col.high, strokeWidth: 1.2 }
            : { stroke: col.line, strokeWidth: kind === 'belongs_to' ? 1.4 : 1 }
      return { id: e.id, source: e.source, target: e.target, type: 'straight', data: { kind }, markerEnd: kind === 'refines' ? { type: MarkerType.ArrowClosed, color: col.line, width: 14, height: 14 } : undefined, style: { ...style, opacity: dimmed(e.source, e.target) ? 0.25 : 1, transition: 'opacity var(--t-fast)' } }
    })
    const thread: Edge[] = dialogThread(graph).filter((e) => ids.has(e.source) && ids.has(e.target)).map((e) => ({
      id: e.id, source: e.source, target: e.target, type: 'straight', data: { kind: 'asked_next' },
      markerEnd: { type: MarkerType.ArrowClosed, color: col.gold, width: 14, height: 14 },
      style: { stroke: col.gold, strokeDasharray: '6 4', strokeWidth: 1.6, opacity: dimmed(e.source, e.target) ? 0.25 : 1 },
    }))
    return [...base, ...thread]
  }, [graph, visible, marked])

  useEffect(() => { const t = window.setTimeout(() => rf.fitView({ padding: 0.15, duration: 0 }), 50); return () => window.clearTimeout(t) }, [rf, graph.nodes.length])
  useEffect(() => {
    if (match.size !== 1) return
    const id = [...match][0]
    const p = id ? positions.current[id] ?? layout[id] : undefined
    if (p) void rf.setCenter(p.x + 60, p.y + 20, { zoom: 1.1, duration: 500 })
  }, [match, rf, layout])
  // выбор риска в таблице — камера перелетает к его узлам-источникам (500 мс)
  useEffect(() => {
    if (!sel.riskId) return
    const ids = [...nodesForRisk(graph, sel.riskId)].filter((id) => layout[id])
    if (ids.length) void rf.fitView({ nodes: ids.map((id) => ({ id })), padding: 0.4, duration: 500, maxZoom: 1.3 })
  }, [sel.riskId, graph, layout, rf])

  const activate = useCallback((id: string) => {
    const n = graph.nodes.find((x) => x.id === id)
    if (!n) return
    selectNode(n.id)
    if (n.kind === 'question') setDrawer(n.id)
    if (n.kind === 'norm' && n.data['citation_id']) openCitation(String(n.data['citation_id']))
  }, [graph.nodes, selectNode, openCitation])

  // Enter на узле с фокуса клавиатуры — то же, что клик (Tab идёт по порядку номеров вопросов)
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== 'Enter' && e.key !== ' ') return
    const id = (e.target as HTMLElement).closest('.react-flow__node')?.getAttribute('data-id')
    if (id) { e.preventDefault(); activate(id) }
  }

  const exportGraph = useCallback(async (fmt: 'svg' | 'png') => {
    const all = [...graph.edges, ...dialogThread(graph)]
    const svg = toSvg(visible, all, { ...layout, ...positions.current }, `DoorAIn — цифровой слепок, ${new Date().toLocaleDateString('ru-RU')}`)
    if (!svg) return
    const stamp = new Date().toISOString().slice(0, 10)
    if (fmt === 'svg') { download(`doorain-portrait-${stamp}.svg`, new Blob([svg], { type: 'image/svg+xml' })); return }
    const png = await svgToPng(svg)
    if (png) download(`doorain-portrait-${stamp}.png`, png)
  }, [graph, visible, layout])

  const relayout = () => { positions.current = {}; force((x) => x + 1); persist(filters) }
  const topics = graph.nodes.filter((n) => n.kind === 'topic')
  const topicTitle = topics.find((t) => t.id === filters.topic)?.label
  const onlyHigh = filters.minLevel === 'high'
  const minimapColor = (n: Node) => cssVar(`--risk-${(n.data as PData).level === 'medium' ? 'mid' : ((n.data as PData).level ?? 'none')}`)

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex flex-wrap items-center gap-2 px-3 py-2">
        {filters.topic && <button className="btn" onClick={() => setF({ ...filters, topic: '' })}><ArrowLeft className="size-4" aria-hidden />Все темы<span className="sr-only">: выйти из подграфа «{topicTitle}»</span></button>}
        {filters.topic && <span className="caption">подграф: {topicTitle}</span>}
        <button className="btn" aria-pressed={onlyHigh} onClick={() => setF({ ...filters, minLevel: onlyHigh ? '' : 'high' })}>Только высокие риски</button>
        <button className="btn" onClick={() => void rf.fitView({ padding: 0.15, duration: 500 })}><Maximize2 className="size-4" aria-hidden />Вписать в экран</button>
        <details className="relative">
          <summary className="btn list-none"><SlidersHorizontal className="size-4" aria-hidden />Фильтры</summary>
          <div className="zone absolute right-0 z-20 mt-1 w-72 space-y-3 !p-3 shadow-[var(--shadow-hover)]">
            <label className="relative block">
              <span className="sr-only">Поиск по карте</span>
              <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted" aria-hidden />
              <input className="input !pl-9" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Поиск по карте" />
            </label>
            <label className="block"><span className="label">Тема</span>
              <select className="input" value={filters.topic} onChange={(e) => setF({ ...filters, topic: e.target.value })}>
                <option value="">Все темы</option>
                {topics.map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}
              </select>
            </label>
            <label className="block"><span className="label">Уровень риска</span>
              <select className="input" aria-label="Уровень риска" value={filters.minLevel} onChange={(e) => setF({ ...filters, minLevel: e.target.value as Level | '' })}>
                <option value="">Любой риск</option>
                <option value="high">Высокие и выше</option>
                <option value="critical">Только критические</option>
              </select>
            </label>
            <label className="block"><span className="label">Интервал вопросов</span>
              <select className="input" aria-label="Интервал вопросов" value={filters.lastN} onChange={(e) => setF({ ...filters, lastN: Number(e.target.value) })}>
                <option value={0}>Все вопросы</option>
                <option value={5}>Последние 5</option>
                <option value={10}>Последние 10</option>
              </select>
            </label>
            <fieldset className="body-s flex flex-wrap gap-x-4 gap-y-1">
              <legend className="label">Показывать</legend>
              {(['question', 'norm', 'risk'] as const).map((k) => (
                <label key={k} className="flex items-center gap-1.5"><input type="checkbox" checked={filters.kinds[k]} onChange={(e) => setF({ ...filters, kinds: { ...filters.kinds, [k]: e.target.checked } })} />{k === 'question' ? 'Вопросы' : k === 'norm' ? 'Нормы' : 'Риски'}</label>
              ))}
              <label className="flex items-center gap-1.5"><input type="checkbox" checked={filters.showResolved} onChange={(e) => setF({ ...filters, showResolved: e.target.checked })} />Снятые</label>
            </fieldset>
            <div className="flex flex-wrap gap-2 border-t border-line-soft pt-3">
              <button className="btn" onClick={() => void exportGraph('svg')}><Download className="size-4" aria-hidden />SVG</button>
              <button className="btn" onClick={() => void exportGraph('png')}>PNG</button>
              <button className="btn btn-quiet" onClick={relayout}><RotateCcw className="size-4" aria-hidden />Разложить заново</button>
            </div>
          </div>
        </details>
        {(sel.riskId || sel.nodeId || sel.messageId) && <button className="btn btn-quiet" onClick={clear}>Снять выделение</button>}
      </div>
      <div ref={box} className="relative min-h-0 flex-1 bg-panel" onKeyDown={onKey}>
        <ReactFlow
          nodes={nodes} edges={edges} nodeTypes={nodeTypes} minZoom={0.15} maxZoom={2} fitView proOptions={{ hideAttribution: true }}
          nodesConnectable={false} deleteKeyCode={null} aria-label="Карта тем: цифровой слепок сессии"
          onNodeClick={(_, n) => activate(n.id)}
          onNodeDoubleClick={(_, n) => { if (graph.nodes.find((x) => x.id === n.id)?.kind === 'topic') setF({ ...filters, topic: n.id }) }}
          onNodeMouseEnter={(ev, n) => {
            const r = box.current?.getBoundingClientRect()
            if (r) setHover({ id: n.id, x: ev.clientX - r.left, y: ev.clientY - r.top })
            const rid = graph.nodes.find((x) => x.id === n.id && x.kind === 'risk')?.data['risk_id']
            if (rid) setHoverRisks([String(rid)])
          }}
          onNodeMouseLeave={() => { setHover(null); setHoverRisks(null) }}
          onNodeDragStop={(_, n) => { positions.current = { ...positions.current, [n.id]: n.position }; force((x) => x + 1); persist(filters) }}
          onPaneClick={() => { clear(); setHover(null) }}
        >
          <Background gap={22} size={1.2} color={cssVar('--line')} />
          <Controls showInteractive={false} />
          <MiniMap pannable zoomable ariaLabel="Мини-карта слепка" nodeColor={minimapColor} maskColor="transparent" style={{ width: 120, height: 84 }} />
        </ReactFlow>
        {hover && <HoverCard graph={graph} hover={hover} sessionId={sessionId} nums={nums} />}
        <Legend questions={nums.size} />
      </div>
      <ReasoningDrawer sessionId={sessionId} nodeId={drawer} onClose={() => setDrawer(null)} />
    </div>
  )
}

export function GraphView({ sessionId, graph }: { sessionId: string; graph: Graph }) {
  return <ReactFlowProvider><Inner sessionId={sessionId} graph={graph} /></ReactFlowProvider>
}
