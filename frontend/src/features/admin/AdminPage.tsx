import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Copy, Check } from 'lucide-react'
import { useState } from 'react'
import { Banner, ErrorNote, Skeleton } from '../../components/States'
import { Field, Spinner } from '../../components/ui'
import { del, get, patch, post } from '../../lib/api'
import type { components } from '../../lib/api-types'

type S = components['schemas']
type Stats = S['AdminStats']
type UserRow = S['UserAdminOut']
type Invite = S['InviteOut']
type AuditRow = S['AuditEventOut']

const STATE_RU: Record<Invite['state'], string> = { active: 'действует', used: 'использован', revoked: 'отозван', expired: 'истёк' }
const ROLE_RU: Record<string, string> = { student: 'Студент', entrepreneur: 'Предприниматель', expert: 'Эксперт' }
const dt = (v: string | null) => (v ? new Date(v).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' }) : '—')

function NewInvite() {
  const qc = useQueryClient()
  const [note, setNote] = useState('')
  const [copied, setCopied] = useState(false)
  const create = useMutation({
    mutationFn: () => post<S['InviteCreated']>('/admin/invites', { note: note || null }),
    onSuccess: () => { setNote(''); void qc.invalidateQueries({ queryKey: ['admin', 'invites'] }) },
  })
  const code = create.data?.code
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-2">
        <Field id="note" label="Для кого код"><input id="note" className="input w-56" value={note} onChange={(e) => setNote(e.target.value)} placeholder="например: Иван, отдел продаж" /></Field>
        <button className="btn btn-primary" onClick={() => create.mutate()} disabled={create.isPending}>{create.isPending ? <Spinner label="Создаём…" /> : 'Выпустить код'}</button>
      </div>
      {code && (
        <Banner tone="warn">
          <span className="block">Код показывается один раз — в базе хранится только его хеш. Передайте его лично.</span>
          <span className="mt-2 flex items-center gap-2">
            <code className="select-all break-all rounded bg-sidebar px-2 py-1">{code}</code>
            <button className="btn btn-icon" aria-label="Скопировать код" onClick={() => { void navigator.clipboard?.writeText(code).then(() => { setCopied(true); window.setTimeout(() => setCopied(false), 1500) }) }}>
              {copied ? <Check className="size-4" aria-hidden /> : <Copy className="size-4" aria-hidden />}
            </button>
          </span>
        </Banner>
      )}
      {create.error && <ErrorNote error={create.error} />}
    </div>
  )
}

