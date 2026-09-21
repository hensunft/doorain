import { describe, expect, it } from 'vitest'
import type { Graph, Risk } from './api'
import { LEVEL_ORDER, levelOf } from './risk'
import { nodesForRisk, riskIdsForNode } from './selection'

const node = (id: string, kind: Graph['nodes'][number]['kind'], data: Record<string, unknown> = {}) => ({ id, kind, label: id, weight: 1, risk_level: null, data }) as Graph['nodes'][number]
const edge = (s: string, t: string, kind: string) => ({ id: `${s}-${t}`, source: s, target: t, kind, data: {} })
const graph: Graph = {
  nodes: [node('c', 'center'), node('t1', 'topic'), node('q1', 'question', { message_id: 'm1' }), node('q2', 'question', { message_id: 'm2' }), node('n1', 'norm'), node('r1', 'risk', { risk_id: 'R1' }), node('r2', 'risk', { risk_id: 'R2' })],
  edges: [edge('t1', 'c', 'belongs_to'), edge('q1', 't1', 'asks_about'), edge('q2', 't1', 'asks_about'), edge('q1', 'n1', 'cites'), edge('q1', 'r1', 'evidences'), edge('r1', 'n1', 'grounded_in'), edge('q2', 'r2', 'evidences')],
  positions: {}, filters: {}, topics: [],
}
const risks = [{ id: 'R1' }, { id: 'R2' }] as Risk[]

describe('двусторонняя навигация граф ↔ риски', () => {
  it('клик по риску подсвечивает сам узел, связанные вопросы и нормы', () => {
    expect([...nodesForRisk(graph, 'R1')].sort()).toEqual(['n1', 'q1', 'r1'])
  })
  it('клик по вопросу выделяет только его строки рисков', () => {
    expect([...riskIdsForNode(graph, risks, 'q1')]).toEqual(['R1'])
    expect([...riskIdsForNode(graph, risks, 'q2')]).toEqual(['R2'])
  })
  it('клик по норме выделяет риски, основанные на ней', () => {
    expect([...riskIdsForNode(graph, risks, 'n1')]).toEqual(['R1'])
  })
  it('клик по теме собирает риски всех её вопросов', () => {
    expect([...riskIdsForNode(graph, risks, 't1')].sort()).toEqual(['R1', 'R2'])
  })
  it('очистка выделения даёт пустые множества', () => {
    expect(nodesForRisk(graph, null).size).toBe(0)
    expect(riskIdsForNode(graph, risks, null).size).toBe(0)
  })
})

describe('уровни риска', () => {
  it.each([[1, 'low'], [4, 'low'], [5, 'medium'], [9, 'medium'], [10, 'high'], [15, 'high'], [16, 'critical'], [25, 'critical']])('score %i → %s', (s, l) => {
    expect(levelOf(s, [4, 9, 15])).toBe(l)
  })
  it('нет оценки или порогов — нет уровня', () => { expect(levelOf(null, [4, 9, 15])).toBeNull(); expect(levelOf(8, undefined)).toBeNull(); expect(LEVEL_ORDER).toHaveLength(4) })
  it('пороги приходят с сервера: сдвиг меняет уровень', () => { expect(levelOf(8, [3, 7, 14])).toBe('high') })
})
