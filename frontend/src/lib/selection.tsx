/** Двусторонняя навигация чат ↔ граф ↔ риски ↔ источник: общее состояние выделения + чистые функции связей. */
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'
import type { Graph, Risk } from './api'

export interface SelectionState {
  riskId: string | null
  nodeId: string | null
  messageId: string | null
  citationId: string | null
}
const empty: SelectionState = { riskId: null, nodeId: null, messageId: null, citationId: null }

interface Ctx {
  sel: SelectionState
  selectRisk: (id: string | null) => void
  selectNode: (id: string | null) => void
  selectMessage: (id: string | null) => void
  openCitation: (id: string | null) => void
  clear: () => void
  /** Текст, который нужно подставить в поле вопроса (например, «Уточнить по этому узлу»). */
  prefill: string | null
  requestPrefill: (text: string | null) => void
}
const SelCtx = createContext<Ctx | null>(null)

export function SelectionProvider({ children }: { children: ReactNode }) {
  const [sel, setSel] = useState<SelectionState>(empty)
  const [prefill, requestPrefill] = useState<string | null>(null)
  const selectRisk = useCallback((id: string | null) => setSel((s) => ({ ...s, riskId: id, nodeId: null })), [])
  const selectNode = useCallback((id: string | null) => setSel((s) => ({ ...s, nodeId: id, riskId: null })), [])
  const selectMessage = useCallback((id: string | null) => setSel((s) => ({ ...s, messageId: id })), [])
  const openCitation = useCallback((id: string | null) => setSel((s) => ({ ...s, citationId: id })), [])
  const clear = useCallback(() => setSel((s) => ({ ...empty, citationId: s.citationId })), [])
  const value = useMemo(() => ({ sel, selectRisk, selectNode, selectMessage, openCitation, clear, prefill, requestPrefill }), [sel, selectRisk, selectNode, selectMessage, openCitation, clear, prefill])
  return <SelCtx.Provider value={value}>{children}</SelCtx.Provider>
}

export function useSelection(): Ctx {
  const c = useContext(SelCtx)
  if (!c) throw new Error('SelectionProvider отсутствует')
  return c
}

/** Узлы графа, подсвечиваемые при выборе риска: сам узел риска, связанные вопросы и нормы. */
export function nodesForRisk(graph: Graph | undefined, riskId: string | null): Set<string> {
  const out = new Set<string>()
  if (!graph || !riskId) return out
  const rn = graph.nodes.find((n) => n.kind === 'risk' && n.data['risk_id'] === riskId)
  if (!rn) return out
  out.add(rn.id)
  for (const e of graph.edges) {
    if (e.source === rn.id) out.add(e.target)
    if (e.target === rn.id) out.add(e.source)
  }
  return out
}

/** Строки рисков, связанные с узлом графа (вопрос/норма/тема/риск). */
export function riskIdsForNode(graph: Graph | undefined, risks: Risk[], nodeId: string | null): Set<string> {
  const out = new Set<string>()
  if (!graph || !nodeId) return out
  const node = graph.nodes.find((n) => n.id === nodeId)
  if (!node) return out
  const riskNodeToId = new Map(graph.nodes.filter((n) => n.kind === 'risk').map((n) => [n.id, String(n.data['risk_id'])]))
  const riskNeighbors = (id: string) => graph.edges.flatMap((e) => (e.source === id && riskNodeToId.has(e.target) ? [e.target] : e.target === id && riskNodeToId.has(e.source) ? [e.source] : []))
  if (node.kind === 'risk') {
    const r = riskNodeToId.get(node.id)
    if (r) out.add(r)
  } else if (node.kind === 'topic') {
    const qs = graph.edges.filter((e) => e.kind === 'asks_about' && e.target === node.id).map((e) => e.source)
    for (const q of qs) for (const rn of riskNeighbors(q)) { const r = riskNodeToId.get(rn); if (r) out.add(r) }
  } else {
    for (const rn of riskNeighbors(node.id)) { const r = riskNodeToId.get(rn); if (r) out.add(r) }
  }
  const known = new Set(risks.map((r) => r.id))
  return new Set([...out].filter((x) => known.has(x)))
}
