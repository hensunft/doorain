import { useMutation, useQueryClient } from '@tanstack/react-query'
import { LogOut } from 'lucide-react'
import { useState, type FormEvent, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { Banner, ErrorNote, Skeleton } from '../../components/States'
import { Button, Field } from '../../components/ui'
import { useLocalState } from '../../lib/hooks'
import { errorText, patch, post, setCsrf } from '../../lib/api'
import type { components } from '../../lib/api-types'
import { useMe } from '../../app/App'
import { keys, useDiagnostics } from '../../lib/queries'

function Row({ k, children }: { k: string; children: ReactNode }) {
  return <div className="flex justify-between gap-4 border-b border-line py-1.5 text-small"><dt className="text-muted">{k}</dt><dd className="text-right">{children}</dd></div>
}
const ok = (v: boolean | undefined) => (v ? 'Работает' : 'Недоступно')

/** Профиль: имя, фамилия, почта. Логин неизменяем — на него ссылаются журнал, сессии и приглашения. */
function ProfileSection() {
  const me = useMe()
  const qc = useQueryClient()
  const u = me.data?.user
  const [f, setF] = useState<{ first: string; last: string; email: string; pw: string } | null>(null)
  const [saved, setSaved] = useState(false)
  const cur = f ?? { first: u?.first_name ?? '', last: u?.last_name ?? '', email: u?.email ?? '', pw: '' }
  const emailChanged = cur.email.trim().toLowerCase() !== (u?.email ?? '')
  const save = useMutation({
    mutationFn: () => patch<components['schemas']['AuthOut']>('/auth/profile', { first_name: cur.first, last_name: cur.last, email: cur.email.trim(), current_password: emailChanged ? cur.pw : null }),
    onSuccess: (d) => { qc.setQueryData(keys.me, d); void qc.invalidateQueries({ queryKey: ['admin'] }); setF(null); setSaved(true) },
  })
  if (!u) return null
  const set = (k: 'first' | 'last' | 'email' | 'pw') => (e: React.ChangeEvent<HTMLInputElement>) => { setSaved(false); setF({ ...cur, [k]: e.target.value }) }
  return (
    <section aria-labelledby="prof" className="space-y-3">
      <h2 id="prof" className="text-h3">Профиль</h2>
      <form className="max-w-lg space-y-3" onSubmit={(e) => { e.preventDefault(); save.mutate() }}>
        <div>
          <span className="label">Логин</span>
          <p className="mono-l">{u.username}</p>
          <p className="hint">Логин — постоянный идентификатор учётной записи, изменить его нельзя.</p>
        </div>
        {!u.first_name && !u.last_name && <Banner>Имя и фамилия не указаны: в интерфейсе показывается логин. Заполните их — это необязательно.</Banner>}
        <div className="grid gap-3 sm:grid-cols-2">
          <Field id="pf" label="Имя"><input id="pf" className="input" autoComplete="given-name" maxLength={80} value={cur.first} onChange={set('first')} /></Field>
          <Field id="pl" label="Фамилия"><input id="pl" className="input" autoComplete="family-name" maxLength={80} value={cur.last} onChange={set('last')} /></Field>
        </div>
        <Field id="pe" label="Электронная почта" hint="Адрес не подтверждается письмом: он хранится как указанный вами контакт."><input id="pe" className="input" type="email" autoComplete="email" maxLength={200} value={cur.email} onChange={set('email')} /></Field>
        {emailChanged && <Field id="pp" label="Пароль для смены почты" hint="Введите текущий пароль: без него адрес не меняется."><input id="pp" className="input" type="password" autoComplete="current-password" value={cur.pw} onChange={set('pw')} required /></Field>}
        {save.error && <Banner tone="error">{errorText(save.error)}</Banner>}
        {saved && <Banner>Профиль сохранён.</Banner>}
        <Button type="submit" loading={save.isPending} disabled={!f}>Сохранить профиль</Button>
      </form>
    </section>
  )
}

export function SettingsPage() {
  document.title = 'Настройки — DoorAIn'
  const me = useMe()
  const isOwner = me.data?.user.access_level === 'owner'
  const d = useDiagnostics(isOwner)  // диагностика — только владельцу: пользователю не показываем ошибку доступа
  const nav = useNavigate()
  const qc = useQueryClient()
  const [cur, setCur] = useState('')
  const [next, setNext] = useState('')
  const [done, setDone] = useState(false)
  const change = useMutation({
    mutationFn: () => post<components['schemas']['AuthOut']>('/auth/change-password', { current_password: cur, new_password: next }),
    onSuccess: (r) => { setCsrf(r.csrf_token); setCur(''); setNext(''); setDone(true) },
  })
  const logout = useMutation({ mutationFn: () => post('/auth/logout'), onSuccess: () => { qc.clear(); nav('/login', { replace: true }) } })
  const submit = (e: FormEvent) => { e.preventDefault(); setDone(false); change.mutate() }
  const x = d.data
  const [dev, setDev] = useLocalState('doorain.dev', false)
  return (
    <div className="mx-auto max-w-3xl space-y-8 px-4 py-6">
      <h1>Настройки</h1>
      <ProfileSection />
      <section aria-labelledby="diag" className="space-y-2">
        <h2 id="diag" className="text-h3">О программе</h2>
        <label className="flex min-h-11 items-center gap-2 text-small"><input type="checkbox" className="size-4 accent-[var(--brand)]" checked={dev} onChange={(e) => setDev(e.target.checked)} />Режим разработчика — служебные метки (номер generation корпуса) в рабочем пространстве</label>
        {isOwner && d.isLoading && <Skeleton lines={6} />}
        {isOwner && d.isError && <ErrorNote error={d.error} onRetry={() => d.refetch()} />}
        {x && (
          <dl>
            <Row k="Версия / режим провайдеров">{x.version} · {x.provider_mode === 'test' ? 'ТЕСТОВЫЙ (заглушки, не модель)' : 'локальные модели'}</Row>
            <Row k="База данных">{ok(x.database['ok'] as boolean)}</Row>
            <Row k="Qdrant">{ok(x.qdrant['ok'] as boolean)} · точек в индексе: {String(x.qdrant['points'] ?? 0)}</Row>
            <Row k="Языковая модель">{ok(x.llm['ok'] as boolean)} · {String(x.llm['name'] ?? '—')} {x.llm['quantization'] ? `(${String(x.llm['quantization'])})` : ''} · контекст {String(x.llm['num_ctx'] ?? '—')}</Row>
            <Row k="Embeddings (BGE-M3)">{ok(x.embedder['ok'] as boolean)}</Row>
            <Row k="Reranker">{ok(x.reranker['ok'] as boolean)} · {String(x.reranker['name'] ?? '')}</Row>
            <Row k="Worker">{x.worker['alive'] ? 'Работает' : 'Не отвечает'}</Row>
            <Row k="Корпус">{x.corpus['empty'] ? 'Пуст: загрузите документы в «Базе знаний»' : `редакций: ${String(x.corpus['revisions'])}, фрагментов: ${String(x.corpus['chunks'])}, generation №${String(x.corpus['generation_seq'])}`}</Row>
            <Row k="Порог релевантности">{String(x.thresholds['min_rerank_score'])} ({String(x.thresholds['source'])}) · top-k {String(x.thresholds['top_k'])} · контекст {String(x.thresholds['num_ctx'])}</Row>
            <Row k="Диск данных">свободно {String(x.disk['free_gb'])} ГБ из {String(x.disk['total_gb'])} ГБ</Row>
            <Row k="Задания">{Object.entries(x.jobs).map(([k, v]) => `${k}: ${v}`).join(', ') || 'нет'}</Row>
          </dl>
        )}
        {x && x.thresholds['source'] === 'uncalibrated' && x.provider_mode !== 'test' && <Banner tone="warn">Порог отказа не откалиброван на проверочных данных: ответы нельзя считать надёжными до калибровки (docs/evaluation.md).</Banner>}
      </section>
      <section aria-labelledby="pw" className="space-y-3">
        <h2 id="pw" className="text-h3">Смена пароля</h2>
        <form onSubmit={submit} className="max-w-sm space-y-3">
          {/* Скрытое имя пользователя: без него браузер и менеджер паролей не связывают форму с учётной записью. */}
          <input className="sr-only" type="text" name="username" autoComplete="username" tabIndex={-1} aria-hidden readOnly value={me.data?.user.username ?? ''} />
          <Field id="cur" label="Текущий пароль"><input id="cur" className="input" type="password" autoComplete="current-password" value={cur} onChange={(e) => setCur(e.target.value)} required /></Field>
          <Field id="new" label="Новый пароль" hint="Не короче 12 символов. После смены все остальные сессии входа будут завершены."><input id="new" className="input" type="password" autoComplete="new-password" minLength={12} value={next} onChange={(e) => setNext(e.target.value)} required /></Field>
          {change.error && <Banner tone="error">{errorText(change.error)}</Banner>}
          {done && <Banner>Пароль изменён. Остальные сессии входа отозваны.</Banner>}
          <button className="btn btn-primary" type="submit" disabled={change.isPending} aria-busy={change.isPending || undefined}>Сменить пароль</button>
        </form>
      </section>
      <section className="space-y-2">
        <h2 className="text-h3">Сессия входа</h2>
        <button className="btn" onClick={() => logout.mutate()} disabled={logout.isPending}><LogOut className="size-4" aria-hidden />Выйти</button>
      </section>
    </div>
  )
}
