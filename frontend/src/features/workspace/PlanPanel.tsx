import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { EmptyState, ErrorNote, Skeleton } from '../../components/States'
import type { Level, PlanStep, Risk, Session } from '../../lib/api'
import { del, errorText, get, patch, post } from '../../lib/api'
import { useLayoutMode } from '../../lib/hooks'
import { keys, useRisks } from '../../lib/queries'
import { LEVEL_RU, RESOLVED_BY_RU } from '../../lib/risk'
import { ClosureForm } from './Closure'
import { useSelection } from '../../lib/selection'

type GroupId = 'now' | 'month' | 'watch'
const GROUPS: { id: GroupId; title: string; hint: string; levels: Level[] }[] = [
  { id: 'now', title: 'Сделать сейчас', hint: 'критические и высокие риски', levels: ['critical', 'high'] },
  { id: 'month', title: 'В ближайший месяц', hint: 'средние риски', levels: ['medium'] },
  { id: 'watch', title: 'Мониторинг', hint: 'низкие и закрытые', levels: ['low'] },
]

function Step({ risk, sessionId }: { risk: Risk; sessionId: string }) {
  const { selectRisk } = useSelection()
  const [asking, setAsking] = useState(false)
  const closed = risk.status === 'resolved' || risk.status === 'not_applicable'
  return (
    <li>
      <article className={`card card-risk ${closed ? 'opacity-[0.78]' : ''}`} data-level={risk.level ?? 'none'}>
        <div className="flex items-start gap-3">
          <label className="-m-3 flex shrink-0 cursor-pointer p-3"><input
            type="checkbox"
            className="size-5 accent-[var(--brand)]"
            checked={closed}
            disabled={closed || asking}
            aria-label={`Отметить шаг выполненным: ${risk.recommendation || risk.title}`}
            onChange={() => setAsking(true)}
          /></label>
          <div className="min-w-0 flex-1">
            <h3 className={`body-l font-semibold ${closed ? 'text-muted line-through' : ''}`}>{risk.recommendation || risk.title}</h3>
            {risk.scenario && <p className="body-s mt-1 text-muted">{risk.scenario}</p>}
            <div className="mt-2 flex flex-wrap items-center gap-2">
              {risk.norms.map((n) => <span key={n} className="chip-norm">{n}</span>)}
              <button type="button" className="badge-level" data-level={risk.level ?? 'none'} onClick={() => selectRisk(risk.id)}>
                {closed ? 'риск закрыт' : risk.level ? `${LEVEL_RU[risk.level]} · P×S = ${risk.score}` : 'не оценён'}
              </button>
            </div>
            {closed && risk.resolved_by && <p className="caption mt-1">{RESOLVED_BY_RU[risk.resolved_by] ?? 'закрыт'}</p>}
            {asking && !closed && <ClosureForm risk={risk} sessionId={sessionId} source="plan" onCancel={() => setAsking(false)} />}
          </div>
        </div>
      </article>
    </li>
  )
}

/** Свои шаги пользователя: хранятся в сессии, не связаны с рисками и не меняют их статус. */
function OwnSteps({ sessionId }: { sessionId: string }) {
  const qc = useQueryClient()
  const key = [...keys.risks(sessionId), 'steps']
  const q = useQuery({ queryKey: key, queryFn: () => get<PlanStep[]>(`/sessions/${sessionId}/plan/steps`) })
  const [title, setTitle] = useState('')
  const [due, setDue] = useState('')
  const done = () => void qc.invalidateQueries({ queryKey: key })
  const add = useMutation({ mutationFn: () => post<PlanStep>(`/sessions/${sessionId}/plan/steps`, { title, due: due || null }), onSuccess: () => { setTitle(''); setDue(''); done() } })
  const toggle = useMutation({ mutationFn: (s: PlanStep) => patch<PlanStep>(`/sessions/${sessionId}/plan/steps/${s.id}`, { done: !s.done }), onSuccess: done })
  const drop = useMutation({ mutationFn: (s: PlanStep) => del(`/sessions/${sessionId}/plan/steps/${s.id}`), onSuccess: done })
  const err = add.error ?? toggle.error ?? drop.error
  return (
    <section aria-labelledby="pl-own" className="space-y-2">
      <h3 id="pl-own" className="display-s">Свои шаги</h3>
      <ul className="space-y-2">
        {(q.data ?? []).map((s) => (
          <li key={s.id} className="card flex items-start gap-3 border-dashed">
            <label className="-m-3 flex shrink-0 cursor-pointer p-3"><input type="checkbox" className="size-5 accent-[var(--brand)]" checked={s.done} disabled={toggle.isPending} onChange={() => toggle.mutate(s)} aria-label={`Выполнено: ${s.title}`} /></label>
            <div className="min-w-0 flex-1">
              <p className={`body-l font-semibold ${s.done ? 'text-muted line-through' : ''}`}>{s.title}</p>
              <p className="caption">шаг добавлен вами{s.due ? ` · до ${new Date(s.due).toLocaleDateString('ru-RU')}` : ''}</p>
            </div>
            <button type="button" className="btn btn-tertiary" onClick={() => drop.mutate(s)} aria-label={`Удалить шаг: ${s.title}`}>Удалить</button>
          </li>
        ))}
      </ul>
      <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); add.mutate() }}>
        <label className="min-w-48 flex-1"><span className="label">Добавить свой шаг</span><input className="input" value={title} onChange={(e) => setTitle(e.target.value)} minLength={2} maxLength={300} placeholder="Например: запросить у подрядчика акт передачи прав" /></label>
        <label><span className="label">Срок</span><input type="date" className="input" value={due} onChange={(e) => setDue(e.target.value)} /></label>
        <button className="btn" type="submit" disabled={title.trim().length < 2 || add.isPending}>Добавить</button>
      </form>
      {err && <p role="alert" className="body-s text-risk-high">{errorText(err)}</p>}
    </section>
  )
}

