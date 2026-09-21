import { EmptyState, ErrorNote, Skeleton } from '../../components/States'
import type { Level, Message, TimelineItem } from '../../lib/api'
import { useMessages, useTimeline } from '../../lib/queries'
import { LEVEL_RU, STATUS_RU } from '../../lib/risk'
import { useSelection } from '../../lib/selection'
import { short } from './graphModel'

interface TRisk { node_id: string; label: string; risk_id: string | null; level: Level | null; score: number | null; p: number | null; s: number | null; status: string | null; recommendation: string; closed_at: string | null }

const RANK: Record<Level, number> = { low: 1, medium: 2, high: 3, critical: 4 }
const topLevel = (rs: TRisk[]): Level | null =>
  rs.filter((r) => r.status === 'open' || r.status === 'in_progress').reduce<Level | null>((m, r) => (r.level && (!m || RANK[r.level] > RANK[m]) ? r.level : m), null)
const closedAll = (rs: TRisk[]) => rs.length > 0 && rs.every((r) => r.status === 'resolved' || r.status === 'not_applicable')
const time = (at: string | null | undefined) => (at ? new Date(at).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' }) : '')

function conclusionOf(msgs: Message[] | undefined, messageId: string | null): string {
  if (!msgs || !messageId) return ''
  const i = msgs.findIndex((m) => m.id === messageId)
  const ans = i >= 0 ? msgs.slice(i + 1).find((m) => m.role === 'assistant') : undefined
  const b = ans?.blocks?.find((x) => x.kind === 'claim' && x.state === 'verified')
  return b ? short(b.text, 180) : ''
}

function Arrow() {
  return (
    <svg className="mx-auto block" width="14" height="30" viewBox="0 0 14 30" aria-hidden>
      <line x1="7" y1="0" x2="7" y2="22" stroke="var(--gold)" strokeWidth="2" />
      <polygon points="1,20 13,20 7,29" fill="var(--gold)" />
    </svg>
  )
}

function QuestionCard({ it, onOpen, active }: { it: TimelineItem; onOpen: () => void; active: boolean }) {
  const risks = it.risks as unknown as TRisk[]
  const lv = topLevel(risks)
  const closed = closedAll(risks)
  return (
    <button
      type="button"
      onClick={onOpen}
      data-level={lv ?? 'none'}
      className={`card w-full border-2 text-left transition-colors ${lv ? 'border-[var(--level)]' : 'border-line-strong'} ${closed ? 'border-dashed opacity-80' : ''} ${active ? 'ring-1 ring-gold' : ''}`}
    >
      <span className="flex items-start gap-3">
        <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-[var(--level-tint)] font-mono text-xs font-medium text-[var(--level-ink)]">{it.seq}</span>
        <span className="min-w-0">
          <span className={`body-l block font-semibold ${closed ? 'text-muted' : ''}`}>{it.text}</span>
          <span className="mono-m mt-1 block text-muted">{[time(it.at), it.topics.length ? `тема: ${it.topics.join(', ').toLowerCase()}` : '', it.follow_up_of ? 'уточнение' : ''].filter(Boolean).join(' · ')}</span>
          {closed && <span className="mt-2 inline-flex items-center gap-2"><span className="chip risk-low">высветлен · закрыт</span><span className="caption">след прежнего цвета сохранён</span></span>}
        </span>
      </span>
    </button>
  )
}

function Bases({ it, conclusion }: { it: TimelineItem; conclusion: string }) {
  if (!it.norms.length && !conclusion) return null
  return (
    <div className="card">
      <p className="overline">Основания</p>
      <div className="mt-2 flex flex-wrap gap-2">{it.norms.map((n) => <span key={n} className="chip-norm">{n}</span>)}</div>
      {conclusion && <p className="body-m mt-2">Вывод: {conclusion}</p>}
    </div>
  )
}

function RiskBox({ r, onOpen }: { r: TRisk; onOpen: () => void }) {
  const closed = r.status === 'resolved' || r.status === 'not_applicable'
  return (
    <button type="button" onClick={onOpen} className={`card card-risk w-full text-left ${closed ? 'opacity-[0.78]' : ''}`} data-level={r.level ?? 'none'}>
      <span className="overline block">Риск{r.level ? ` · ${LEVEL_RU[r.level].toLowerCase()}` : ''}</span>
      <span className={`body-l mt-1 block font-semibold ${closed ? 'text-muted line-through' : ''}`}>{r.label}</span>
      <span className="mt-2 flex flex-wrap items-center gap-2">
        {r.score != null && <span className="badge-level" data-level={r.level ?? 'none'}>{r.p} × {r.s} = {r.score}</span>}
        <span className="caption">{r.level ? LEVEL_RU[r.level].toLowerCase() : 'не оценён'} · статус: {(STATUS_RU[r.status ?? ''] ?? r.status ?? '').toLowerCase()}</span>
      </span>
      {r.recommendation && <span className="body-s mt-2 block">{r.recommendation}</span>}
    </button>
  )
}

/** Хронология: основная колонка — нить диалога по порядку вопросов (вопрос → нормы → вывод → риск);
 *  уточняющие вопросы уходят вправо ветвлением и не сбивают нумерацию основной цепочки. */
export function TimelineFlow({ sessionId }: { sessionId: string }) {
  const tl = useTimeline(sessionId)
  const msgs = useMessages(sessionId)
  const { selectMessage, selectRisk, sel } = useSelection()
  if (tl.isLoading) return <div className="p-3"><Skeleton lines={4} /></div>
  if (tl.isError) return <div className="p-3"><ErrorNote error={tl.error} onRetry={() => tl.refetch()} /></div>
  const items = tl.data ?? []
  if (!items.length) return <EmptyState title="Хронология пуста">Здесь появятся вопросы сессии по порядку, их основания, выводы и риски.</EmptyState>
  const byMessage = new Map(items.map((it) => [it.message_id, it]))
  const main = items.filter((it) => !it.follow_up_of || !byMessage.has(it.follow_up_of))
  const branches = (parent: TimelineItem) => items.filter((it) => it.follow_up_of && it.follow_up_of === parent.message_id)
  const risksOf = (it: TimelineItem) => it.risks as unknown as TRisk[]
  const hasBranches = main.some((it) => branches(it).length > 0)
  return (
    <div className="h-full overflow-y-auto bg-panel p-4" aria-label="Хронология вопросов">
      <p className="caption mb-3">как разворачивалась консультация: вопрос → нормы → вывод → риск</p>
      <ol className="space-y-0">
        {main.map((it, i) => {
          const side = branches(it)
          return (
            <li key={it.node_id} className={hasBranches ? 'grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)] gap-x-8' : 'max-w-2xl'}>
              <div className="space-y-0">
                {i > 0 && <Arrow />}
                <QuestionCard it={it} active={sel.messageId === it.message_id} onOpen={() => it.message_id && selectMessage(it.message_id)} />
                {(it.norms.length > 0 || conclusionOf(msgs.data, it.message_id)) && <><Arrow /><Bases it={it} conclusion={conclusionOf(msgs.data, it.message_id)} /></>}
                {risksOf(it).map((r) => <div key={r.node_id}><Arrow /><RiskBox r={r} onOpen={() => r.risk_id && selectRisk(r.risk_id)} /></div>)}
              </div>
              {hasBranches && <div className="space-y-3 pt-6">
                {side.map((b) => (
                  <div key={b.node_id} className="relative border-l-2 border-dashed border-line-strong pl-4">
                    <p className="caption mb-2">{b.condition ? `ветка «если ${b.condition}»` : 'уточняющий вопрос'} → к вопросу №{it.seq}</p>
                    <div className="space-y-3">
                      <QuestionCard it={b} active={sel.messageId === b.message_id} onOpen={() => b.message_id && selectMessage(b.message_id)} />
                      {risksOf(b).map((r) => <RiskBox key={r.node_id} r={r} onOpen={() => r.risk_id && selectRisk(r.risk_id)} />)}
                    </div>
                  </div>
                ))}
              </div>}
            </li>
          )
        })}
      </ol>
      <div className="mt-6 flex flex-wrap items-center gap-x-6 gap-y-2 border-t border-line pt-3">
        <span className="caption flex items-center gap-2"><svg width="28" height="4" aria-hidden><line x1="0" y1="2" x2="28" y2="2" stroke="var(--gold)" strokeWidth="2" /></svg>asked_next — следующий вопрос</span>
        <span className="caption flex items-center gap-2"><svg width="28" height="4" aria-hidden><line x1="0" y1="2" x2="28" y2="2" stroke="var(--line-strong)" strokeWidth="2" strokeDasharray="4 3" /></svg>refines — уточнение</span>
      </div>
    </div>
  )
}
