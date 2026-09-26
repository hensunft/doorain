import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  useStore,
  type Edge,
  type Node,
  type NodeChange,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { ArrowLeft, Download, Maximize2, RotateCcw, Search, SlidersHorizontal } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react'
import { HelpPopover } from '../../components/ui'
import type { Graph, GraphNode, Level } from '../../lib/api'
import { put } from '../../lib/api'
import { todayISO } from '../../lib/date'
import { useMessages, useRisks } from '../../lib/queries'
import { LEVEL_ORDER, LEVEL_RU, levelVar, ROLE_RU } from '../../lib/risk'
import { nodesForRisk, riskIdsForNode, useSelection } from '../../lib/selection'
import { cssVar } from '../../lib/theme'
import { download, NODE_TITLE, svgToPng, toSvg } from './graphExport'
import { BOX, branchOf, countersText, dialogThread, growth, lodFor, questionNumbers, radialLayout, separate, short, topicCounters, visibleAt, type Positions, type SizeOf } from './graphModel'
import { edgeTypes, nodeTypes, type EData, type PData } from './GraphNodes'
import { ReasoningDrawer } from './ReasoningDrawer'

export interface GraphFilters { topic: string; kinds: Record<'question' | 'norm' | 'risk', boolean>; showResolved: boolean; minLevel: Level | ''; lastN: number }
// Риск по умолчанию — не отдельный узел, а окраска связанных узлов и ромб-счётчик (kinds.risk = false).
const defaultFilters: GraphFilters = { topic: '', kinds: { question: true, norm: true, risk: false }, showResolved: true, minLevel: '', lastN: 0 }
const KIND_ORDER: Record<GraphNode['kind'], number> = { center: 0, topic: 1, question: 2, norm: 3, risk: 4 }
// ponytail: уровни детализации включаются на больших графах; маленький слепок читается целиком при любом зуме.
const LOD_FROM_NODES = 20
// Снятие наведения откладывается: при переходе через зазор между соседними узлами карта не «моргает» затемнением.
const HOVER_OUT_MS = 80

interface Hover { id: string; x: number; y: number }
interface HotEdge { id: string; source: string; target: string }

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
        <p className="mono-m mt-2 text-[var(--level-ink)]">{levelLine}</p>
      </div>
    </div>
  )
}

