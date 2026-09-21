import type { Graph, GraphNode } from '../../lib/api'

/** Чистая логика слепка: нумерация, счётчики, нить диалога, ветка наведения, уровни детализации, радиальная раскладка. */

export type Positions = Record<string, { x: number; y: number }>
export type Lod = 'topics' | 'questions' | 'full'

export const TEXT_SHORT = 60

export const short = (s: string, n = TEXT_SHORT): string => (s.length > n ? `${s.slice(0, n - 1)}…` : s)

/** Вопросы по порядку появления: номер нужен и на карте, и в хронологии, и в карточках рисков. */
export function questionNumbers(graph: Graph): Map<string, number> {
  const qs = graph.nodes.filter((n) => n.kind === 'question')
  qs.sort((a, b) => Number(a.data['seq'] ?? 0) - Number(b.data['seq'] ?? 0))
  return new Map(qs.map((q, i) => [q.id, i + 1]))
}

export interface TopicCounters { questions: number; norms: number; risks: number }

/** Счётчики внутри капсулы темы: вопросов, различных норм в ответах на них, активных рисков. */
export function topicCounters(graph: Graph): Map<string, TopicCounters> {
  const out = new Map<string, TopicCounters>()
  const byId = new Map(graph.nodes.map((n) => [n.id, n]))
  for (const t of graph.nodes.filter((n) => n.kind === 'topic')) {
    const qs = graph.edges.filter((e) => e.kind === 'asks_about' && e.target === t.id).map((e) => e.source)
    const norms = new Set(graph.edges.filter((e) => e.kind === 'cites' && qs.includes(e.source)).map((e) => e.target))
    out.set(t.id, { questions: qs.length, norms: norms.size, risks: byId.get(t.id)?.risk_count ?? 0 })
  }
  return out
}

const plural = (n: number, one: string, few: string, many: string) => {
  const m10 = n % 10, m100 = n % 100
  return `${n} ${m10 === 1 && m100 !== 11 ? one : m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14) ? few : many}`
}
export const countersText = (c: TopicCounters): string =>
  [plural(c.questions, 'вопрос', 'вопроса', 'вопросов'), plural(c.norms, 'норма', 'нормы', 'норм'), c.risks ? plural(c.risks, 'риск', 'риска', 'рисков') : '']
    .filter(Boolean).join(' · ')

/** Нить диалога asked_next: связь каждого вопроса со следующим по порядку (в БД не хранится — выводится из номеров). */
export function dialogThread(graph: Graph): { id: string; source: string; target: string; kind: 'asked_next' }[] {
  const nums = questionNumbers(graph)
  const ordered = [...nums.entries()].sort((a, b) => a[1] - b[1]).map(([id]) => id)
  return ordered.slice(1).map((id, i) => ({ id: `next:${ordered[i]}:${id}`, source: ordered[i] as string, target: id, kind: 'asked_next' as const }))
}

/** Ветка при наведении: путь от центра к узлу и его непосредственные основания. Остальной граф приглушается. */
export function branchOf(graph: Graph, nodeId: string): Set<string> {
  const node = graph.nodes.find((n) => n.id === nodeId)
  const out = new Set<string>([nodeId])
  if (!node) return out
  const center = graph.nodes.find((n) => n.kind === 'center')
  if (center) out.add(center.id)
  const nb = (id: string, kinds: string[], dir: 'out' | 'in') =>
    graph.edges.filter((e) => kinds.includes(e.kind) && (dir === 'out' ? e.source === id : e.target === id)).map((e) => (dir === 'out' ? e.target : e.source))
  const addQuestion = (q: string) => {
    out.add(q)
    nb(q, ['asks_about'], 'out').forEach((t) => out.add(t))
    nb(q, ['cites', 'evidences'], 'out').forEach((x) => out.add(x))
  }
  if (node.kind === 'center') return new Set(graph.nodes.map((n) => n.id))
  if (node.kind === 'question') addQuestion(node.id)
  if (node.kind === 'topic') nb(node.id, ['asks_about'], 'in').forEach(addQuestion)
  if (node.kind === 'norm') nb(node.id, ['cites'], 'in').forEach(addQuestion)
  if (node.kind === 'risk') nb(node.id, ['evidences'], 'in').forEach(addQuestion)
  return out
}

/** Уровни детализации: при отдалении подписи и мелкие узлы скрываются. */
export function lodFor(zoom: number): Lod {
  return zoom < 0.5 ? 'topics' : zoom < 1 ? 'questions' : 'full'
}
export function visibleAt(kind: GraphNode['kind'], lod: Lod): boolean {
  if (kind === 'center' || kind === 'topic') return true
  if (kind === 'question') return lod !== 'topics'
  return lod === 'full'
}

/** Радиус растёт логарифмически от числа связей: ключевые темы и нормы заметнее, но граф не «раздувается». */
export const growth = (weight: number): number => Math.min(1.45, 1 + Math.log2(Math.max(1, weight)) * 0.12)

export const BOX: Record<GraphNode['kind'], { w: number; h: number }> = {
  center: { w: 120, h: 118 },
  topic: { w: 230, h: 52 },
  question: { w: 200, h: 44 },
  norm: { w: 86, h: 66 },
  risk: { w: 44, h: 44 },
}

/** Радиальная раскладка: центр в середине, темы по окружности, вопросы — дугой снаружи своей темы, нормы — ещё дальше.
 *  Уже размещённые узлы (keep) не двигаются: новые узлы не перетряхивают граф. */
