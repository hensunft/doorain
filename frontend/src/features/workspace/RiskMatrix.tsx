import { useQuery } from '@tanstack/react-query'
import { useId, useState, type FocusEvent, type MouseEvent } from 'react'
import { ErrorNote, Skeleton } from '../../components/States'
import type { components } from '../../lib/api-types'
import type { Level, Risk } from '../../lib/api'
import { get } from '../../lib/api'
import { keys } from '../../lib/queries'
import { LEVEL_ORDER, LEVEL_RU, STATUS_RU } from '../../lib/risk'
import { useSelection } from '../../lib/selection'
import { PsInfo } from '../../components/PsInfo'
import { short } from './graphModel'

type Cell = components['schemas']['MatrixCell']

/** Диапазоны уровней из порогов сервера (app/config/risk.yaml): подписи легенды не расходятся с раскраской. */
export function levelRanges(t: number[]): Record<Level, string> {
  const [a = 4, b = 9, c = 15] = t
  return { low: `1–${a}`, medium: `${a + 1}–${b}`, high: `${b + 1}–${c}`, critical: `${c + 1}–25` }
}

/** Матрица 5 × 5. Ячейка окрашена уровнем своих координат (P × S, тинт и штриховка); открытые риски — точка уровня с их числом,
 *  в ячейке больше ничего нет. Уровень дублируется штриховкой и легендой — читается в ч/б печати.
 *  Клик раскрывает риски ячейки; наведение и фокус подсвечивают их узлы в графе и карточки в списке и показывают стеклянную
 *  карточку: название, P и S, норма, пояснение и следующий шаг. */
export function RiskMatrix({ sessionId, risks, thresholds }: { sessionId: string; risks: Risk[]; thresholds: number[] }) {
  const q = useQuery({ queryKey: [...keys.risks(sessionId), 'matrix'], queryFn: () => get<Cell[]>(`/sessions/${sessionId}/risks/matrix`) })
  const { hoverRisks, setHoverRisks, selectRisk } = useSelection()
  const [open, setOpen] = useState<{ p: number; s: number } | null>(null)
  const [peek, setPeek] = useState<{ p: number; s: number; left: number; top: number; up: boolean } | null>(null)
  const cardId = useId()
  if (q.isLoading) return <Skeleton lines={5} />
  if (q.isError) return <ErrorNote error={q.error} onRetry={() => q.refetch()} />
  const cells = q.data ?? []
  const total = cells.reduce((n, c) => n + c.count, 0)
  const byId = new Map(risks.map((r) => [r.id, r]))
  const picked = open ? cells.find((c) => c.p === open.p && c.s === open.s) : undefined
  const ranges = levelRanges(thresholds)
  const peekCell = peek ? cells.find((c) => c.p === peek.p && c.s === peek.s) : undefined
  const show = (p: number, s: number, ids: string[]) => (e: MouseEvent<HTMLButtonElement> | FocusEvent<HTMLButtonElement>) => {
    setHoverRisks(ids)
    const el = e.currentTarget
    const w = (el.offsetParent as HTMLElement | null)?.clientWidth ?? 0
    setPeek({ p, s, left: Math.max(0, Math.min(el.offsetLeft, w - 280)), top: p <= 2 ? el.offsetTop - 6 : el.offsetTop + el.offsetHeight + 6, up: p <= 2 })
  }
  const hide = () => { setHoverRisks(null); setPeek(null) }
  return (
    <figure className="mx-auto max-w-sm space-y-3">
      <p className="caption flex flex-wrap items-center gap-x-1">P — вероятность<PsInfo what="p" sessionId={sessionId} /> · S — последствия<PsInfo what="s" sessionId={sessionId} /></p>
      <div className="relative grid grid-cols-[1.25rem_auto_repeat(5,minmax(0,1fr))] gap-1.5" role="grid" aria-label={`Матрица рисков 5 × 5, открытых рисков: ${total}`}>
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
                  onMouseEnter={c.count ? show(p, s, ids) : undefined}
                  onMouseLeave={hide}
                  onFocus={c.count ? show(p, s, ids) : undefined}
                  onBlur={hide}
                  aria-describedby={peek?.p === p && peek.s === s ? cardId : undefined}
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
        {peek && peekCell && peekCell.count > 0 && (
          <div id={cardId} role="tooltip" className="mx-card glass-strong" data-level={peekCell.level} style={{ left: peek.left, top: peek.top, transform: peek.up ? 'translateY(-100%)' : undefined }}>
            <p className="overline" style={{ color: 'var(--level-ink)' }}>P{peek.p} × S{peek.s} = {peek.p * peek.s} · {LEVEL_RU[peekCell.level].toLowerCase()}</p>
            {peekCell.risks.slice(0, 3).map((cr) => {
              const r = byId.get(cr.id)
              const why = r?.consequences || ((r?.description ?? '').length > 24 ? r?.description : '')  // короткий «сценарий» агента («сайт») — не пояснение
              return (
                <div key={cr.id} className="mt-2 border-t border-line-soft pt-2 first-of-type:mt-1.5 first-of-type:border-0 first-of-type:pt-0">
                  <p className="body-m font-semibold leading-snug">{cr.title}</p>
                  <p className="mono-m mt-0.5 text-muted">{r?.p != null ? `P ${r.p} · S ${r.s}` : `P ${peek.p} · S ${peek.s}`}{r?.norms.length ? ` · ${r.norms[0]}` : ''}</p>
                  {why && <p className="body-s mt-1 text-ink-2">{short(why, 150)}</p>}
                  {r?.recommendation && <p className="body-s mt-1"><span className="text-faint">Следующий шаг: </span>{short(r.recommendation, 120)}</p>}
                </div>
              )
            })}
            {peekCell.risks.length > 3 && <p className="caption mt-2">и ещё {peekCell.risks.length - 3} — нажмите на ячейку</p>}
          </div>
        )}
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
