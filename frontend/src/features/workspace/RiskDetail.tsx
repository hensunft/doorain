import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Banner, ErrorNote, Skeleton } from '../../components/States'
import { Button, RiskBadge } from '../../components/ui'
import type { Risk } from '../../lib/api'
import { errorText, patch } from '../../lib/api'
import { keys, useRiskDetail } from '../../lib/queries'
import { STATUS_RU, scoreLabel } from '../../lib/risk'
import { useSelection } from '../../lib/selection'

const EVENT_KIND: Record<string, string> = { created: 'Создан', status: 'Статус', score: 'Оценка', evidence: 'Основание' }
const AUTHOR: Record<string, string> = { system: 'система', user_message: 'по сообщению пользователя', owner: 'владелец' }

export function RiskDetail({ riskId, sessionId }: { riskId: string; sessionId: string }) {
  const q = useRiskDetail(riskId)
  const qc = useQueryClient()
  const { openCitation, selectMessage } = useSelection()
  const [status, setStatus] = useState<'open' | 'in_progress' | 'resolved'>('in_progress')
  const [reason, setReason] = useState('')
  const change = useMutation({
    mutationFn: (v: { status: string; reason: string; version: number }) => patch<Risk>(`/risks/${riskId}`, v),
    onSuccess: () => { setReason(''); void qc.invalidateQueries({ queryKey: keys.risk(riskId) }); void qc.invalidateQueries({ queryKey: keys.risks(sessionId) }); void qc.invalidateQueries({ queryKey: keys.graph(sessionId) }) },
  })
  if (q.isLoading) return <Skeleton lines={6} />
  if (q.isError) return <ErrorNote error={q.error} onRetry={() => q.refetch()} />
  if (!q.data) return null
  const { risk: r, events, evidence } = q.data
  const facts = evidence.filter((e) => e.kind === 'fact')
  const cites = evidence.filter((e) => e.kind === 'obligation' || e.kind === 'consequence')
  const msgs = evidence.filter((e) => e.kind === 'message')
  const bonusFacts = facts.filter((e) => e.role === 'bonus')
  const editable = r.status !== 'needs_clarification'
  return (
    <div className="space-y-4 text-small">
      <header className="space-y-1">
        <h3>{r.title}</h3>
        <div className="flex flex-wrap items-center gap-2">
          <RiskBadge level={r.level} score={r.score} />
          <span className="chip tnum">P{r.p ?? '—'} × S{r.s ?? '—'} = {scoreLabel(r.p, r.s, r.score)}</span>
          <span className="chip">{STATUS_RU[r.status] ?? r.status}</span>
          {r.kind === 'learning' && <span className="chip">Учебный риск</span>}
          {r.category && <span className="chip">{r.category}</span>}
        </div>
        <p className="hint">Оценка качественная (методика {r.methodology_version}, экспериментальная), это не вероятность штрафа в процентах.</p>
      </header>
      {r.status === 'needs_clarification' && <Banner tone="warn">Нужно уточнение: {r.clarification ?? 'недостаточно фактов'}. Строка не входит в ранжированную таблицу.</Banner>}
      {r.resolution_pending && (
        <Banner tone="warn" action={<Button onClick={() => change.mutate({ status: 'resolved', reason: 'Подтверждено владельцем после сообщения о снятии', version: r.version })}>Снять</Button>}>{r.resolution_pending}</Banner>
      )}
      {r.status === 'resolved' && <Banner>{r.resolved_by === 'user_message' ? 'Снят по сообщению пользователя (это не независимая проверка устранения).' : 'Снят вручную.'} Причина: {r.resolution_reason}</Banner>}
      <section><h4 className="font-semibold">Почему такая оценка</h4>
        <p><b>P:</b> {r.p_reason || '—'}{r.bonus_p > 0 && <> Базовая P={r.base_p}; однократный бонус +1 за независимый подтверждающий факт{bonusFacts.length ? `: «${bonusFacts[0]?.label}»` : ''}.</>}</p>
        <p><b>S:</b> {r.s_reason || '—'}</p>
        {r.conditions && <p><b>Условия применимости:</b> {r.conditions}</p>}
      </section>
      <section><h4 className="font-semibold">Нормативное основание</h4>
        <ul className="mt-1 flex flex-wrap gap-1.5">{cites.map((c) => <li key={`${c.kind}${c.ref_id}`}><button type="button" className="chip" onClick={() => c.citation_id && openCitation(c.citation_id)}>{c.kind === 'consequence' ? 'Последствия: ' : ''}{c.label}</button></li>)}</ul>
        {!cites.length && <p className="text-muted">Основание не указано</p>}
      </section>
      <section><h4 className="font-semibold">Последствия</h4><p>{r.consequences || 'Источник последствий не указан'}</p></section>
      <section><h4 className="font-semibold">Рекомендация</h4><p>{r.recommendation || '—'}</p></section>
      <section><h4 className="font-semibold">Подтверждённые факты и вопросы</h4>
        <ul className="list-disc pl-5">{facts.map((f) => <li key={f.ref_id}>{f.label} <span className="text-muted">({f.role === 'bonus' ? 'бонус' : 'основа'})</span></li>)}</ul>
        <ul className="mt-1 flex flex-col gap-1">{msgs.map((m) => <li key={m.ref_id}><button type="button" className="text-left text-muted underline" onClick={() => m.message_id && selectMessage(m.message_id)}>Вопрос: {m.label}</button></li>)}</ul>
      </section>
      <section><h4 className="font-semibold">История</h4>
        <ol className="space-y-1">{events.map((e) => <li key={e.id} className="tnum"><span className="text-muted">{new Date(e.at).toLocaleString('ru-RU')}</span> · {EVENT_KIND[e.kind] ?? e.kind}{e.from_value || e.to_value ? `: ${e.from_value ?? '—'} → ${e.to_value ?? '—'}` : ''} · {e.reason} <span className="text-muted">({AUTHOR[e.author] ?? e.author})</span></li>)}</ol>
      </section>
      {editable && (
        <form className="space-y-2 border-t border-line pt-3" onSubmit={(e) => { e.preventDefault(); change.mutate({ status, reason, version: r.version }) }}>
          <h4 className="font-semibold">Изменить статус</h4>
          <div className="flex flex-wrap gap-2">
            <label className="sr-only" htmlFor={`st-${r.id}`}>Новый статус</label>
            <select id={`st-${r.id}`} className="input !w-40" value={status} onChange={(e) => setStatus(e.target.value as typeof status)}><option value="open">Открыт</option><option value="in_progress">В работе</option><option value="resolved">Снят</option></select>
            <label className="sr-only" htmlFor={`rs-${r.id}`}>Причина</label>
            <input id={`rs-${r.id}`} className="input min-w-48 flex-1" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Причина изменения (обязательно)" required maxLength={1000} />
            <Button variant="primary" type="submit" disabled={!reason.trim() || change.isPending}>Сохранить</Button>
          </div>
          {change.error && <p role="alert" className="text-risk-high">{errorText(change.error)}</p>}
        </form>
      )}
    </div>
  )
}