function Legend({ questions }: { questions: number }) {
  return (
    <ul className="caption space-y-1.5" aria-label="Легенда">
      <li className="flex items-center gap-1.5"><span className="inline-block h-3 w-6 rounded-full border border-line-strong bg-[var(--risk-none-tint)]" />тема</li>
      <li className="flex items-center gap-1.5"><span className="inline-block h-3 w-5 rounded border border-line-strong bg-alt" />вопрос</li>
      <li className="flex items-center gap-1.5"><svg width="16" height="14" viewBox="0 0 46 40" aria-hidden><polygon points="12,2 34,2 44,20 34,38 12,38 2,20" fill="none" stroke="var(--gold)" strokeWidth="4" /></svg>норма</li>
      <li className="flex items-center gap-1.5"><span className="inline-block size-2.5 rotate-45 rounded-[2px] bg-risk-high" />риск</li>
      <li className="flex items-center gap-1.5"><svg width="24" height="6" aria-hidden><line x1="0" y1="3" x2="18" y2="3" stroke="var(--muted)" strokeWidth="1.6" /><path d="M24 3 L17 0 L17 6 Z" fill="var(--muted)" /></svg>стрелка — от «Вы» наружу: тема → вопрос → норма</li>
      <li className="flex items-center gap-1.5"><svg width="24" height="4" aria-hidden><line x1="0" y1="2" x2="24" y2="2" stroke="var(--gold)" strokeWidth="1.5" /></svg>основание ответа (норма); на большой карте — у узла под курсором</li>
      <li className="flex items-center gap-1.5"><svg width="24" height="4" aria-hidden><line x1="0" y1="2" x2="24" y2="2" stroke="var(--ink-2)" strokeWidth="2" strokeDasharray="5 4" /></svg>уточняющий вопрос</li>
      {questions > 1 && <li className="flex items-center gap-1.5"><svg width="24" height="4" aria-hidden><line x1="0" y1="2" x2="24" y2="2" stroke="var(--gold)" strokeWidth="2" strokeDasharray="6 4" /></svg>нить диалога 1 → {questions} — у вопроса под курсором</li>}
      <li>наведите на узел — выделятся его связи; на линию — подпись «что → куда»</li>
      <li className="flex flex-wrap items-center gap-x-3 gap-y-1">цвет — наивысший уровень открытых рисков:{LEVEL_ORDER.map((l) => <span key={l} className="flex items-center gap-1" data-level={l}><span className="mx-swatch" aria-hidden />{LEVEL_RU[l].toLowerCase()}</span>)}</li>
      <li>серый — рисков нет или данных мало; бледный узел с обводкой — риск закрыт</li>
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
  const [hotEdge, setHotEdge] = useState<HotEdge | null>(null)
  const [drawer, setDrawer] = useState<string | null>(null)
  const positions = useRef<Positions>({ ...(graph.positions as Positions) })
  const [moved, force] = useState(0)
  // Замеры узлов: React Flow сбрасывает размеры у каждого нового объекта узла без measured и прячет его (visibility: hidden)
  // до повторного замера — курсор «проваливается» на фон, приходит mouseleave, и карта мерцает при неподвижном курсоре.
  const sizes = useRef(new Map<string, { width: number; height: number }>())
  const pinned = useRef(new Set<string>()) // последние перетащенные узлы: раздвижка их не сдвигает
  const hoverId = useRef<string | null>(null)
  const hoverOut = useRef<number | undefined>(undefined)
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
  // Узлы не залезают друг на друга: после раскладки все видимые узлы раздвигаются по замеренным размерам (капсула темы —
  // с учётом масштаба), включая сохранённые позиции; не двигается только то, что пользователь только что перетащил.
  const layout = useMemo(() => {
    const size: SizeOf = (n) => {
      const m = sizes.current.get(n.id), k = n.kind === 'topic' ? growth(n.weight) : 1
      return m ? { w: m.width, h: m.height, k } : { ...BOX[n.kind], k }
    }
    const out = radialLayout(graph, visible, positions.current, size)
    separate(visible, out, pinned.current, size)
    return out
  }, [graph, visible, moved]) // eslint-disable-line react-hooks/exhaustive-deps -- позиции и размеры лежат в ref: moved пересчитывает раскладку после замера, перетаскивания и «Разложить заново»

  const persist = useCallback((f: GraphFilters) => {
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => { void put(`/sessions/${sessionId}/layout`, { positions: positions.current, filters: f }).catch(() => undefined) }, 600)
  }, [sessionId])
  const setF = (f: GraphFilters) => { setFilters(f); persist(f) }

  // Новые узлы получают позицию один раз и сохраняются (следующий ответ не перетряхивает слепок); раздвинутые — тоже.
  useEffect(() => {
    const fresh = Object.entries(layout).filter(([id, p]) => positions.current[id]?.x !== p.x || positions.current[id]?.y !== p.y)
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
  const marked = useMemo(() => (hotEdge ? new Set([hotEdge.source, hotEdge.target]) : null), [hotEdge]) ?? branch ?? riskHover ?? (match.size ? match : highlight)
  const role = String(graph.nodes.find((n) => n.kind === 'center')?.data['role'] ?? '')

  const nodes: Node<PData>[] = useMemo(
    () => visible.map((n) => ({
      id: n.id,
      type: n.kind,
      position: layout[n.id] ?? { x: 0, y: 0 },
      measured: sizes.current.get(n.id),
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

  // Связи по типу: цвет, толщина, пунктир и стрелка «от "Вы" наружу» (тема → вопрос → норма → риск). Выделенные (ветка
  // узла под курсором, выбранный риск, связь под курсором) — толще и непрозрачны, остальные приглушаются до 12 %.
  // Нить диалога видна только у вопроса под курсором или выбранного: через всю карту она перечёркивала остальные связи.
  // Основания ответа (вопрос → норма) в покое приглушены, а на большой карте видны только у узла в фокусе:
  // при десятке норм на ответ они иначе сливаются в сетку через весь слепок.
  const edges: Edge<EData>[] = useMemo(() => {
    const ids = new Set(visible.map((n) => n.id))
    const byId = new Map(graph.nodes.map((n) => [n.id, n]))
    const name = (id: string) => { const n = byId.get(id); return n?.kind === 'question' ? `вопрос №${nums.get(id) ?? ''}` : `«${short(n?.label ?? '', 36)}»` }
    const focus = hover?.id ?? sel.nodeId
    const dense = visible.length > LOD_FROM_NODES
    const out: Edge<EData>[] = []
    const add = (id: string, source: string, target: string, stroke: string, width: number, dash: string | undefined, arrow: boolean, label: string, always = false, rest = 0.75) => {
      const hot = hotEdge?.id === id
      const lit = hot || always || (marked.size > 0 && marked.has(source) && marked.has(target))
      const quiet = !lit && (hotEdge !== null || marked.size > 0)
      if (!lit && rest === 0) return // на большой карте связь видна только у узла в фокусе
      out.push({
        id, source, target, type: 'float', zIndex: lit ? 1 : 0, data: { arrow, label, hot },
        style: { stroke, strokeWidth: lit ? width + 0.9 : width, strokeDasharray: dash, opacity: quiet ? 0.12 : lit ? 1 : rest, transition: 'opacity var(--t-fast), stroke-width var(--t-fast)' },
      })
    }
    for (const e of graph.edges) {
      if (!ids.has(e.source) || !ids.has(e.target)) continue
      const risk = (id: string) => levelVar(byId.get(id)?.risk_level ?? 'high')
      if (e.kind === 'belongs_to') add(e.id, e.target, e.source, 'var(--line-strong)', 1.6, undefined, false, `Тема портрета: ${name(e.source)}`)
      else if (e.kind === 'asks_about') add(e.id, e.target, e.source, 'var(--muted)', 1.1, undefined, true, `Тема ${name(e.target)} → ${name(e.source)}`)
      // основания ответа — самые многочисленные связи: в покое тонкие и полупрозрачные, проявляются у узла под курсором
      else if (e.kind === 'cites') add(e.id, e.source, e.target, 'var(--gold)', 0.9, undefined, true, `${name(e.source)} опирается на норму ${name(e.target)}`, false, dense ? 0 : 0.3)
      else if (e.kind === 'evidences') add(e.id, e.source, e.target, risk(e.target), 1.3, undefined, true, `${name(e.source)} → риск ${name(e.target)}`)
      else if (e.kind === 'grounded_in') add(e.id, e.target, e.source, risk(e.source), 1.3, undefined, true, `Норма ${name(e.target)} — основание риска ${name(e.source)}`)
      else if (e.kind === 'follow_up_of') add(e.id, e.source, e.target, 'var(--ink-2)', 1.1, '5 4', true, `${name(e.source)} уточняет ${name(e.target)}`)
    }
    for (const e of dialogThread(graph)) {
      if (ids.has(e.source) && ids.has(e.target) && (focus === e.source || focus === e.target)) add(e.id, e.source, e.target, 'var(--gold)', 1.4, '6 4', true, `Следующий вопрос: ${name(e.source)} → ${name(e.target)}`, true)
    }
    return out
  }, [graph, visible, marked, hotEdge, hover, sel.nodeId, nums])

  useEffect(() => { const t = window.setTimeout(() => rf.fitView({ padding: 0.15, duration: 0 }), 50); return () => window.clearTimeout(t) }, [rf, graph.nodes.length])
  // Панель портрета на узком экране скрыта (display: none) и измеряется нулём: после показа карту вписываем заново.
  useEffect(() => {
    const el = box.current
    if (!el) return
    let shown = el.clientWidth > 0 && el.clientHeight > 0
    const ro = new ResizeObserver(() => {
      const now = el.clientWidth > 0 && el.clientHeight > 0
      if (now && !shown) rf.fitView({ padding: 0.15, duration: 0 })
      shown = now
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [rf])
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

  const onNodesChange = useCallback((changes: NodeChange<Node<PData>>[]) => {
    let drag = false
    const dragged = new Set<string>()
    for (const c of changes) {
      // новый или изменившийся замер пересобирает узлы: мини-карта рисует только узлы с measured, раздвижка берёт реальный размер
      if (c.type === 'dimensions' && c.dimensions) {
        const was = sizes.current.get(c.id)
        drag ||= !was || Math.abs(was.width - c.dimensions.width) > 1 || Math.abs(was.height - c.dimensions.height) > 1
        sizes.current.set(c.id, c.dimensions)
      }
      if (c.type === 'position' && c.position) { positions.current = { ...positions.current, [c.id]: c.position }; dragged.add(c.id); drag = true }
    }
    if (dragged.size) pinned.current = dragged
    if (drag) force((x) => x + 1)
  }, [])
  useEffect(() => () => window.clearTimeout(hoverOut.current), [])
  // Состояние наведения меняется только при смене узла; отложенное снятие отменяется новым наведением.
  const hoverNode = (id: string | null, x = 0, y = 0) => {
    window.clearTimeout(hoverOut.current)
    if (id === hoverId.current) return
    hoverId.current = id
    setHover(id ? { id, x, y } : null)
    const rid = id ? graph.nodes.find((n) => n.id === id && n.kind === 'risk')?.data['risk_id'] : undefined
    setHoverRisks(rid ? [String(rid)] : null)
  }

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
    const stamp = todayISO()
    if (fmt === 'svg') { download(`doorain-portrait-${stamp}.svg`, new Blob([svg], { type: 'image/svg+xml' })); return }
    const png = await svgToPng(svg)
    if (png) download(`doorain-portrait-${stamp}.png`, png)
  }, [graph, visible, layout])

  const relayout = () => { positions.current = {}; pinned.current = new Set(); force((x) => x + 1); persist(filters) }
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
                <label key={k} className="flex min-h-11 items-center gap-1.5"><input type="checkbox" checked={filters.kinds[k]} onChange={(e) => setF({ ...filters, kinds: { ...filters.kinds, [k]: e.target.checked } })} />{k === 'question' ? 'Вопросы' : k === 'norm' ? 'Нормы' : 'Риски'}</label>
              ))}
              <label className="flex min-h-11 items-center gap-1.5"><input type="checkbox" checked={filters.showResolved} onChange={(e) => setF({ ...filters, showResolved: e.target.checked })} />Снятые</label>
            </fieldset>
            <div className="flex flex-wrap gap-2 border-t border-line-soft pt-3">
              <button className="btn" onClick={() => void exportGraph('svg')}><Download className="size-4" aria-hidden />SVG</button>
              <button className="btn" onClick={() => void exportGraph('png')}>PNG</button>
              <button className="btn btn-tertiary" onClick={relayout}><RotateCcw className="size-4" aria-hidden />Разложить заново</button>
            </div>
          </div>
        </details>
        {(sel.riskId || sel.nodeId || sel.messageId) && <button className="btn btn-tertiary" onClick={clear}>Снять выделение</button>}
        <span className="ml-auto"><HelpPopover label="Условные обозначения карты"><Legend questions={nums.size} /></HelpPopover></span>
      </div>
      <div ref={box} className="map-stage relative min-h-0 flex-1" onKeyDown={onKey}>
        <ReactFlow
          nodes={nodes} edges={edges} nodeTypes={nodeTypes} edgeTypes={edgeTypes} minZoom={0.15} maxZoom={2} fitView proOptions={{ hideAttribution: true }}
          nodesConnectable={false} deleteKeyCode={null} aria-label="Карта тем: цифровой слепок сессии"
          onNodeClick={(_, n) => activate(n.id)}
          onNodeDoubleClick={(_, n) => { if (graph.nodes.find((x) => x.id === n.id)?.kind === 'topic') setF({ ...filters, topic: n.id }) }}
          onNodesChange={onNodesChange}
          onNodeMouseEnter={(ev, n) => {
            const r = box.current?.getBoundingClientRect()
            if (r) hoverNode(n.id, ev.clientX - r.left, ev.clientY - r.top)
          }}
          onNodeMouseLeave={() => { window.clearTimeout(hoverOut.current); hoverOut.current = window.setTimeout(() => hoverNode(null), HOVER_OUT_MS) }}
          onNodeDragStop={(_, n) => { positions.current = { ...positions.current, [n.id]: n.position }; force((x) => x + 1); persist(filters) }}
          onPaneClick={() => { clear(); hoverNode(null) }}
          onEdgeMouseEnter={(_, e) => setHotEdge({ id: e.id, source: e.source, target: e.target })}
          onEdgeMouseLeave={() => setHotEdge(null)}
        >
          <Background gap={26} size={1} color={cssVar('--line')} />
          <Controls showInteractive={false} />
          <MiniMap pannable zoomable ariaLabel="Мини-карта слепка" nodeColor={minimapColor} maskColor="transparent" style={{ width: 120, height: 84, backgroundColor: 'var(--glass)' }} />
        </ReactFlow>
        {hover && <HoverCard graph={graph} hover={hover} sessionId={sessionId} nums={nums} />}
      </div>
      <ReasoningDrawer sessionId={sessionId} nodeId={drawer} onClose={() => setDrawer(null)} />
    </div>
  )
}

export function GraphView({ sessionId, graph }: { sessionId: string; graph: Graph }) {
  return <ReactFlowProvider><Inner sessionId={sessionId} graph={graph} /></ReactFlowProvider>
}
