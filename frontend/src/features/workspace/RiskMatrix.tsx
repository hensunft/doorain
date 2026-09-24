import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { ErrorNote, Skeleton } from '../../components/States'
import type { components } from '../../lib/api-types'
import type { Level, Risk } from '../../lib/api'
import { get } from '../../lib/api'
import { keys } from '../../lib/queries'
import { LEVEL_ORDER, LEVEL_RU, STATUS_RU } from '../../lib/risk'
import { useSelection } from '../../lib/selection'
import { PsInfo } from '../../components/PsInfo'

type Cell = components['schemas']['MatrixCell']

/** Диапазоны уровней из порогов сервера (app/config/risk.yaml): подписи легенды не расходятся с раскраской. */
export function levelRanges(t: number[]): Record<Level, string> {
  const [a = 4, b = 9, c = 15] = t
  return { low: `1–${a}`, medium: `${a + 1}–${b}`, high: `${b + 1}–${c}`, critical: `${c + 1}–25` }
}

/** Матрица 5 × 5. Ячейка окрашена уровнем своих координат (P × S): пустая — тинт, с открытыми рисками — насыщенная
 *  заливка; в ячейке только число открытых рисков. Уровень дублируется штриховкой и легендой — читается в ч/б печати.
 *  Клик раскрывает риски ячейки; наведение подсвечивает их узлы в графе и карточки в списке. */
export function RiskMatrix({ sessionId, risks, thresholds }: { sessionId: string; risks: Risk[]; thresholds: number[] }) {
  const q = useQuery({ queryKey: [...keys.risks(sessionId), 'matrix'], queryFn: () => get<Cell[]>(`/sessions/${sessionId}/risks/matrix`) })
  const { hoverRisks, setHoverRisks, selectRisk } = useSelection()
  const [open, setOpen] = useState<{ p: number; s: number } | null>(null)
  if (q.isLoading) return <Skeleton lines={5} />
  if (q.isError) return <ErrorNote error={q.error} onRetry={() => q.refetch()} />
  const cells = q.data ?? []
  const total = cells.reduce((n, c) => n + c.count, 0)
  const byId = new Map(risks.map((r) => [r.id, r]))
  const picked = open ? cells.find((c) => c.p === open.p && c.s === open.s) : undefined
  const ranges = levelRanges(thresholds)
  return (
    <figure className="mx-auto max-w-sm space-y-3">
      <p className="caption flex flex-wrap items-center gap-x-1">P — вероятность<PsInfo what="p" sessionId={sessionId} /> · S — последствия<PsInfo what="s" sessionId={sessionId} /></p>
      <div className="grid grid-cols-[1.25rem_auto_repeat(5,minmax(0,1fr))] gap-1" role="grid" aria-label={`Матрица рисков 5 × 5, открытых рисков: ${total}`}>
        <span className="caption row-span-5 flex items-center justify-center [writing-mode:vertical-rl] rotate-180" aria-hidden>вероятность (P)</span>
        {[5, 4, 3, 2, 1].map((p) => (
          <div key={p} role="row" className="contents">
            <span className="mono-m flex items-center justify-end pr-1 text-muted" role="rowheader">{p}</span>
            {[1, 2, 3, 4, 5].map((s) => {
              const c = cells.find((x) => x.p === p && x.s === s)
              if (!c) return <span key={s} />
              const ids = c.risks.map((r) => r.id)
              const hot = !!hoverRisks?.some((id) => ids.includes(id))
              const isOpen = open?.p === p && open.s === s
              return (
                <button
                  key={s}
                  type="button"
                  role="gridcell"
                  className="mx-cell"
                  data-level={c.level}
                  data-filled={c.count > 0}
                  data-hot={hot}
                  data-dim={!!hoverRisks?.length && !hot}
                  aria-expanded={c.count > 0 ? isOpen : undefined}
                  disabled={!c.count}
                  onClick={() => setOpen(isOpen ? null : { p, s })}
                  onMouseEnter={() => c.count && setHoverRisks(ids)}
                  onMouseLeave={() => setHoverRisks(null)}
                  onFocus={() => c.count && setHoverRisks(ids)}
                  onBlur={() => setHoverRisks(null)}
                  title={c.count ? c.risks.map((r) => r.title).join('\n') : undefined}
                  aria-label={`P${p} × S${s} = ${p * s}, ${LEVEL_RU[c.level].toLowerCase()}, открытых рисков: ${c.count}`}
                >
                  {c.count > 0 && <span>{c.count}</span>}
                </button>
              )
            })}
          </div>
        ))}
        <span />
        <span />
        {[1, 2, 3, 4, 5].map((s) => <span key={s} className="mono-m text-center text-muted">{s}</span>)}
        <span />
        <span />
        <span className="caption col-span-5 text-center" aria-hidden>последствия (S)</span>
      </div>
      {picked && (
        <ul className="space-y-1.5" aria-label={`Риски ячейки P${picked.p} × S${picked.s}`}>
          {picked.risks.map((cr) => {
            const r = byId.get(cr.id)
            return (
              <li key={cr.id}>
                <button type="button" className="card w-full text-left hover:bg-hover" onClick={() => selectRisk(cr.id)} onMouseEnter={() => setHoverRisks([cr.id])} onMouseLeave={() => setHoverRisks(null)}>
                  <span className="body-m block font-semibold">{cr.title}</span>
                  <span className="mono-m block text-muted">{r?.norms.join(' · ') || 'основание не указано'}</span>
                  <span className="caption block">{STATUS_RU[r?.status ?? 'open'] ?? r?.status}</span>
                </button>
              </li>
            )
          })}
        </ul>
      )}
      <figcaption className="flex flex-wrap gap-x-3 gap-y-1" aria-label="Легенда уровней">
        {LEVEL_ORDER.map((l) => (
          <span key={l} className="caption flex items-center gap-1.5" data-level={l}><span className="mx-swatch" aria-hidden />{LEVEL_RU[l]} {ranges[l]}</span>
        ))}
      </figcaption>
    </figure>
  )
}
