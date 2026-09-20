import { useState } from 'react'
import { MapArt } from '../../components/art'
import { EmptyState, ErrorNote, Skeleton } from '../../components/States'
import { RiskBadge } from '../../components/ui'
import type { Graph, Risk, Session } from '../../lib/api'
import { useGraph, useRisks, useTimeline } from '../../lib/queries'
import { NODE_KIND_RU, RESULT_RU } from '../../lib/risk'
import { riskIdsForNode, useSelection } from '../../lib/selection'
import { GraphView } from './GraphView'

const TABS = [['map', 'Карта'], ['timeline', 'Хронология'], ['list', 'Список']] as const
type Tab = (typeof TABS)[number][0]

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

function Timeline({ sessionId }: { sessionId: string }) {
  const tl = useTimeline(sessionId)
  const { selectMessage, sel } = useSelection()
  if (tl.isLoading) return <div className="p-3"><Skeleton lines={4} /></div>
  if (tl.isError) return <div className="p-3"><ErrorNote error={tl.error} onRetry={() => tl.refetch()} /></div>
  if (!tl.data?.length) return <EmptyState title="Хронология пуста">Здесь появятся вопросы сессии по порядку, уточнения и связанные нормы и риски.</EmptyState>
  return (
    <ol className="space-y-2 overflow-y-auto p-3" aria-label="Хронология вопросов">
      {tl.data.map((it, i) => {
        const parent = it.follow_up_of ? tl.data.findIndex((x) => x.message_id === it.follow_up_of) + 1 : 0
        return (
          <li key={it.node_id} className={`rounded-md border p-2 ${sel.messageId === it.message_id ? 'border-graphite bg-sidebar' : 'border-line'}`}>
            <button type="button" className="w-full text-left" onClick={() => it.message_id && selectMessage(it.message_id)}>
              <span className="text-small font-medium">{i + 1}. {it.text}</span>
            </button>
            <div className="mt-1 flex flex-wrap gap-1.5 text-xs">
              {it.result && it.result !== 'answered' && <span className="chip">{RESULT_RU[it.result] ?? it.result}</span>}
              {it.topics.map((t) => <span key={t} className="chip">{t}</span>)}
              {it.norms.map((n) => <span key={n} className="chip">{n}</span>)}
              {it.risks.map((r) => <span key={r.node_id} className="chip risk-none">Риск: {r.label}</span>)}
            </div>
            {parent > 0 && <p className="hint mt-1">{it.condition ? `Ветка «если ${it.condition}» → к вопросу ${parent}` : `Уточнение к вопросу ${parent}`}</p>}
          </li>
        )
      })}
    </ol>
  )
}

export function PortraitPanel({ session }: { session: Session }) {
  const [tab, setTab] = useState<Tab>('map')
  const graph = useGraph(session.id)
  const risks = useRisks(session.id)
  const questions = graph.data?.nodes.filter((n) => n.kind === 'question').length ?? 0
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div role="tablist" aria-label="Вид портрета" className="flex gap-1 border-b border-line px-3 py-2">
        {TABS.map(([id, label]) => <button key={id} role="tab" id={`pt-${id}`} aria-selected={tab === id} aria-controls={`pp-${id}`} className={`btn ${tab === id ? 'btn-primary' : 'btn-quiet'}`} onClick={() => setTab(id)}>{label}</button>)}
      </div>
      <div role="tabpanel" id={`pp-${tab}`} aria-labelledby={`pt-${tab}`} className="min-h-0 flex-1">
        {graph.isLoading && <div className="p-3"><Skeleton lines={5} /></div>}
        {graph.isError && <div className="p-3"><ErrorNote error={graph.error} onRetry={() => graph.refetch()} /></div>}
        {graph.data && tab === 'map' && (questions === 0 ? <EmptyState art={MapArt} title="Портрет пока пуст">После первого вопроса здесь появятся темы, вопросы, нормы и связи. Цвет узла показывает максимальный активный риск.</EmptyState> : <GraphView sessionId={session.id} graph={graph.data} />)}
        {graph.data && tab === 'list' && <NodeList graph={graph.data} risks={risks.data?.active ?? []} />}
        {tab === 'timeline' && <Timeline sessionId={session.id} />}
      </div>
    </div>
  )
}
