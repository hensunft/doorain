import { CircleAlert } from 'lucide-react'
import { useState } from 'react'
import { Dialog } from '../../components/Dialog'
import { Skeleton } from '../../components/States'
import type { Block, CitationChip, Graph, Message, Risk } from '../../lib/api'
import { useCitation, useGraph, useMessages, useRisks } from '../../lib/queries'
import { LEVEL_RU } from '../../lib/risk'
import { riskIdsForNode, useSelection } from '../../lib/selection'
import { questionNumbers } from './graphModel'

/** Цитата раскрывается по кнопке: фрагмент запрашивается только тогда, когда пользователь захотел его увидеть. */
function Quote({ citationId }: { citationId: string }) {
  const q = useCitation(citationId)
  if (q.isLoading) return <Skeleton lines={2} />
  if (!q.data) return null
  return <blockquote className="mono-m mt-2 whitespace-pre-wrap rounded-md border-l-2 border-gold bg-panel px-3 py-2 text-ink-2">«{q.data.excerpt.slice(0, 420)}{q.data.excerpt.length > 420 ? '…' : ''}»</blockquote>
}

function Step({ n, block, chips }: { n: number; block: Block; chips: CitationChip[] }) {
  const [open, setOpen] = useState<string | null>(null)
  const found = block.citation_ids.map((id) => chips.find((c) => c.id === id)).filter((c): c is CitationChip => !!c)
  return (
    <li className="flex gap-3">
      <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-brand text-xs font-semibold" style={{ color: 'var(--brand-on)' }}>{n}</span>
      <div className="min-w-0 flex-1 border-l border-line-soft pl-3">
        <p className="body-m">{block.text}</p>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          {found.map((c) => (
            <span key={c.id} className="flex flex-wrap items-center gap-2">
              <span className="chip-norm">{c.label}, {c.locator} · {c.revision_label}</span>
              <button type="button" className="btn body-s" aria-expanded={open === c.id} onClick={() => setOpen(open === c.id ? null : c.id)}>
                {open === c.id ? 'скрыть цитату' : 'показать цитату'}
              </button>
            </span>
          ))}
        </div>
        {open && <Quote citationId={open} />}
      </div>
    </li>
  )
}

function answerOf(msgs: Message[], messageId: string): Message | undefined {
  const i = msgs.findIndex((m) => m.id === messageId)
  return i >= 0 ? msgs.slice(i + 1).find((m) => m.role === 'assistant') : undefined
}

/** Ветка рассуждений по вопросу: шаги ответа с нормами, вывод, риск и действия. Шаг без ссылки на фрагмент не показывается. */
export function ReasoningDrawer({ sessionId, nodeId, onClose }: { sessionId: string; nodeId: string | null; onClose: () => void }) {
  const graph = useGraph(sessionId)
  const msgs = useMessages(sessionId)
  const risks = useRisks(sessionId)
  const { selectMessage, selectRisk, requestPrefill } = useSelection()
  const g: Graph | undefined = graph.data
  const node = g?.nodes.find((n) => n.id === nodeId)
  const num = node && g ? questionNumbers(g).get(node.id) : undefined
  const mid = node ? String(node.data['message_id'] ?? '') : ''
  const answer = msgs.data && mid ? answerOf(msgs.data, mid) : undefined
  const claims = (answer?.blocks ?? []).filter((b) => b.kind === 'claim' && b.state === 'verified' && b.citation_ids.length > 0)
  const [conclusion, ...steps] = claims
  const all: Risk[] = risks.data ? [...risks.data.active, ...risks.data.resolved] : []
  const ids = g && node ? riskIdsForNode(g, all, node.id) : new Set<string>()
  const linked = all.filter((r) => ids.has(r.id))
  const go = (fn: () => void) => { fn(); onClose() }
  return (
    <Dialog open={!!node} onClose={onClose} variant="drawer" overline="Ветка рассуждений" title={node ? `Вопрос №${num ?? ''}. ${node.label}` : ''}>
      {!answer && <p className="hint">Ответ на этот вопрос ещё не сформирован или был отказом: шагов с основаниями нет.</p>}
      {answer && (
        <div className="space-y-5">
          {(steps.length ? steps : claims).length > 0 && (
            <ol className="space-y-4">
              {(steps.length ? steps : claims).map((b, i) => <Step key={b.id} n={i + 1} block={b} chips={answer.citations} />)}
            </ol>
          )}
          {conclusion && steps.length > 0 && (
            <section className="rounded-lg bg-sidebar p-3">
              <p className="overline">Вывод</p>
              <p className="body-m mt-1">{conclusion.text}</p>
            </section>
          )}
          {linked.map((r) => (
            <article key={r.id} className="card card-risk" data-level={r.level ?? 'none'}>
              <div className="flex items-start justify-between gap-3">
                <h3 className="body-l font-semibold">Риск: {r.title}</h3>
                <span className="badge-level shrink-0" data-level={r.level ?? 'none'}>{r.p} × {r.s} = {r.score}</span>
              </div>
              <p className="caption mt-0.5">{r.level ? LEVEL_RU[r.level] : 'Не оценён'}</p>
              {r.recommendation && <p className="body-s mt-2">Рекомендация: {r.recommendation}</p>}
            </article>
          ))}
          <div className="flex flex-wrap gap-2">
            <button type="button" className="btn btn-primary" onClick={() => go(() => selectMessage(mid))}>Открыть в чате</button>
            <button type="button" className="btn" onClick={() => go(() => requestPrefill(`По вопросу №${num ?? ''} «${node?.label.slice(0, 60) ?? ''}»: `))}>Уточнить по этому узлу</button>
            {linked[0] && <button type="button" className="btn" onClick={() => go(() => selectRisk(linked[0]!.id))}>Перейти к риску</button>}
          </div>
          <p className="caption flex items-center gap-1.5"><CircleAlert className="size-3.5" aria-hidden />Шаг без ссылки на фрагмент базы знаний не отображается.</p>
        </div>
      )}
    </Dialog>
  )
}
