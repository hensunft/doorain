import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Banner, ErrorNote, Skeleton } from '../../components/States'
import { Button, RiskBadge } from '../../components/ui'
import type { Risk } from '../../lib/api'
import { errorText, patch } from '../../lib/api'
import { keys, useRiskDetail } from '../../lib/queries'
import { useMe } from '../../app/App'
import { RESOLVED_BY_RU, STATUS_RU, scoreLabel } from '../../lib/risk'
import { PsInfo } from '../../components/PsInfo'
import { ClosureForm, VERIFICATION_RU } from './Closure'
import { useSelection } from '../../lib/selection'

const EVENT_KIND: Record<string, string> = { created: 'Создан', status: 'Статус', score: 'Оценка', evidence: 'Основание', closure: 'Проверка закрытия' }
const AUTHOR: Record<string, string> = { system: 'система', user_message: 'по сообщению пользователя', owner: 'владелец', closure_user_claim: 'проверка ответа · со слов пользователя', closure_confirmed: 'проверка ответа · подтверждено фактами', owner_override: 'владелец без проверки' }
const DECISION_RU: Record<string, string> = { close: 'Закрыт', keep_open: 'Остаётся открытым', clarify: 'Нужно уточнение', other_risk: 'Описана другая проблема' }

export function RiskDetail({ riskId, sessionId }: { riskId: string; sessionId: string }) {
  const q = useRiskDetail(riskId)
  const qc = useQueryClient()
  const { openCitation, selectMessage } = useSelection()
  const isOwner = useMe().data?.user.access_level === 'owner'
  const [status, setStatus] = useState<'open' | 'in_progress'>('in_progress')
  const [override, setOverride] = useState('')
  const [reason, setReason] = useState('')
  const change = useMutation({
    mutationFn: (v: { status: string; reason: string; version: number; override?: boolean }) => patch<Risk>(`/risks/${riskId}`, v),
    onSuccess: () => { setReason(''); setOverride(''); void qc.invalidateQueries({ queryKey: keys.risk(riskId) }); void qc.invalidateQueries({ queryKey: keys.risks(sessionId) }); void qc.invalidateQueries({ queryKey: keys.graph(sessionId) }) },
  })
  const [ps, setPs] = useState<{ p: number; s: number; reason: string } | null>(null)
  const rescore = useMutation({
    mutationFn: (v: { p: number; s: number; reason: string; version: number }) => patch<Risk>(`/risks/${riskId}`, v),
    onSuccess: () => { setPs(null); void qc.invalidateQueries({ queryKey: keys.risk(riskId) }); void qc.invalidateQueries({ queryKey: keys.risks(sessionId) }); void qc.invalidateQueries({ queryKey: keys.graph(sessionId) }) },
  })
  if (q.isLoading) return <Skeleton lines={6} />
  if (q.isError) return <ErrorNote error={q.error} onRetry={() => q.refetch()} />
  if (!q.data) return null
  const { risk: r, events, evidence, closures = [] } = q.data
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
          <span className="inline-flex items-center">P<PsInfo what="p" sessionId={sessionId} />S<PsInfo what="s" sessionId={sessionId} /></span>
          <span className="chip">{STATUS_RU[r.status] ?? r.status}</span>
          {r.kind === 'learning' && <span className="chip">Учебный риск</span>}
          {r.category && <span className="chip">{r.category}</span>}
        </div>
        <p className="hint">Оценка качественная (методика {r.methodology_version}, экспериментальная), это не вероятность штрафа в процентах.{r.mentions > 1 ? ` Упоминался в ${r.mentions} сообщениях, обновлён ${new Date(r.updated_at).toLocaleDateString('ru-RU')}.` : ''}</p>
      </header>
      {r.status === 'needs_clarification' && <Banner tone="warn">Нужно уточнение: {r.clarification ?? 'недостаточно фактов'}. Строка не входит в ранжированную таблицу.</Banner>}
      {r.resolution_pending && <Banner tone="warn"><b>Чтобы закрыть риск, уточните:</b> {r.resolution_pending}</Banner>}
      {(r.status === 'resolved' || r.status === 'not_applicable') && <Banner>{RESOLVED_BY_RU[r.resolved_by ?? ''] ?? 'Закрыт.'}{r.resolution_reason ? <>. Ответ: «{r.resolution_reason}»</> : null}</Banner>}
      <section><h4 className="font-semibold">Почему такая оценка</h4>
        <p><b>P:</b> {r.p_reason || '—'}{r.bonus_p > 0 && <> Базовая P={r.base_p}; однократный бонус +1 за независимый подтверждающий факт{bonusFacts.length ? `: «${bonusFacts[0]?.label}»` : ''}.</>}</p>
        <p><b>S:</b> {r.s_reason || '—'}</p>
        {r.conditions && <p><b>Условия применимости:</b> {r.conditions}</p>}
      </section>
      {r.status !== 'needs_clarification' && (
        <section>
          {!ps ? (
            <button type="button" className="btn" onClick={() => setPs({ p: r.p ?? 3, s: r.s ?? 3, reason: '' })}>Изменить оценку P и S</button>
          ) : (
            <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); rescore.mutate({ ...ps, version: r.version }) }}>
              <label className="block"><span className="label">P <PsInfo what="p" sessionId={sessionId} /></span><select className="input !w-20" value={ps.p} onChange={(e) => setPs({ ...ps, p: Number(e.target.value) })}>{[1, 2, 3, 4, 5].map((x) => <option key={x}>{x}</option>)}</select></label>
              <label className="block"><span className="label">S <PsInfo what="s" sessionId={sessionId} /></span><select className="input !w-20" value={ps.s} onChange={(e) => setPs({ ...ps, s: Number(e.target.value) })}>{[1, 2, 3, 4, 5].map((x) => <option key={x}>{x}</option>)}</select></label>
              <label className="block min-w-40 flex-1"><span className="label">Почему</span><input className="input" required maxLength={1000} value={ps.reason} onChange={(e) => setPs({ ...ps, reason: e.target.value })} /></label>
              <button className="btn" type="submit" disabled={!ps.reason.trim() || rescore.isPending}>Сохранить</button>
              <button className="btn" type="button" onClick={() => setPs(null)}>Отмена</button>
            </form>
          )}
          <p className="hint mt-1">{r.manual_ps ? 'Оценка задана вами: агент её не перезаписывает, а при расхождении предлагает уточнение.' : 'После ручной правки агент перестанет менять P и S автоматически.'}</p>
          {rescore.error && <p role="alert" className="text-risk-high">{errorText(rescore.error)}</p>}
        </section>
      )}
      <section><h4 className="font-semibold">Нормативное основание</h4>
        <ul className="mt-1 flex flex-wrap gap-1.5">{cites.map((c) => <li key={`${c.kind}${c.ref_id}`}><button type="button" className="chip" onClick={() => c.citation_id && openCitation(c.citation_id)}>{c.kind === 'consequence' ? 'Последствия: ' : ''}{c.label}</button></li>)}</ul>
        {!cites.length && <p className="text-muted">Основание не указано</p>}
      </section>
      <section><h4 className="font-semibold">Последствия</h4><p>{r.consequences || 'Источник последствий не указан'}</p></section>
      <section><h4 className="font-semibold">Рекомендация</h4><p>{r.recommendation || '—'}</p></section>
      <section><h4 className="font-semibold">Подтверждённые факты и вопросы</h4>
        <ul className="list-disc pl-5">{facts.map((f) => <li key={f.ref_id}>{f.label} <span className="text-muted">({f.role === 'bonus' ? 'бонус' : 'основа'})</span></li>)}</ul>
        <ul className="mt-1 flex flex-col gap-1">{msgs.map((m) => <li key={m.ref_id}><button type="button" className="btn btn-tertiary h-auto !justify-start whitespace-normal !px-0 text-left" onClick={() => m.message_id && selectMessage(m.message_id)}>Вопрос: {m.label}</button></li>)}</ul>
      </section>
      <section><h4 className="font-semibold">История</h4>
        <ol className="space-y-1">{events.map((e) => <li key={e.id} className="tnum"><span className="text-muted">{new Date(e.at).toLocaleString('ru-RU')}</span> · {EVENT_KIND[e.kind] ?? e.kind}{e.to_value ? `: ${STATUS_RU[e.to_value] ?? e.to_value}` : ''}{e.from_value ? ` (было: ${STATUS_RU[e.from_value] ?? e.from_value})` : ''} · {e.reason} <span className="text-muted">({AUTHOR[e.author] ?? e.author})</span></li>)}</ol>
      </section>
      {closures.length > 0 && (
        <section><h4 className="font-semibold">Проверки ответа о закрытии</h4>
          <ol className="mt-1 space-y-2">{closures.map((a) => (
            <li key={a.id}>
              <span className="text-muted tnum">{new Date(a.created_at).toLocaleString('ru-RU')}</span> · «{a.user_answer.slice(0, 120)}»
              <span className="block"><b>{a.state === 'decided' ? DECISION_RU[a.decision ?? ''] ?? a.decision : a.state === 'failed' ? 'Проверка не выполнена' : 'Не применено'}</b>{a.verification ? ` — ${VERIFICATION_RU[a.verification]}` : ''}{a.decision === 'clarify' && a.question ? `. ${a.question}` : ''}</span>
            </li>
          ))}</ol>
        </section>
      )}
      {editable && r.status !== 'resolved' && r.status !== 'not_applicable' && (
        <section className="space-y-1 border-t border-line pt-3">
          <h4 className="font-semibold">Закрыть риск</h4>
          <ClosureForm key={r.version} risk={r} sessionId={sessionId} source="detail" />
        </section>
      )}
      {isOwner && editable && r.status !== 'resolved' && r.status !== 'not_applicable' && (
        <details className="text-small">
          <summary className="cursor-pointer text-muted">Административно: закрыть без проверки ответа</summary>
          <form className="mt-2 flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); change.mutate({ status: 'resolved', reason: override, version: r.version, override: true }) }}>
            <label className="sr-only" htmlFor={`ov-${r.id}`}>Основание административного закрытия</label>
            <input id={`ov-${r.id}`} className="input min-w-48 flex-1" value={override} onChange={(e) => setOverride(e.target.value)} placeholder="Основание (записывается в журнал)" required maxLength={1000} />
            <Button type="submit" variant="danger" disabled={!override.trim() || change.isPending}>Закрыть без проверки</Button>
          </form>
        </details>
      )}
      {editable && (
        <form className="space-y-2 border-t border-line pt-3" onSubmit={(e) => { e.preventDefault(); change.mutate({ status, reason, version: r.version }) }}>
          <h4 className="font-semibold">Изменить статус</h4>
          <div className="flex flex-wrap gap-2">
            <label className="sr-only" htmlFor={`st-${r.id}`}>Новый статус</label>
            <select id={`st-${r.id}`} className="input !w-40" value={status} onChange={(e) => setStatus(e.target.value as typeof status)}><option value="open">Открыт</option><option value="in_progress">В работе</option></select>
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
