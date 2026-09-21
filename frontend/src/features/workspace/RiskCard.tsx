import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { ErrorNote } from '../../components/States'
import type { Risk } from '../../lib/api'
import { errorText, patch } from '../../lib/api'
import { keys } from '../../lib/queries'
import { LEVEL_RU, levelVar, STATUS_RU } from '../../lib/risk'

const FLOW: { id: 'open' | 'in_progress' | 'resolved'; label: string }[] = [
  { id: 'open', label: 'Открыт' },
  { id: 'in_progress', label: 'В работе' },
  { id: 'resolved', label: 'Закрыт' },
]

/** Карточка риска: полоса уровня слева, бейдж P × S справа, основание моноширинным, переключатель статуса.
 *  Свёрнута по умолчанию — разворачивается кликом; закрытый риск приглушается и уходит в конец списка. */
export function RiskCard({ risk, sessionId, questions, expanded, selected, highlighted, onToggle, children }: {
  risk: Risk
  sessionId: string
  questions: number[]
  expanded: boolean
  selected: boolean
  highlighted: boolean
  onToggle: () => void
  children?: React.ReactNode
}) {
  const qc = useQueryClient()
  const [reason, setReason] = useState('')
  const [ask, setAsk] = useState<null | 'open' | 'in_progress' | 'resolved'>(null)
  const change = useMutation({
    mutationFn: (v: { status: string; reason: string }) => patch<Risk>(`/risks/${risk.id}`, { ...v, version: risk.version }),
    onSuccess: () => {
      setAsk(null); setReason('')
      void qc.invalidateQueries({ queryKey: keys.risks(sessionId) })
      void qc.invalidateQueries({ queryKey: keys.graph(sessionId) })
      void qc.invalidateQueries({ queryKey: keys.risk(risk.id) })
    },
  })
  const closed = risk.status === 'resolved' || risk.status === 'not_applicable'
  const level = levelVar(risk.level)
  const basis = [risk.norms.join(' · '), questions.length ? `${questions.length > 1 ? 'вопросы' : 'вопрос'} ${questions.map((n) => `№${n}`).join(', ')}` : '']
    .filter(Boolean).join(' · ')
  return (
    <article
      className={`card card-risk transition-opacity ${closed ? 'opacity-[0.78]' : ''} ${selected ? 'ring-1 ring-gold' : highlighted ? 'ring-1 ring-line-strong' : ''}`}
      style={{ ['--level' as string]: level }}
      aria-label={`Риск: ${risk.title}`}
    >
      <button type="button" className="flex w-full items-start justify-between gap-3 text-left" aria-expanded={expanded} onClick={onToggle}>
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
          <span className="badge-level shrink-0" style={{ ['--level' as string]: level }} data-level={risk.level ?? 'none'} title={`P${risk.p} × S${risk.s} — ${risk.level ? LEVEL_RU[risk.level].toLowerCase() : 'не оценён'}`}>
            {risk.score ?? '—'}
          </span>
        )}
      </button>
      <p className="mono-m mt-1 text-muted">{basis || 'основание не указано'}</p>
      {expanded && (
        <>
          {risk.recommendation && <p className="body-s mt-2">{risk.recommendation}</p>}
          <div className="seg mt-3" role="group" aria-label="Статус риска">
            {FLOW.map((s) => (
              <button key={s.id} type="button" className="seg-item" aria-pressed={risk.status === s.id} disabled={change.isPending} onClick={() => (risk.status === s.id ? undefined : setAsk(s.id))}>{s.label}</button>
            ))}
          </div>
          {ask && (
            <form className="mt-2 flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); change.mutate({ status: ask, reason }) }}>
              <label className="sr-only" htmlFor={`rs-${risk.id}`}>Причина изменения статуса</label>
              <input id={`rs-${risk.id}`} className="input min-w-40 flex-1" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Причина (обязательно)" required maxLength={1000} autoFocus />
              <button className="btn btn-primary" type="submit" disabled={!reason.trim() || change.isPending}>Сохранить</button>
              <button className="btn" type="button" onClick={() => setAsk(null)}>Отмена</button>
            </form>
          )}
          {change.error && <p role="alert" className="body-s mt-1 text-risk-high">{errorText(change.error)}</p>}
          {children}
          <p className="caption mt-2">Оценка носит информационный характер и не является юридическим заключением.</p>
        </>
      )}
      {change.error && !expanded && <ErrorNote error={change.error} />}
    </article>
  )
}
