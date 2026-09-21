import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowDown, Loader2, Send, Square } from 'lucide-react'
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react'
import { Link } from 'react-router-dom'
import { Banner, EmptyState, ErrorNote, Skeleton } from '../../components/States'
import { Button } from '../../components/ui'
import type { Message, Session } from '../../lib/api'
import { ApiError, newRequestId, post } from '../../lib/api'
import { useOnline } from '../../lib/hooks'
import { keys, useGraph, useMessages, useRisks, useStatus } from '../../lib/queries'
import { nodesForRisk, riskIdsForNode, useSelection } from '../../lib/selection'
import { useRunStream } from '../../lib/stream'
import { Blocks } from './MessageView'

type RunAccepted = { run_id: string; message_id: string; deduplicated?: boolean }

const EXAMPLES: Record<Session['role'], string[]> = {
  student: ['Что такое персональные данные и чем они отличаются от обычной информации?', 'Кто такой оператор персональных данных?'],
  entrepreneur: ['Нужна ли мне политика обработки персональных данных на сайте?', 'Можно ли собирать e-mail через форму без отдельного согласия?', 'Сервер у нас в Европе — это проблема?'],
  expert: ['Что говорится в статье 18.1 о политике оператора?', 'Какие обязанности оператора установлены при сборе персональных данных?'],
}

const NO_CHIPS: never[] = []

/** Системная врезка: какие риски выросли из этого ответа. Клик открывает риск в таблице. */
function RiskNotes({ session, messageId }: { session: Session; messageId: string }) {
  const risks = useRisks(session.id)
  const graph = useGraph(session.id)
  const { selectRisk } = useSelection()
  const node = graph.data?.nodes.find((n) => n.kind === 'question' && n.data['message_id'] === messageId)
  if (!node || !risks.data) return null
  const ids = riskIdsForNode(graph.data, [...risks.data.active, ...risks.data.resolved], node.id)
  const rows = [...risks.data.active, ...risks.data.resolved].filter((r) => ids.has(r.id))
  if (!rows.length) return null
  return (
    <div className="space-y-1 pt-1">
      {rows.map((r) => (
        <button key={r.id} type="button" className="inline-note" data-level={r.level ?? 'none'} onClick={() => selectRisk(r.id)}>
          Добавлен риск: {r.title}{r.score != null ? ` · ${r.score}` : ''}
        </button>
      ))}
    </div>
  )
}

function RunStream({ runId, session, hideBlocks, onFinished }: { runId: string; session: Session; hideBlocks: boolean; onFinished: () => void }) {
  const qc = useQueryClient()
  const stream = useRunStream(runId, (ev) => {
    if (ev.type === 'portrait_updated') { void qc.invalidateQueries({ queryKey: keys.graph(session.id) }); void qc.invalidateQueries({ queryKey: keys.timeline(session.id) }) }
    if (ev.type === 'risk_updated') void qc.invalidateQueries({ queryKey: keys.risks(session.id) })
    if (ev.type === 'answer_completed') void qc.invalidateQueries({ queryKey: keys.messages(session.id) }) // сохранённый ответ (с источниками) заменяет буфер
    if (ev.type === 'completed' || ev.type === 'failed' || ev.type === 'cancelled') {
      void Promise.all([qc.invalidateQueries({ queryKey: keys.messages(session.id) }), qc.invalidateQueries({ queryKey: keys.session(session.id) }), qc.invalidateQueries({ queryKey: keys.graph(session.id) }), qc.invalidateQueries({ queryKey: keys.risks(session.id) }), qc.invalidateQueries({ queryKey: keys.timeline(session.id) })]).then(onFinished)
    }
  })
  const { openCitation } = useSelection()
  return (
    <div className="space-y-2" aria-busy={!stream.done}>
      {!hideBlocks && stream.blocks.length > 0 && <Blocks blocks={stream.blocks} chips={NO_CHIPS} onCite={openCitation} />}
      {!stream.done && (
        <p className="flex items-center gap-2 text-small text-muted" role="status">
          <Loader2 className="size-4 animate-spin" aria-hidden />
          {stream.provisional && !hideBlocks && stream.blocks.length > 0 ? 'Ответ формируется: проверка ссылок и цитат не завершена…' : (stream.stageMessage ?? 'Обрабатываю запрос…')}
          {stream.connection === 'reconnecting' && ' Соединение восстанавливается…'}
        </p>
      )}
      {stream.analysis === 'running' && !stream.done && <p className="text-small text-muted" role="status">Обновляю слепок и риски…</p>}
      {stream.error && <ErrorNote error={new ApiError(0, 'run', stream.error)} />}
    </div>
  )
}

