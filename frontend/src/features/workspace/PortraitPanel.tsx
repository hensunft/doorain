import { useState } from 'react'
import { EmptyState, ErrorNote, Skeleton } from '../../components/States'
import { RiskBadge } from '../../components/ui'
import type { Graph, Risk, Session } from '../../lib/api'
import { useGraph, useRisks } from '../../lib/queries'
import { NODE_KIND_RU, RESULT_RU } from '../../lib/risk'
import { riskIdsForNode, useSelection } from '../../lib/selection'
import { GraphView } from './GraphView'

import type { PortraitMode } from './WorkspacePage'
import { PlanPanel } from './PlanPanel'
import { TimelineFlow } from './TimelineFlow'

/** Текстовая альтернатива графа: те же узлы и связи, доступные с клавиатуры и для чтения с экрана. */
function NodeList({ graph, risks }: { graph: Graph; risks: Risk[] }) {
  const { sel, selectNode, selectMessage, openCitation } = useSelection()
  const byId = new Map(graph.nodes.map((n) => [n.id, n]))
  const children = (id: string, kinds: string[], dir: 'in' | 'out') =>
    graph.edges.filter((e) => (dir === 'in' ? e.target === id : e.source === id) && kinds.includes(e.kind)).map((e) => byId.get(dir === 'in' ? e.source : e.target)).filter((n): n is Graph['nodes'][number] => !!n)
  const center = graph.nodes.find((n) => n.kind === 'center')
  const topics = children(center?.id ?? '', ['belongs_to'], 'in')
  const hl = riskIdsForNode(graph, risks, sel.nodeId)
  const Btn = ({ n }: { n: Graph['nodes'][number] }) => (
    <button type="button" className={`flex w-full items-center gap-2 rounded-md px-2 py-1 text-left text-small hover:bg-hover ${sel.nodeId === n.id ? 'bg-selected' : ''}`} onClick={() => { selectNode(n.id); if (n.kind === 'question' && n.data['message_id']) selectMessage(String(n.data['message_id'])); if (n.kind === 'norm' && n.data['citation_id']) openCitation(String(n.data['citation_id'])) }}>
      <span className="chip shrink-0">{NODE_KIND_RU[n.kind]}</span>
      <span className="min-w-0 flex-1 truncate">{n.label}</span>
      {n.kind === 'question' && typeof n.data['result'] === 'string' && n.data['result'] !== 'answered' && <span className="chip">{RESULT_RU[n.data['result']]}</span>}
      <RiskBadge level={n.risk_level ?? null} compact />
    </button>
  )
  return (
    <div className="space-y-2 overflow-y-auto p-3" aria-label="Список узлов слепка">
      {center && <p className="text-small font-medium">{center.label}</p>}
      <ul className="space-y-1">
        {topics.map((t) => (
          <li key={t.id}>
            <Btn n={t} />
            <ul className="ml-4 space-y-1 border-l border-line pl-2">
              {children(t.id, ['asks_about'], 'in').map((q) => (
                <li key={q.id}>
                  <Btn n={q} />
                  <ul className="ml-4 space-y-0.5">
                    {children(q.id, ['cites'], 'out').map((n) => <li key={n.id}><Btn n={n} /></li>)}
                    {children(q.id, ['evidences'], 'out').map((n) => <li key={n.id}><Btn n={n} /></li>)}
                  </ul>
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ul>
      {hl.size > 0 && <p className="hint">Связанные риски выделены в таблице справа.</p>}
    </div>
  )
}

export function PortraitPanel({ session, mode }: { session: Session; mode: PortraitMode }) {
  const [text, setText] = useState(false)  // текстовая альтернатива карты: доступна с клавиатуры и для чтения с экрана
  const graph = useGraph(session.id)
  const risks = useRisks(session.id)
  const questions = graph.data?.nodes.filter((n) => n.kind === 'question').length ?? 0
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center justify-between gap-2 border-b border-line px-3 py-2">
        <h2 className="display-s">Цифровой слепок <span className="caption font-normal">{graph.data ? `${graph.data.nodes.filter((n) => n.kind === 'topic').length} тем · ${questions} вопросов · ${graph.data.nodes.filter((n) => n.kind === 'norm').length} норм` : ''}</span></h2>
        {mode === 'map' && <button className="btn btn-quiet" aria-pressed={text} onClick={() => setText(!text)}>{text ? 'Показать карту' : 'Текстом'}</button>}
      </div>
      <div className="min-h-0 flex-1" aria-label="Портрет сессии">
        {graph.isLoading && <div className="p-3"><Skeleton lines={5} /></div>}
        {graph.isError && <div className="p-3"><ErrorNote error={graph.error} onRetry={() => graph.refetch()} /></div>}
        {graph.data && mode === 'map' && !text && (questions === 0 ? <EmptyState title="Портрет пока пуст">После первого вопроса здесь появятся темы, вопросы, нормы и связи. Цвет узла показывает максимальный активный риск.</EmptyState> : <GraphView sessionId={session.id} graph={graph.data} />)}
        {graph.data && mode === 'map' && text && <NodeList graph={graph.data} risks={risks.data?.active ?? []} />}
        {mode === 'timeline' && <TimelineFlow sessionId={session.id} />}
        {mode === 'plan' && <PlanPanel session={session} />}
      </div>
    </div>
  )
}
