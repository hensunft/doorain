import { useQuery } from '@tanstack/react-query'
import { ErrorNote, Skeleton } from '../../components/States'
import type { components } from '../../lib/api-types'
import { get } from '../../lib/api'
import { keys } from '../../lib/queries'
import { LEVEL_RU } from '../../lib/risk'

type Cell = components['schemas']['MatrixCell']
const SHORT: Record<Cell['level'], string> = { low: 'низк.', medium: 'средн.', high: 'высок.', critical: 'критич.' }

/** Матрица 5 × 5: вероятность по вертикали, тяжесть по горизонтали. Заливка — тинт уровня; уровень дублируется
 *  подписью в углу ячейки, поэтому матрица читается и в чёрно-белой печати. Клик по ячейке фильтрует список. */
export function RiskMatrix({ sessionId, onPick }: { sessionId: string; onPick: (p: number, s: number) => void }) {
  const q = useQuery({ queryKey: [...keys.risks(sessionId), 'matrix'], queryFn: () => get<Cell[]>(`/sessions/${sessionId}/risks/matrix`) })
  if (q.isLoading) return <Skeleton lines={5} />
  if (q.isError) return <ErrorNote error={q.error} onRetry={() => q.refetch()} />
  const cells = q.data ?? []
  const total = cells.reduce((n, c) => n + c.count, 0)
  return (
    <figure className="mx-auto max-w-sm space-y-2">
      <div className="grid grid-cols-[auto_repeat(5,minmax(0,1fr))] gap-1" role="grid" aria-label={`Матрица рисков 5 × 5, всего активных: ${total}`}>
        {[5, 4, 3, 2, 1].map((p) => (
          <div key={p} role="row" className="contents">
            <span className="mono-m flex items-center justify-end pr-1 text-muted" role="rowheader">P{p}</span>
            {[1, 2, 3, 4, 5].map((s) => {
              const c = cells.find((x) => x.p === p && x.s === s)
              if (!c) return <span key={s} />
              const tint = `var(--risk-${c.level === 'medium' ? 'mid' : c.level}-tint)`
              const ink = `var(--risk-${c.level === 'medium' ? 'mid' : c.level})`
              const titles = c.risks.map((r) => r.title).join('\n')
              return (
                <button
                  key={s}
                  type="button"
                  role="gridcell"
                  disabled={!c.count}
                  onClick={() => onPick(p, s)}
                  title={c.count ? `P${p} × S${s} = ${p * s} (${LEVEL_RU[c.level].toLowerCase()})\n${titles}` : `P${p} × S${s} = ${p * s}`}
                  aria-label={`P${p} × S${s} = ${p * s}, ${LEVEL_RU[c.level].toLowerCase()}, рисков: ${c.count}`}
                  className="relative flex aspect-square min-h-11 flex-col items-center justify-center rounded-md border border-line text-ink disabled:cursor-default"
                  style={{ background: tint }}
                >
                  <span className="absolute left-1 top-0.5 text-[9px] leading-none text-muted">{SHORT[c.level]}</span>
                  {c.count > 0 && <span className="mono-l" style={{ color: ink }}>{c.count}</span>}
                  {c.count > 0 && <span className="mt-0.5 flex gap-0.5" aria-hidden>{c.risks.slice(0, 4).map((r) => <span key={r.id} className="size-1.5 rounded-full" style={{ background: ink }} />)}</span>}
                </button>
              )
            })}
          </div>
        ))}
        <span />
        {[1, 2, 3, 4, 5].map((s) => <span key={s} className="mono-m text-center text-muted">S{s}</span>)}
      </div>
      <figcaption className="caption">Вероятность (P) по вертикали, тяжесть (S) по горизонтали. Всего активных рисков: {total}. Клик по ячейке — отфильтровать список.</figcaption>
    </figure>
  )
}
