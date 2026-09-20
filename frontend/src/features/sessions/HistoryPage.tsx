import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Archive, ArchiveRestore, Pencil, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Dialog } from '../../components/Dialog'
import { EmptyState, ErrorNote, Skeleton } from '../../components/States'
import { Button } from '../../components/ui'
import { MapArt } from '../../components/art'
import type { Session } from '../../lib/api'
import { del, errorText, patch } from '../../lib/api'
import { useSessions } from '../../lib/queries'
import { ROLE_RU } from '../../lib/risk'

export function HistoryPage() {
  document.title = 'История — DoorAIn'
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
        <h1>История сессий</h1>
        <div role="tablist" aria-label="Фильтр" className="flex gap-1">
          {(['active', 'archived'] as const).map((t) => <button key={t} role="tab" aria-selected={tab === t} className={`btn ${tab === t ? 'btn-primary' : ''}`} onClick={() => setTab(t)}>{t === 'active' ? 'Активные' : 'Архив'}</button>)}
        </div>
      </div>
      {list.isLoading && <Skeleton lines={5} />}
      {list.isError && <ErrorNote error={list.error} onRetry={() => list.refetch()} />}
      {list.data?.length === 0 && <EmptyState art={MapArt} title={tab === 'active' ? 'Сессий пока нет' : 'Архив пуст'} action={tab === 'active' ? <Link to="/" className="btn btn-primary no-underline">Создать сессию</Link> : undefined}>Сессия хранит диалог, портрет и риски. После перезапуска её можно продолжить.</EmptyState>}
      <ul className="divide-y divide-line rounded-lg border border-line empty:hidden">
        {list.data?.map((s) => (
          <li key={s.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
            <div className="min-w-0 flex-1">
              <Link to={`/s/${s.id}`} className="block truncate font-medium text-ink no-underline hover:underline">{s.title}</Link>
              <p className="text-small text-muted">{ROLE_RU[s.role]} · срез на {s.as_of_date} · сообщений: {s.messages_count} · активных рисков: {s.active_risks} · обновлена {new Date(s.updated_at).toLocaleString('ru-RU')}</p>
            </div>
            <div className="flex gap-1">
              <Button variant="quiet" className="btn-icon" aria-label={`Переименовать «${s.title}»`} onClick={() => { setRename(s); setName(s.title) }}><Pencil className="size-4" aria-hidden /></Button>
              <Button variant="quiet" className="btn-icon" aria-label={s.status === 'active' ? `Архивировать «${s.title}»` : `Вернуть из архива «${s.title}»`} onClick={() => upd.mutate({ id: s.id, body: { status: s.status === 'active' ? 'archived' : 'active' } })}>{s.status === 'active' ? <Archive className="size-4" aria-hidden /> : <ArchiveRestore className="size-4" aria-hidden />}</Button>
              <Button variant="quiet" className="btn-icon" aria-label={`Удалить «${s.title}»`} onClick={() => { setRemove(s); setConfirm('') }}><Trash2 className="size-4" aria-hidden /></Button>
            </div>
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
