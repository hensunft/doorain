import { createColumnHelper, flexRender, getCoreRowModel, getSortedRowModel, useReactTable, type SortingState } from '@tanstack/react-table'
import { Maximize2 } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Dialog } from '../../components/Dialog'
import { EmptyState, ErrorNote, Skeleton } from '../../components/States'
import { Button, RiskBadge } from '../../components/ui'
import type { Level, Risk, Session } from '../../lib/api'
import { useGraph, useRisks } from '../../lib/queries'
import { LEVEL_ORDER, levelVar, STATUS_RU } from '../../lib/risk'
import { riskIdsForNode, useSelection } from '../../lib/selection'
import { RiskCard } from './RiskCard'
import { RiskDetail } from './RiskDetail'

const col = createColumnHelper<Risk>()

function RisksTable({ rows, highlight, selected, onSelect }: { rows: Risk[]; highlight: Set<string>; selected: string | null; onSelect: (id: string) => void }) {
  const [sorting, setSorting] = useState<SortingState>([{ id: 'score', desc: true }])
  const columns = useMemo(() => [
    col.display({ id: 'n', header: '№', cell: (c) => c.row.index + 1 }),
    col.accessor('title', { header: 'Риск', cell: (c) => <div><b className="font-medium">{c.getValue()}</b><div className="text-muted">{c.row.original.scenario}</div></div> }),
    col.accessor((r) => r.score ?? 0, { id: 'score', header: 'P×S, уровень', cell: (c) => <div className="space-y-1"><RiskBadge level={c.row.original.level} score={c.row.original.score} /><div className="tnum text-muted">P{c.row.original.p}×S{c.row.original.s}</div></div> }),
    col.accessor((r) => r.norms.join('; '), { id: 'norms', header: 'Нормативное основание', enableSorting: false, cell: (c) => c.getValue() || '—' }),
    col.accessor('consequences', { header: 'Последствия', enableSorting: false, cell: (c) => c.getValue() || '—' }),
    col.accessor('recommendation', { header: 'Рекомендация', enableSorting: false, cell: (c) => c.getValue() || '—' }),
    col.accessor('status', { header: 'Статус', cell: (c) => STATUS_RU[c.getValue()] ?? c.getValue() }),
  ], [])
  const table = useReactTable({ data: rows, columns, state: { sorting }, onSortingChange: setSorting, getCoreRowModel: getCoreRowModel(), getSortedRowModel: getSortedRowModel() })
  return (
    <div className="overflow-auto">
      <table className="w-full min-w-[820px] border-collapse text-small">
        <caption className="sr-only">Таблица рисков сессии, по умолчанию отсортирована по убыванию оценки</caption>
        <thead className="sticky top-0 bg-canvas">
          {table.getHeaderGroups().map((hg) => (
            <tr key={hg.id} className="border-b border-line text-left">
              {hg.headers.map((h) => {
                const dir = h.column.getIsSorted()
                return (
                  <th key={h.id} scope="col" aria-sort={dir === 'asc' ? 'ascending' : dir === 'desc' ? 'descending' : 'none'} className="px-2 py-2 font-medium">
                    {h.column.getCanSort() ? <button type="button" className="font-medium hover:underline" onClick={h.column.getToggleSortingHandler()}>{flexRender(h.column.columnDef.header, h.getContext())}{dir === 'asc' ? ' ↑' : dir === 'desc' ? ' ↓' : ''}</button> : flexRender(h.column.columnDef.header, h.getContext())}
                  </th>
                )
              })}
            </tr>
          ))}
        </thead>
        <tbody>
          {table.getRowModel().rows.map((r) => (
            <tr key={r.original.id} tabIndex={0} aria-selected={selected === r.original.id} onClick={() => onSelect(r.original.id)} onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelect(r.original.id) } }} className={`cursor-pointer border-b border-line align-top hover:bg-sidebar ${selected === r.original.id ? 'bg-selected' : highlight.has(r.original.id) ? 'bg-risk-critical-soft/50' : ''}`}>
              {r.getVisibleCells().map((c) => <td key={c.id} className="max-w-[260px] px-2 py-2 break-words">{flexRender(c.column.columnDef.cell, c.getContext())}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

const FILTERS = [['active', 'Активные'], ['needs_clarification', 'Уточнения'], ['resolved', 'Снятые']] as const

const SHORT: Record<Level, string> = { low: 'низк.', medium: 'средн.', high: 'высок.', critical: 'критич.' }

/** Сводка: пилюля на каждый уровень с числом. Клик фильтрует список; цвет дублируется подписью. */
function LevelSummary({ rows, only, onOnly }: { rows: Risk[]; only: Level | null; onOnly: (l: Level | null) => void }) {
  const counts = LEVEL_ORDER.map((l) => [l, rows.filter((r) => r.level === l).length] as const).filter(([, n]) => n > 0)
  if (!counts.length) return null
  return (
    <ul className="flex flex-wrap gap-1.5 px-3 pb-2" aria-label="Сводка по уровням риска">
      {counts.reverse().map(([l, n]) => (
        <li key={l}>
          <button
            type="button"
            aria-pressed={only === l}
            onClick={() => onOnly(only === l ? null : l)}
            className="badge-level gap-1.5 px-3"
            style={{ ['--level' as string]: levelVar(l) }}
            data-level={l}
          >
            <span className="tnum">{n}</span> {SHORT[l]}
          </button>
        </li>
      ))}
    </ul>
  )
}

export function RisksPanel({ session }: { session: Session }) {
  const risks = useRisks(session.id)
  const graph = useGraph(session.id)
  const { sel, selectRisk } = useSelection()
  const [filter, setFilter] = useState<(typeof FILTERS)[number][0]>('active')
  const [wide, setWide] = useState(false)
  const [only, setOnly] = useState<Level | null>(null)
  const [open, setOpen] = useState<Record<string, boolean>>({})
  const data = risks.data
  const base = data ? (filter === 'active' ? data.active : filter === 'resolved' ? data.resolved : data.needs_clarification) : []
  const list = only ? base.filter((r) => r.level === only) : base
  const qNum = new Map<string, number>()
  graph.data?.nodes.filter((n) => n.kind === 'question').forEach((n, i) => qNum.set(n.id, i + 1))
  const questionsOf = (riskId: string) => {
    const riskNode = graph.data?.nodes.find((n) => n.kind === 'risk' && n.data['risk_id'] === riskId)
    if (!riskNode) return []
    const out = new Set<number>()
    for (const e of graph.data?.edges ?? []) {
      if (e.kind !== 'evidences') continue
      const other = e.source === riskNode.id ? e.target : e.target === riskNode.id ? e.source : null
      const n = other ? qNum.get(other) : undefined
      if (n) out.add(n)
    }
    return [...out].sort((a, b) => a - b)
  }
  const highlight = useMemo(() => riskIdsForNode(graph.data, data?.active ?? [], sel.nodeId), [graph.data, data, sel.nodeId])
  const selected = sel.riskId
  const learning = session.role === 'student'
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center justify-between gap-2 border-b border-line px-3 py-2">
        <h2 className="display-s">{learning ? 'Ошибки понимания' : 'Риски'} <span className="caption font-normal">P × S, по убыванию</span></h2>
        <Button className="btn-icon" aria-label="Развернуть таблицу на всю ширину" onClick={() => setWide(true)}><Maximize2 className="size-4" aria-hidden /></Button>
      </div>
      <div role="tablist" aria-label="Фильтр рисков" className="flex gap-1 px-3 py-2">
        {FILTERS.map(([id, label]) => <button key={id} role="tab" aria-selected={filter === id} className={`btn ${filter === id ? 'btn-primary' : 'btn-quiet'}`} onClick={() => setFilter(id)}>{label}{data ? ` ${id === 'active' ? data.active.length : id === 'resolved' ? data.resolved.length : data.needs_clarification.length}` : ''}</button>)}
      </div>
      {filter === 'active' && data && <LevelSummary rows={data.active} only={only} onOnly={setOnly} />}
      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto px-3 pb-3">
        {risks.isLoading && <Skeleton lines={5} />}
        {risks.isError && <ErrorNote error={risks.error} onRetry={() => risks.refetch()} />}
        {data && list.length === 0 && (
          filter === 'active' ? <EmptyState title={learning ? 'Ошибок понимания не выявлено' : 'Подтверждённых рисков нет'}>{learning ? 'Вопрос сам по себе не доказывает незнание. Пройдите самопроверку: подтверждённые ошибки появятся здесь.' : 'Риск создаётся только при нормативном основании и подтверждённых фактах. Отсутствие строк не означает безопасность.'}</EmptyState> : <p className="hint px-1">Здесь пока ничего нет.</p>
        )}
        {filter === 'needs_clarification' && data?.clarifications.map((c) => <p key={c} className="rounded-md bg-risk-medium-soft px-3 py-2 text-small text-risk-medium">Вопрос для уточнения: {c}</p>)}
        <ul className="space-y-2">
          {list.map((r, i) => {
            const isSel = selected === r.id
            const isOpen = open[r.id] ?? (isSel || (i < 2 && filter === 'active'))
            return (
              <li key={r.id}>
                <RiskCard
                  risk={r}
                  sessionId={session.id}
                  questions={questionsOf(r.id)}
                  expanded={isOpen}
                  selected={isSel}
                  highlighted={highlight.has(r.id)}
                  onToggle={() => { setOpen({ ...open, [r.id]: !isSel }); selectRisk(isSel ? null : r.id) }}
                >
                  {isSel && <div className="mt-3 border-t border-line-soft pt-3"><RiskDetail riskId={r.id} sessionId={session.id} /></div>}
                </RiskCard>
              </li>
            )
          })}
        </ul>
      </div>
      <Dialog open={wide} onClose={() => setWide(false)} title="Таблица рисков" variant="full">
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(320px,420px)]">
          <div className="min-w-0"><RisksTable rows={data?.active ?? []} highlight={highlight} selected={selected} onSelect={(id) => selectRisk(id)} /></div>
          <div className="min-w-0 rounded-md border border-line p-3">{selected ? <RiskDetail riskId={selected} sessionId={session.id} /> : <p className="hint">Выберите строку, чтобы увидеть подробности: основания, факты, историю и изменить статус.</p>}</div>
        </div>
      </Dialog>
    </div>
  )
}
