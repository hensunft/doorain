import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { EmptyState, ErrorNote, Skeleton } from '../../components/States'
import type { Level, Risk, Session } from '../../lib/api'
import { errorText, patch } from '../../lib/api'
import { keys, useRisks } from '../../lib/queries'
import { levelVar } from '../../lib/risk'
import { useSelection } from '../../lib/selection'

type GroupId = 'now' | 'month' | 'watch'
const GROUPS: { id: GroupId; title: string; hint: string; levels: Level[] }[] = [
  { id: 'now', title: 'Сделать сейчас', hint: 'критические и высокие риски', levels: ['critical', 'high'] },
  { id: 'month', title: 'В ближайший месяц', hint: 'средние риски', levels: ['medium'] },
  { id: 'watch', title: 'Мониторинг', hint: 'низкие и закрытые', levels: ['low'] },
]

function Step({ risk, sessionId }: { risk: Risk; sessionId: string }) {
  const qc = useQueryClient()
  const { selectRisk } = useSelection()
  const [reason, setReason] = useState('')
  const [asking, setAsking] = useState(false)
  const closed = risk.status === 'resolved' || risk.status === 'not_applicable'
  const close = useMutation({
    mutationFn: () => patch<Risk>(`/risks/${risk.id}`, { status: 'resolved', reason, version: risk.version }),
    onSuccess: () => {
      setAsking(false); setReason('')
      void qc.invalidateQueries({ queryKey: keys.risks(sessionId) })
      void qc.invalidateQueries({ queryKey: keys.graph(sessionId) })
    },
  })
  return (
    <li>
      <article className={`card card-risk ${closed ? 'opacity-[0.78]' : ''}`} style={{ ['--level' as string]: levelVar(risk.level) }}>
        <div className="flex items-start gap-3">
          <input
            type="checkbox"
            className="mt-0.5 size-5 shrink-0 accent-[var(--brand)]"
            checked={closed}
            disabled={closed || close.isPending}
            aria-label={`Отметить шаг выполненным: ${risk.recommendation || risk.title}`}
            onChange={() => setAsking(true)}
          />
          <div className="min-w-0 flex-1">
            <h3 className={`body-l font-semibold ${closed ? 'text-muted line-through' : ''}`}>{risk.recommendation || risk.title}</h3>
            {risk.scenario && <p className="body-s mt-1 text-muted">{risk.scenario}</p>}
            <div className="mt-2 flex flex-wrap items-center gap-2">
              {risk.norms.map((n) => <span key={n} className="chip-norm">{n}</span>)}
              <button type="button" className="badge-level" style={{ ['--level' as string]: levelVar(risk.level) }} data-level={risk.level ?? 'none'} onClick={() => selectRisk(risk.id)}>
                {closed ? 'риск закрыт' : `закрывает риск ${risk.score ?? ''}`}
              </button>
            </div>
            {asking && !closed && (
              <form className="mt-2 flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); close.mutate() }}>
                <label className="sr-only" htmlFor={`pl-${risk.id}`}>Что сделано</label>
                <input id={`pl-${risk.id}`} className="input min-w-40 flex-1" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Что сделано (обязательно)" required maxLength={1000} autoFocus />
                <button className="btn btn-primary" type="submit" disabled={!reason.trim() || close.isPending}>Закрыть риск</button>
                <button className="btn" type="button" onClick={() => setAsking(false)}>Отмена</button>
              </form>
            )}
            {close.error && <p role="alert" className="body-s mt-1 text-risk-high">{errorText(close.error)}</p>}
          </div>
        </div>
      </article>
    </li>
  )
}

/** План-схема: открытые риски превращаются в шаги, сгруппированные по срочности.
 *  Отметка шага закрывает риск и перекрашивает граф без перезагрузки. */
export function PlanPanel({ session }: { session: Session }) {
  const risks = useRisks(session.id)
  if (risks.isLoading) return <div className="p-3"><Skeleton lines={5} /></div>
  if (risks.isError) return <div className="p-3"><ErrorNote error={risks.error} onRetry={() => risks.refetch()} /></div>
  const data = risks.data
  if (!data) return null
  const all = [...data.active, ...data.resolved]
  if (!all.length) return <EmptyState title="Плана пока нет">Шаги появятся, когда в сессии будут риски с рекомендациями. Пустой план не означает отсутствие рисков.</EmptyState>
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
        <h2 className="display-s">План-схема</h2>
        <p className="hint mt-1">Рекомендации по открытым рискам превращены в шаги. Закрытие шага высветляет узлы в других режимах.</p>
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
              <span className="inline-block size-2.5 rotate-45" style={{ background: levelVar(g.levels[0] ?? 'low') }} aria-hidden />
              <span className="display-s">{g.title}</span>
              <span className="caption">{g.hint}</span>
            </h3>
            <ul className="space-y-2">{rows.map((r) => <Step key={r.id} risk={r} sessionId={session.id} />)}</ul>
          </section>
        )
      })}
      <p className="caption">Оценка носит информационный характер и не является юридическим заключением.</p>
    </div>
  )
}
