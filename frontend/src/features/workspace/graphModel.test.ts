import { describe, expect, it } from 'vitest'
import type { Graph } from '../../lib/api'
import { BOX, branchOf, countersText, dialogThread, lodFor, normParts, questionNumbers, radialLayout, separate, swingPush, swingStep, topicCounters, visibleAt } from './graphModel'

const n = (id: string, kind: Graph['nodes'][number]['kind'], extra: Partial<Graph['nodes'][number]> = {}) =>
  ({ id, kind, label: id, weight: 1, risk_level: null, resolved_level: null, risk_count: 0, data: {}, ...extra }) as Graph['nodes'][number]
const e = (source: string, target: string, kind: string) => ({ id: `${source}-${target}-${kind}`, source, target, kind, data: {} })

const graph: Graph = {
  nodes: [
    n('c', 'center'), n('t1', 'topic', { risk_count: 2 }), n('t2', 'topic'),
    n('q1', 'question', { data: { seq: 1 } }), n('q2', 'question', { data: { seq: 3 } }), n('q3', 'question', { data: { seq: 5 } }),
    n('n1', 'norm', { label: '152-ФЗ, ст. 22 ч. 1' }), n('n2', 'norm', { label: 'КоАП РФ, ст. 13.11' }),
  ],
  edges: [
    e('t1', 'c', 'belongs_to'), e('t2', 'c', 'belongs_to'),
    e('q1', 't1', 'asks_about'), e('q2', 't1', 'asks_about'), e('q3', 't2', 'asks_about'),
    e('q1', 'n1', 'cites'), e('q2', 'n1', 'cites'), e('q2', 'n2', 'cites'), e('q3', 'n2', 'cites'),
  ],
  positions: {}, filters: {}, topics: [],
}

describe('модель слепка', () => {
  it('нумерует вопросы по порядку появления и строит нить диалога', () => {
    expect([...questionNumbers(graph).entries()]).toEqual([['q1', 1], ['q2', 2], ['q3', 3]])
    expect(dialogThread(graph).map((x) => [x.source, x.target])).toEqual([['q1', 'q2'], ['q2', 'q3']])
  })

  it('считает вопросы, различные нормы и риски темы', () => {
    const c = topicCounters(graph).get('t1')
    expect(c).toEqual({ questions: 2, norms: 2, risks: 2 })
    expect(countersText(c!)).toBe('2 вопроса · 2 нормы · 2 риска')
    expect(countersText({ questions: 1, norms: 5, risks: 0 })).toBe('1 вопрос · 5 норм')
  })

  it('ветка наведения: путь от центра и основания, остальное вне ветки', () => {
    const b = branchOf(graph, 'q1')
    expect([...b].sort()).toEqual(['c', 'n1', 'q1', 't1'])
    expect(b.has('q3')).toBe(false)
    expect(branchOf(graph, 't2').has('n2')).toBe(true)
  })

  it('уровни детализации по зуму', () => {
    expect([lodFor(0.3), lodFor(0.7), lodFor(1.2)]).toEqual(['topics', 'questions', 'full'])
    expect(visibleAt('question', 'topics')).toBe(false)
    expect(visibleAt('norm', 'questions')).toBe(false)
    expect(visibleAt('topic', 'topics')).toBe(true)
  })

  it('раскладка стабильна: размещённые узлы не двигаются', () => {
    const first = radialLayout(graph, graph.nodes, {})
    const moved = { ...first, t1: { x: 999, y: 999 } }
    const again = radialLayout(graph, graph.nodes, moved)
    expect(again['t1']).toEqual({ x: 999, y: 999 })
    expect(again['q3']).toEqual(first['q3'])
    expect(new Set(Object.values(first).map((p) => `${p.x}:${p.y}`)).size).toBe(graph.nodes.length) // без наложений в одной точке
  })

  it('узлы не накладываются: раздвижка сохраняет закреплённые позиции', () => {
    const qs = ['a', 'b', 'c', 'd'].map((id) => n(id, 'question'))
    const pos = Object.fromEntries(qs.map((q) => [q.id, { x: 0, y: 0 }]))
    pos['a'] = { x: 0, y: 0 }
    separate(qs, pos, new Set(['a']))
    expect(pos['a']).toEqual({ x: 0, y: 0 })
    const W = BOX.question.w, H = BOX.question.h
    for (const x of qs) for (const y of qs) {
      if (x.id >= y.id) continue
      const px = pos[x.id]!, py = pos[y.id]!
      expect(px.x + W <= py.x || py.x + W <= px.x || px.y + H <= py.y || py.y + H <= px.y).toBe(true)
    }
  })

  it('раздвижка по видимым размерам: масштаб капсулы темы и сохранённые позиции тоже раздвигаются', () => {
    const ts = [n('a', 'topic'), n('b', 'topic'), n('c', 'question')]
    const pos = { a: { x: 0, y: 0 }, b: { x: 10, y: 40 }, c: { x: 20, y: 30 } }  // все «сохранены» внахлёст
    const size = (x: Graph['nodes'][number]) => (x.kind === 'topic' ? { w: 200, h: 50, k: 1.4 } : { w: 180, h: 56 })
    separate(ts, pos, new Set(['a']), size)
    expect(pos.a).toEqual({ x: 0, y: 0 })  // перетащенный пользователем остаётся на месте
    const rect = (id: 'a' | 'b' | 'c'): [number, number, number, number] => { const s = size(ts.find((x) => x.id === id)!), k = s.k ?? 1; const cx = pos[id].x + s.w / 2, cy = pos[id].y + s.h / 2; return [cx - (s.w * k) / 2, cy - (s.h * k) / 2, cx + (s.w * k) / 2, cy + (s.h * k) / 2] }
    for (const [x, y] of [['a', 'b'], ['a', 'c'], ['b', 'c']] as const) {
      const [a1, b1, c1, d1] = rect(x), [a2, b2, c2, d2] = rect(y)
      expect(c1 <= a2 || c2 <= a1 || d1 <= b2 || d2 <= b1, `${x} и ${y} пересекаются`).toBe(true)
    }
  })

  it('весы: сдвиг вправо отклоняет чаши, колебания затухают и весы успокаиваются', () => {
    const s = { pan: 0, panV: 0, beam: 0, beamV: 0 }
    swingPush(s, 30)
    swingStep(s, 0.016)
    expect(s.pan).toBeGreaterThan(0)
    let frames = 0, crossed = false
    while (swingStep(s, 0.016) && frames < 2000) { frames++; crossed ||= s.pan < 0 }
    expect(crossed).toBe(true)  // качается через середину, а не просто возвращается
    expect(frames * 0.016).toBeLessThan(8)
    expect(Math.abs(s.pan)).toBeLessThan(0.05)
  })

  it('подпись нормы для шестиугольника', () => {
    expect(normParts('152-ФЗ, ст. 22 ч. 1')).toEqual({ act: '152', loc: 'ст. 22 ч. 1' })
    expect(normParts('КоАП РФ, ст. 13.11')).toEqual({ act: 'КоАП', loc: 'ст. 13.11' })
  })
})