export function ChatPanel({ session, draft, setDraft }: { session: Session; draft: string; setDraft: (t: string) => void }) {
  const qc = useQueryClient()
  const msgs = useMessages(session.id)
  const status = useStatus()
  const graph = useGraph(session.id)
  const online = useOnline()
  const { sel, selectMessage, openCitation, selectNode, prefill, requestPrefill } = useSelection()
  useEffect(() => {
    if (prefill == null) return
    setDraft(prefill)
    requestPrefill(null)
    document.getElementById('composer')?.focus()
  }, [prefill, requestPrefill, setDraft])
  const [runId, setRunId] = useState<string | null>(null)
  const [retryNonce, setRetryNonce] = useState(0)
  const [sendError, setSendError] = useState<unknown>(null)
  const listRef = useRef<HTMLDivElement>(null)
  const [atBottom, setAtBottom] = useState(true)
  const atBottomRef = useRef(true)

  // Возобновление после перезагрузки: если есть незавершённый run — подписываемся снова.
  useEffect(() => {
    if (runId || !msgs.data) return
    const pending = [...msgs.data].reverse().find((m) => m.role === 'user' && m.run_id && (m.answer_status === 'queued' || m.answer_status === 'running' || m.analysis_status === 'running'))
    if (pending?.run_id) setRunId(pending.run_id)
  }, [msgs.data, runId])

  const send = useMutation({
    mutationFn: (text: string) => post<RunAccepted>(`/sessions/${session.id}/messages`, { text, client_request_id: newRequestId() }),
    onMutate: () => setSendError(null),
    onSuccess: (r) => { setDraft(''); setRunId(r.run_id); void qc.invalidateQueries({ queryKey: keys.messages(session.id) }) },
    onError: (e) => { setSendError(e); if (e instanceof ApiError && e.code === 'run_in_progress') void msgs.refetch() },
  })
  const cancel = useMutation({ mutationFn: () => post(`/runs/${runId}/cancel`) })
  const retry = useMutation({
    mutationFn: (rid: string) => post<RunAccepted>(`/runs/${rid}/analysis/retry`),
    onSuccess: (r) => { setRunId(r.run_id); setRetryNonce((n) => n + 1) },
  })

  const running = !!runId
  const submit = useCallback(() => {
    const t = draft.trim()
    if (!t || running || send.isPending || !online) return
    send.mutate(t)
  }, [draft, running, send, online])
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); submit() }
  }

  // Подсветка сообщений, связанных с выбранным риском/узлом
  const highlightMsgs = useMemo(() => {
    const out = new Set<string>()
    if (!graph.data) return out
    const ids = sel.riskId ? nodesForRisk(graph.data, sel.riskId) : sel.nodeId ? new Set([sel.nodeId]) : new Set<string>()
    for (const n of graph.data.nodes) if (ids.has(n.id) && n.kind === 'question' && n.data['message_id']) out.add(String(n.data['message_id']))
    return out
  }, [graph.data, sel.riskId, sel.nodeId])

  // Прокрутка: не дёргаем вниз, если пользователь читает историю
  const onScroll = () => {
    const el = listRef.current
    if (!el) return
    const near = el.scrollHeight - el.scrollTop - el.clientHeight < 80
    atBottomRef.current = near
    setAtBottom(near)
  }
  useLayoutEffect(() => {
    const el = listRef.current
    if (el && atBottomRef.current) el.scrollTop = el.scrollHeight
  })
  useEffect(() => {
    if (!sel.messageId) return
    listRef.current?.querySelector(`[data-message-id="${sel.messageId}"]`)?.scrollIntoView({ block: 'center', behavior: 'smooth' })
  }, [sel.messageId])
  const toBottom = () => { const el = listRef.current; if (el) { el.scrollTop = el.scrollHeight; atBottomRef.current = true; setAtBottom(true) } }

  const questionNodeOf = (mid: string) => graph.data?.nodes.find((n) => n.kind === 'question' && n.data['message_id'] === mid)
  const rows: Message[] = msgs.data ?? []
  const lastAssistantWithFailedAnalysis = [...rows].reverse().find((m) => m.role === 'assistant' && m.analysis_status === 'failed')
  const modelBad = status.data?.model.state === 'unavailable'

  return (
    <div className="relative flex h-full min-h-0 flex-col">
      <p className="overline px-4 pt-3">Диалог</p>
      <div ref={listRef} onScroll={onScroll} role="log" aria-label="Диалог" aria-live="polite" className="relative min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-3">
        {msgs.isLoading && <Skeleton lines={5} />}
        {msgs.isError && <ErrorNote error={msgs.error} onRetry={() => msgs.refetch()} />}
        {msgs.data && rows.length === 0 && (
          <EmptyState title="Задайте первый вопрос">
            {status.data?.corpus_empty ? <>База знаний пуста, поэтому ответить по источникам нельзя. <Link to="/kb">Загрузите документы</Link>, затем вернитесь к вопросу.</> : 'Ответ будет опираться на источники из базы знаний. Например:'}
            {!status.data?.corpus_empty && <div className="mt-3 flex flex-col gap-2">{EXAMPLES[session.role].map((t) => <button key={t} type="button" className="chip !h-auto justify-start whitespace-normal py-1 text-left" onClick={() => setDraft(t)}>{t}</button>)}</div>}
          </EmptyState>
        )}
        {rows.map((m, i) => {
          const qn = m.role === 'user' ? questionNodeOf(m.id) : undefined
          const askedId = m.role === 'assistant' ? [...rows.slice(0, i)].reverse().find((x) => x.role === 'user')?.id : undefined
          const hl = highlightMsgs.has(m.id) || sel.messageId === m.id
          return (
            <article key={m.id} data-message-id={m.id} className={`space-y-2 rounded-lg ${hl ? 'bg-panel ring-1 ring-gold' : ''}`} aria-label={m.role === 'user' ? 'Сообщение пользователя' : 'Ответ ассистента'}>
              {m.role === 'user' ? (
                <button type="button" onClick={() => { selectMessage(m.id); if (qn) selectNode(qn.id) }} className="bubble-user block w-full cursor-pointer text-left" title="Показать вопрос на карте">
                  <span className="whitespace-pre-wrap break-words">{m.text}</span>
                  {qn?.data['result'] === 'refused' && <span className="chip ml-2">Отказ</span>}
                </button>
              ) : m.blocks ? (
                <div className="bubble-agent space-y-2">
                  <Blocks blocks={m.blocks} chips={m.citations} onCite={openCitation} />
                  {m.answer_status === 'cancelled' && <p className="hint">Генерация остановлена: неполный ответ не используется в слепке и рисках.</p>}
                  {m.warnings.length > 0 && <ul className="hint list-disc pl-5">{m.warnings.map((w) => <li key={w}>{w}</li>)}</ul>}
                  {askedId && <RiskNotes session={session} messageId={askedId} />}
                </div>
              ) : <p className="bubble-agent">{m.text}</p>}
            </article>
          )
        })}
        {runId && <RunStream key={`${runId}:${retryNonce}`} runId={runId} session={session} hideBlocks={rows.some((m) => m.role === 'assistant' && m.run_id === runId)} onFinished={() => setRunId(null)} />}
        {!runId && lastAssistantWithFailedAnalysis?.run_id && (
          <Banner tone="warn" action={<Button onClick={() => retry.mutate(lastAssistantWithFailedAnalysis.run_id as string)} disabled={retry.isPending}>Повторить анализ</Button>}>
            Ответ проверен и сохранён, но слепок и риски по нему не обновлены (analysis failed). Повтор не создаст дублей.
          </Banner>
        )}
      </div>
      {!atBottom && <button type="button" className="btn absolute bottom-28 right-6 shadow-sm" onClick={toBottom}><ArrowDown className="size-4" aria-hidden />Новые сообщения</button>}
      <div className="border-t border-line p-3">
        {modelBad && <div className="mb-2"><Banner tone="warn">Локальная модель сейчас недоступна: {status.data?.model.detail}. Вопрос будет сохранён, но ответ не сформируется. Облачный сервис не используется.</Banner></div>}
        {sendError != null && <div className="mb-2"><ErrorNote error={sendError} /></div>}
        {!online && <p className="mb-2 text-small text-risk-medium">Нет интернета — отправка отключена, введённый текст сохранён.</p>}
        <div className="flex items-end gap-2">
          <label className="sr-only" htmlFor="composer">Ваш вопрос</label>
          <textarea id="composer" className="input max-h-40 min-h-[44px] resize-none" rows={2} maxLength={4000} value={draft} onChange={(e) => setDraft(e.target.value)} onKeyDown={onKey} placeholder="Задайте вопрос по IT-праву…" title="Enter — отправить, Shift+Enter — перенос строки" disabled={session.status !== 'active'} />
          {running ? (
            <Button variant="primary" className="h-11" onClick={() => cancel.mutate()} disabled={cancel.isPending} aria-label="Остановить генерацию"><Square className="size-4" aria-hidden />Стоп</Button>
          ) : (
            <Button variant="primary" className="h-11" onClick={submit} disabled={!draft.trim() || send.isPending || !online || session.status !== 'active'} aria-label="Отправить"><Send className="size-4" aria-hidden />Отправить</Button>
          )}
        </div>
        {(session.status !== 'active' || draft.length > 3500) && <p className="mt-1 text-xs text-muted">{session.status !== 'active' ? 'Сессия в архиве' : `${draft.length}/4000`}</p>}
      </div>
    </div>
  )
}