/** План-схема: открытые риски превращаются в шаги, сгруппированные по срочности.
 *  Отметка шага закрывает риск и перекрашивает граф без перезагрузки. */
export function PlanPanel({ session }: { session: Session }) {
  const risks = useRisks(session.id)
  const mode = useLayoutMode()
  if (risks.isLoading) return <div className="p-3"><Skeleton lines={5} /></div>
  if (risks.isError) return <div className="p-3"><ErrorNote error={risks.error} onRetry={() => risks.refetch()} /></div>
  const data = risks.data
  if (!data) return null
  const all = [...data.active, ...data.resolved]
  if (!all.length) return <div className="min-h-0 space-y-4 overflow-y-auto p-3"><EmptyState title="Плана пока нет">Шаги появятся, когда в сессии будут риски с рекомендациями. Пустой план не означает отсутствие рисков.</EmptyState><OwnSteps sessionId={session.id} /></div>
  const closed = data.resolved.length
  const critical = data.active.filter((r) => r.level === 'critical').length
  const pct = Math.round((closed / all.length) * 100)
  const inGroup = (g: (typeof GROUPS)[number]) =>
    g.id === 'watch'
      ? all.filter((r) => r.level === 'low' || r.status === 'resolved' || r.status === 'not_applicable')
      : data.active.filter((r) => r.level && g.levels.includes(r.level))
  return (
    <div className="min-h-0 space-y-4 overflow-y-auto p-3">
      <header>
        <div className="flex items-center justify-between gap-2">
          <h2 className="display-s">План-схема</h2>
          <a className="btn no-underline" href={`/api/v1/sessions/${session.id}/risks/export?format=md`} download>Выгрузить чек-лист</a>
        </div>
      </header>
      <div className="card">
        <div className="flex items-baseline justify-between gap-3">
          <p className="body-l font-semibold">Закрыто {closed} из {all.length} рисков{critical ? ` · ${critical} критических остаются` : ''}</p>
          <p className="mono-l">{pct}%</p>
        </div>
        <div className="mt-2 h-2 overflow-hidden rounded-full bg-sidebar" role="img" aria-label={`Прогресс: закрыто ${closed} из ${all.length}`}>
          <div className="h-full" style={{ width: `${pct}%`, background: 'var(--risk-low)', transition: 'width var(--t-risk) var(--ease)' }} />
        </div>
      </div>
      {GROUPS.map((g) => {
        const rows = inGroup(g)
        if (!rows.length) return null
        return (
          <section key={g.id} aria-labelledby={`pl-${g.id}`} className="space-y-2">
            <h3 id={`pl-${g.id}`} className="flex items-center gap-2">
              <span className="inline-block size-2.5 rotate-45 bg-[var(--level)]" data-level={g.levels[0] ?? 'low'} aria-hidden />
              <span className="display-s">{g.title}</span>
              <span className="caption">{g.hint}</span>
            </h3>
            <ul className="space-y-2">{rows.map((r) => <Step key={r.id} risk={r} sessionId={session.id} />)}</ul>
          </section>
        )
      })}
      <OwnSteps sessionId={session.id} />
      {mode !== 'wide' && <p className="caption">Оценка носит информационный характер и не является юридическим заключением.</p>}
    </div>
  )
}