export function radialLayout(graph: Graph, visible: GraphNode[], keep: Positions): Positions {
  const ids = new Set(visible.map((n) => n.id))
  const topics = visible.filter((n) => n.kind === 'topic')
  const T = Math.max(1, topics.length)
  const R1 = 170 + 16 * T
  const R2 = R1 + 150
  const R3 = R2 + 110
  const center: Positions = {}
  const angle = new Map<string, number>()
  const at = (a: number, r: number) => ({ x: Math.cos(a) * r, y: Math.sin(a) * r })
  const c = visible.find((n) => n.kind === 'center')
  if (c) center[c.id] = { x: 0, y: 0 }
  topics.forEach((t, i) => {
    const a = -Math.PI / 2 + (2 * Math.PI * i) / T
    angle.set(t.id, a)
    center[t.id] = at(a, R1)
  })
  const nums = questionNumbers(graph)
  const qOfTopic = new Map<string, string[]>()
  const loose: string[] = []
  for (const q of visible.filter((n) => n.kind === 'question').sort((a, b) => (nums.get(a.id) ?? 0) - (nums.get(b.id) ?? 0))) {
    const t = graph.edges.find((e) => e.kind === 'asks_about' && e.source === q.id && ids.has(e.target) && angle.has(e.target))?.target
    if (t) qOfTopic.set(t, [...(qOfTopic.get(t) ?? []), q.id])
    else loose.push(q.id)
  }
  const sector = (2 * Math.PI) / T
  for (const [t, qs] of qOfTopic) {
    const base = angle.get(t) ?? 0
    const step = Math.min(0.32, (sector * 0.8) / Math.max(1, qs.length))
    qs.forEach((q, j) => {
      const a = base + (j - (qs.length - 1) / 2) * step
      angle.set(q, a)
      center[q] = at(a, R2)
    })
  }
  loose.forEach((q, j) => {
    const a = Math.PI / 2 + (j - (loose.length - 1) / 2) * 0.3
    angle.set(q, a)
    center[q] = at(a, R1 * 0.55)
  })
  const placedNorm = new Map<string, number>()
  for (const n of visible.filter((x) => x.kind === 'norm' || x.kind === 'risk')) {
    const src = graph.edges.find((e) => (e.kind === 'cites' || e.kind === 'evidences') && e.target === n.id && angle.has(e.source))?.source
    const a0 = src ? (angle.get(src) ?? 0) : 0
    const k = placedNorm.get(src ?? '') ?? 0
    placedNorm.set(src ?? '', k + 1)
    const a = a0 + (k - 0.5) * 0.14 * (n.kind === 'risk' ? -1 : 1)
    center[n.id] = at(a, n.kind === 'risk' ? R2 + 70 : R3 + (k % 2) * 40)
  }
  const out: Positions = {}
  for (const n of visible) {
    const kept = keep[n.id]
    if (kept) { out[n.id] = kept; continue }
    const p = center[n.id] ?? { x: 0, y: 0 }
    const b = BOX[n.kind]
    out[n.id] = { x: Math.round(p.x - b.w / 2), y: Math.round(p.y - b.h / 2) }
  }
  separate(visible, out, new Set(Object.keys(keep)))
  return out
}

/** Раздвигает пересекающиеся прямоугольники узлов; закреплённые (уже размещённые) узлы не двигаются.
 *  ponytail: O(n²) за проход, до 60 проходов — достаточно для слепка в сотни узлов; при тысячах нужен пространственный индекс. */
export function separate(nodes: GraphNode[], pos: Positions, fixed: Set<string>, gap = 10): void {
  for (let iter = 0; iter < 60; iter++) {
    let moved = false
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const a = nodes[i]!, b = nodes[j]!
        const pa = pos[a.id], pb = pos[b.id]
        if (!pa || !pb || (fixed.has(a.id) && fixed.has(b.id))) continue
        const A = BOX[a.kind], B = BOX[b.kind]
        const dx = Math.min(pa.x + A.w, pb.x + B.w) - Math.max(pa.x, pb.x) + gap
        const dy = Math.min(pa.y + A.h, pb.y + B.h) - Math.max(pa.y, pb.y) + gap
        if (dx <= 0 || dy <= 0) continue
        moved = true
        const horizontal = dx < dy
        const sign = horizontal ? Math.sign(pa.x + A.w / 2 - (pb.x + B.w / 2)) || 1 : Math.sign(pa.y + A.h / 2 - (pb.y + B.h / 2)) || 1
        const shift = (horizontal ? dx : dy) / (fixed.has(a.id) || fixed.has(b.id) ? 1 : 2)
        const move = (id: string, s: number) => {
          if (fixed.has(id)) return
          const p = pos[id]!
          pos[id] = horizontal ? { x: Math.round(p.x + s * shift), y: p.y } : { x: p.x, y: Math.round(p.y + s * shift) }
        }
        move(a.id, sign)
        move(b.id, -sign)
      }
    }
    if (!moved) return
  }
}

/** Короткая подпись нормы для шестиугольника: номер акта сверху, статья снизу («152» / «ст. 22»). */
export function normParts(label: string): { act: string; loc: string } {
  const [act = '', ...rest] = label.split(',')
  const num = act.match(/\d+(?:-[А-ЯA-Z]+)?/)?.[0]
  const code = act.match(/КоАП|ГК|УК|ТК|НК/)?.[0]
  return { act: code ?? (num ? num.replace(/-ФЗ$/, '') : short(act.trim(), 8)), loc: rest.join(',').trim() }
}