export function AdminPage() {
  document.title = 'Администрирование — DoorAIn'
  const qc = useQueryClient()
  const stats = useQuery({ queryKey: ['admin', 'stats'], queryFn: () => get<Stats>('/admin/stats') })
  const users = useQuery({ queryKey: ['admin', 'users'], queryFn: () => get<UserRow[]>('/admin/users') })
  const invites = useQuery({ queryKey: ['admin', 'invites'], queryFn: () => get<Invite[]>('/admin/invites') })
  const audit = useQuery({ queryKey: ['admin', 'audit'], queryFn: () => get<AuditRow[]>('/admin/audit?limit=50') })
  const toggle = useMutation({
    mutationFn: (v: { id: string; disabled: boolean }) => patch<UserRow>(`/admin/users/${v.id}`, { disabled: v.disabled }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ['admin'] }) },
  })
  const revoke = useMutation({
    mutationFn: (id: string) => del(`/admin/invites/${id}`),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ['admin', 'invites'] }) },
  })
  const purge = useMutation({
    mutationFn: () => post<{ purged: number }>('/admin/sessions/purge', {}),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ['admin'] }) },
  })
  return (
    <div className="neutral mx-auto max-w-4xl space-y-6 p-4 md:p-6">
      <header>
        <h1>Администрирование</h1>
        <p className="hint mt-1">Учётные записи, приглашения и обезличенная статистика. Содержимое диалогов здесь не отображается.</p>
      </header>

      <section aria-labelledby="st">
        <h2 id="st">Статистика</h2>
        {stats.isLoading && <Skeleton lines={3} />}
        {stats.isError && <ErrorNote error={stats.error} onRetry={() => stats.refetch()} />}
        {stats.data && (
          <>
            <dl className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3">
              {([['Пользователей', stats.data.users], ['Активных', stats.data.active_users], ['Сессий', stats.data.sessions], ['Удалённых сессий', stats.data.deleted_sessions], ['Сообщений', stats.data.messages], ['Активных рисков', stats.data.risks_active]] as const).map(([k, v]) => (
                <div key={k} className="rounded-md border border-line p-3">
                  <dt className="text-small text-muted">{k}</dt>
                  <dd className="text-lg font-medium">{v}</dd>
                </div>
              ))}
            </dl>
            <p className="hint mt-2">Сессии по ролям: {Object.entries(stats.data.sessions_by_role).map(([k, v]) => `${ROLE_RU[k] ?? k} — ${v}`).join('; ') || 'нет'}</p>
            {stats.data.owner_can_read_user_sessions && <Banner tone="warn">Владельцу открыто содержимое сессий пользователей. Каждый такой просмотр записывается в журнал ниже; пользователи предупреждены об этом при первом входе. Отключается настройкой <code>DOORAIN_OWNER_CAN_READ_USER_SESSIONS=false</code>.</Banner>}
            {stats.data.deleted_sessions > 0 && (
              <button className="btn btn-danger mt-3" onClick={() => purge.mutate()} disabled={purge.isPending}>
                {purge.isPending ? <Spinner label="Очищаем…" /> : `Очистить удалённые сессии (${stats.data.deleted_sessions})`}
              </button>
            )}
          </>
        )}
      </section>

      <section aria-labelledby="inv">
        <h2 id="inv">Приглашения</h2>
        <p className="hint mb-3">Саморегистрации нет: учётная запись открывается только по коду.</p>
        <NewInvite />
        {invites.isLoading && <Skeleton lines={2} />}
        {invites.data?.length === 0 && <p className="mt-3 text-small text-muted">Кодов пока нет.</p>}
        {!!invites.data?.length && (
          <table className="mt-3 w-full text-small">
            <thead><tr className="text-left text-muted"><th className="py-1">Код</th><th>Для кого</th><th>Состояние</th><th>Действует до</th><th></th></tr></thead>
            <tbody>
              {invites.data.map((i) => (
                <tr key={i.id} className="border-t border-line">
                  <td className="py-1.5">…{i.hint}</td>
                  <td>{i.note ?? '—'}</td>
                  <td>{STATE_RU[i.state]}{i.used_by ? ` (${i.used_by})` : ''}</td>
                  <td>{dt(i.expires_at)}</td>
                  <td className="text-right">{i.state === 'active' && <button className="btn btn-quiet" onClick={() => revoke.mutate(i.id)}>Отозвать</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section aria-labelledby="us">
        <h2 id="us">Учётные записи</h2>
        {users.isLoading && <Skeleton lines={2} />}
        {users.data && (
          <table className="mt-3 w-full text-small">
            <thead><tr className="text-left text-muted"><th className="py-1">Логин</th><th>Доступ</th><th>Последний вход</th><th>Сессий</th><th></th></tr></thead>
            <tbody>
              {users.data.map((u) => (
                <tr key={u.id} className="border-t border-line">
                  <td className="py-1.5">{u.username}</td>
                  <td>{u.access_level === 'owner' ? 'владелец' : 'пользователь'}</td>
                  <td>{dt(u.last_login_at)}</td>
                  <td>{u.sessions}{u.deleted_sessions ? ` (+${u.deleted_sessions} удалено)` : ''}</td>
                  <td className="text-right">
                    {u.access_level !== 'owner' && (
                      <button className={`btn ${u.disabled_at ? '' : 'btn-danger'}`} onClick={() => toggle.mutate({ id: u.id, disabled: !u.disabled_at })} disabled={toggle.isPending}>
                        {u.disabled_at ? 'Включить' : 'Отключить'}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section aria-labelledby="au">
        <h2 id="au">Журнал действий</h2>
        {audit.isLoading && <Skeleton lines={3} />}
        {audit.data && (
          <ul className="mt-3 space-y-1 text-small">
            {audit.data.map((e) => (
              <li key={e.id} className="flex flex-wrap gap-2 border-b border-line py-1">
                <span className="text-muted">{dt(e.at)}</span>
                <span className="font-medium">{e.actor}</span>
                <span>{e.action}</span>
                {e.object_id && <span className="text-muted">{e.object_type} {e.object_id.slice(0, 8)}</span>}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
