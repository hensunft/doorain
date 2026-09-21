import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { ErrorNote } from '../../components/States'
import type { Risk } from '../../lib/api'
import { errorText, patch, post } from '../../lib/api'
import { keys } from '../../lib/queries'
import { LEVEL_RU, STATUS_RU } from '../../lib/risk'

type Next = 'open' | 'in_progress' | 'resolved' | 'dismissed'
const FLOW: { id: Next; label: string }[] = [
  { id: 'open', label: 'Открыт' },
  { id: 'in_progress', label: 'В работе' },
  { id: 'resolved', label: 'Закрыт' },
]

/** Карточка риска: полоса уровня слева, бейдж P × S справа, основание моноширинным, переключатель статуса.
 *  Свёрнута по умолчанию — разворачивается кликом; закрытый риск приглушается и уходит в конец списка. */
export function RiskCard({ risk, sessionId, questions, expanded, selected, highlighted, dim = false, onHover, onToggle, children }: {
  risk: Risk
  sessionId: string
  questions: number[]
  expanded: boolean
  selected: boolean
  highlighted: boolean
  dim?: boolean
  onHover?: (on: boolean) => void
  onToggle: () => void
  children?: React.ReactNode
}) {
  const qc = useQueryClient()
  const [reason, setReason] = useState('')
  const [ask, setAsk] = useState<null | Next>(null)
  const change = useMutation({
    mutationFn: (v: { status: string; reason: string }) => patch<Risk>(`/risks/${risk.id}`, { ...v, version: risk.version }),
    onSuccess: () => {
      setAsk(null); setReason('')
      void qc.invalidateQueries({ queryKey: keys.risks(sessionId) })
      void qc.invalidateQueries({ queryKey: keys.graph(sessionId) })
      void qc.invalidateQueries({ queryKey: keys.risk(risk.id) })
    },
  })
  const decide = useMutation({
    mutationFn: (d: 'accept' | 'reject') => post<Risk>(`/risks/${risk.id}/suggestion/${d}`),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: keys.risks(sessionId) }); void qc.invalidateQueries({ queryKey: keys.graph(sessionId) }) },
  })
  const sug = risk.pending_suggestion as { p?: number; s?: number; reason?: string } | null | undefined
  const closed = risk.status === 'resolved' || risk.status === 'not_applicable'
  const basis = [risk.norms.join(' · '), questions.length ? `${questions.length > 1 ? 'вопросы' : 'вопрос'} ${questions.map((n) => `№${n}`).join(', ')}` : '']
    .filter(Boolean).join(' · ')
  return (
    <article
      className={`card card-risk transition-opacity ${selected ? 'ring-1 ring-gold' : highlighted ? 'ring-1 ring-line-strong' : ''}`}
      data-level={risk.level ?? 'none'}
      data-closed={closed}
      data-dim={dim}
      onMouseEnter={() => onHover?.(true)}
      onMouseLeave={() => onHover?.(false)}
      aria-label={`Риск: ${risk.title}`}
    >
      <button type="button" className="flex min-h-11 w-full items-start justify-between gap-3 text-left" aria-expanded={expanded} onClick={onToggle}>
        <span className="min-w-0">
          <h3 className={`body-l font-semibold ${closed ? 'text-muted line-through' : ''}`}>{risk.title}</h3>
          {/* Уровень дублируется словом и числом: цвет не единственный носитель смысла. */}
          <span className="caption mt-0.5 block">
            {risk.level ? `${LEVEL_RU[risk.level]} · P${risk.p} × S${risk.s} = ${risk.score}` : 'Не оценён'} · {STATUS_RU[risk.status] ?? risk.status}
          </span>
        </span>
        {closed ? (
          <span className="chip risk-low shrink-0">закрыт</span>
        ) : (
          <span className="badge-level shrink-0" data-level={risk.level ?? 'none'} title={`P${risk.p} × S${risk.s} — ${risk.level ? LEVEL_RU[risk.level].toLowerCase() : 'не оценён'}`}>
            {risk.score ?? '—'}
          </span>
        )}
      </button>
      <p className="mono-m mt-1 text-muted">{basis || (risk.origin === 'user' ? 'основание не указано · добавлен вами' : 'основание не указано')}</p>
      {risk.origin === 'user' && basis && <p className="caption">добавлен вами</p>}
      {sug && !closed && (
        <div className="mt-2 flex flex-wrap items-center gap-2 rounded-md bg-gold-tint px-2 py-1.5">
          <span className="chip border-gold">есть уточнение</span>
          <span className="body-s">Агент оценил P{sug.p} × S{sug.s}{sug.reason ? `: ${sug.reason}` : ''}. Ваша оценка сохранена.</span>
          <button type="button" className="btn" disabled={decide.isPending} onClick={() => decide.mutate('accept')}>Принять</button>
          <button type="button" className="btn btn-tertiary" disabled={decide.isPending} onClick={() => decide.mutate('reject')}>Отклонить</button>
        </div>
      )}
      {expanded && (
        <>
          {risk.recommendation && <p className="body-s mt-2">{risk.recommendation}</p>}
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <div className="seg" role="group" aria-label="Статус риска">
              {FLOW.map((s) => (
                <button key={s.id} type="button" className="seg-item" aria-pressed={risk.status === s.id} disabled={change.isPending} onClick={() => (risk.status === s.id ? undefined : setAsk(s.id))}>{s.label}</button>
              ))}
            </div>
            {risk.status !== 'not_applicable' && <button type="button" className="btn btn-tertiary body-s" onClick={() => setAsk('dismissed')}>Неприменимо ко мне</button>}
          </div>
          {ask && (
            <form className="mt-2 flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); change.mutate({ status: ask, reason }) }}>
              <label className="sr-only" htmlFor={`rs-${risk.id}`}>Причина изменения статуса</label>
              <input id={`rs-${risk.id}`} className="input min-w-40 flex-1" value={reason} onChange={(e) => setReason(e.target.value)} placeholder={ask === 'dismissed' ? 'Почему неприменимо (обязательно)' : 'Причина (обязательно)'} required maxLength={1000} autoFocus />
              <button className="btn" type="submit" disabled={!reason.trim() || change.isPending}>Сохранить</button>
              <button className="btn" type="button" onClick={() => setAsk(null)}>Отмена</button>
            </form>
          )}
          {change.error && <p role="alert" className="body-s mt-1 text-risk-high">{errorText(change.error)}</p>}
          {children}
        </>
      )}
      {change.error && !expanded && <ErrorNote error={change.error} />}
    </article>
  )
}
