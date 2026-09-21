import { useMutation, useQueryClient } from '@tanstack/react-query'
import { MoreHorizontal } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Dialog } from '../../components/Dialog'
import { EmptyState, ErrorNote, Skeleton } from '../../components/States'
import { Button } from '../../components/ui'
import type { Session } from '../../lib/api'
import { del, errorText, patch } from '../../lib/api'
import { useSessions } from '../../lib/queries'
import type { Level } from '../../lib/api'
import { LEVEL_RU, ROLE_RU } from '../../lib/risk'

const ORDER: Level[] = ['critical', 'high', 'medium', 'low']

/** Полоса распределения активных рисков по уровням; уровень дублируется подписью для печати и скринридера. */
function RiskBar({ by }: { by: Record<string, number> }) {
  const total = ORDER.reduce((n, l) => n + (by[l] ?? 0), 0)
  if (!total) return <p className="caption">активных рисков нет</p>
  const text = ORDER.filter((l) => by[l]).map((l) => `${LEVEL_RU[l].toLowerCase()}: ${by[l]}`).join(', ')
  return (
    <div>
      <div className="flex h-2 overflow-hidden rounded-full bg-sidebar" role="img" aria-label={`Активные риски — ${text}`}>
        {ORDER.map((l) => (by[l] ? <span key={l} data-level={l} className="bg-[var(--level)]" style={{ width: `${((by[l] ?? 0) / total) * 100}%` }} /> : null))}
      </div>
      <p className="caption mt-1">{text}</p>
    </div>
  )
}

export function HistoryPage() {
  document.title = 'Мои сессии — DoorAIn'
  const [tab, setTab] = useState<'active' | 'archived'>('active')
  const list = useSessions(tab)
  const qc = useQueryClient()
  const [rename, setRename] = useState<Session | null>(null)
  const [name, setName] = useState('')
  const [remove, setRemove] = useState<Session | null>(null)
  const [confirm, setConfirm] = useState('')
  const refresh = () => qc.invalidateQueries({ queryKey: ['sessions'] })
  const upd = useMutation({ mutationFn: (v: { id: string; body: object }) => patch<Session>(`/sessions/${v.id}`, v.body), onSuccess: () => { setRename(null); void refresh() } })
  const rm = useMutation({ mutationFn: (s: Session) => del(`/sessions/${s.id}?confirm=${encodeURIComponent(confirm)}`), onSuccess: () => { setRemove(null); setConfirm(''); void refresh() } })
  return (
    <div className="mx-auto max-w-4xl space-y-4 px-4 py-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="display-m">Мои сессии</h1>
        <div role="tablist" aria-label="Фильтр" className="seg">
          {(['active', 'archived'] as const).map((t) => <button key={t} role="tab" aria-selected={tab === t} className="seg-item" onClick={() => setTab(t)}>{t === 'active' ? 'Активные' : 'Архив'}</button>)}
        </div>
      </div>
      {list.isLoading && <Skeleton lines={5} />}
      {list.isError && <ErrorNote error={list.error} onRetry={() => list.refetch()} />}
      {list.data?.length === 0 && <EmptyState title={tab === 'active' ? 'Сессий пока нет' : 'Архив пуст'} action={tab === 'active' ? <Link to="/" className="btn btn-primary no-underline">Создать сессию</Link> : undefined}>Сессия хранит диалог, портрет и риски. После перезапуска её можно продолжить.</EmptyState>}
      <ul className="grid gap-3 empty:hidden md:grid-cols-2">
        {list.data?.map((s) => (
          <li key={s.id} className="card flex flex-col gap-3">
            <div className="flex items-start justify-between gap-2">
              <Link to={`/s/${s.id}`} className="display-s min-w-0 text-ink no-underline hover:underline">{s.title}</Link>
              <details className="relative shrink-0">
                <summary className="btn btn-quiet btn-icon list-none" aria-label={`Действия с «${s.title}»`}><MoreHorizontal className="size-4" aria-hidden /></summary>
                <div className="zone absolute right-0 z-20 mt-1 w-48 space-y-1 !p-2 shadow-[var(--shadow-hover)]">
                  <Button variant="quiet" className="w-full !justify-start" onClick={() => { setRename(s); setName(s.title) }}>Переименовать</Button>
                  <Button variant="quiet" className="w-full !justify-start" onClick={() => upd.mutate({ id: s.id, body: { status: s.status === 'active' ? 'archived' : 'active' } })}>{s.status === 'active' ? 'В архив' : 'Вернуть из архива'}</Button>
                  <Button variant="quiet" className="w-full !justify-start text-risk-high" onClick={() => { setRemove(s); setConfirm('') }}>Удалить</Button>
                </div>
              </details>
            </div>
            <p className="mono-m text-muted">{ROLE_RU[s.role].toLowerCase()} · обновлена {new Date(s.updated_at).toLocaleDateString('ru-RU')} · срез на {new Date(s.as_of_date).toLocaleDateString('ru-RU')}</p>
            <p className="body-s">сообщений: {s.messages_count} · активных рисков: {s.active_risks}</p>
            <RiskBar by={s.risks_by_level} />
          </li>
        ))}
      </ul>
      <Dialog open={!!rename} onClose={() => setRename(null)} title="Переименовать сессию" footer={<><Button onClick={() => setRename(null)}>Отмена</Button><Button variant="primary" disabled={!name.trim() || upd.isPending} onClick={() => rename && upd.mutate({ id: rename.id, body: { title: name } })}>Сохранить</Button></>}>
        <label className="label" htmlFor="rn">Название</label>
        <input id="rn" className="input" value={name} maxLength={200} onChange={(e) => setName(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter' && rename && name.trim()) upd.mutate({ id: rename.id, body: { title: name } }) }} autoFocus />
        {upd.error && <p className="mt-2 text-small text-risk-high">{errorText(upd.error)}</p>}
      </Dialog>
      <Dialog open={!!remove} onClose={() => setRemove(null)} title="Удалить сессию?" footer={<><Button onClick={() => setRemove(null)}>Отмена</Button><Button variant="danger" disabled={!remove || confirm.trim() !== remove.title.trim() || rm.isPending} onClick={() => remove && rm.mutate(remove)}>Удалить безвозвратно</Button></>}>
        <div className="space-y-3 text-small">
          <p>Будут удалены сообщения, персональные факты, риски, слепок, источники ответов и PDF-выгрузки этой сессии. Общий корпус НПА не затрагивается.</p>
          <p className="text-muted">Данные, уже выгруженные вами в файлы, и прежние резервные копии сервером не изменяются.</p>
          <label className="label" htmlFor="cf">Для подтверждения введите название: <b>{remove?.title}</b></label>
          <input id="cf" className="input" value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="off" />
          {rm.error && <p className="text-risk-high">{errorText(rm.error)}</p>}
        </div>
      </Dialog>
    </div>
  )
}
