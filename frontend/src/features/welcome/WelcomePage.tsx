import { useMutation, useQueryClient } from '@tanstack/react-query'
import { BookOpen, Landmark, ScanEye } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Banner } from '../../components/States'
import { Field } from '../../components/ui'
import type { Role, Session } from '../../lib/api'
import { errorText, post } from '../../lib/api'
import { todayISO } from '../../lib/date'
import { useSessions } from '../../lib/queries'
import { ROLE_RU } from '../../lib/risk'

const ROLES: { id: Role; title: string; text: string; gets: string[] }[] = [
  { id: 'student', title: 'Студент', text: 'Разобраться в теме и проверить себя.', gets: ['Объяснение от простого к сложному', 'Примеры и связь с источниками', 'Самопроверка по материалам сессии'] },
  { id: 'entrepreneur', title: 'Предприниматель', text: 'Понять, что грозит бизнесу и что делать.', gets: ['Краткий условный вывод и действия', 'Риски с оценкой P × S и план шагов', 'Отчёт для юриста в PDF'] },
  { id: 'expert', title: 'Эксперт', text: 'Точные нормы для собственной работы.', gets: ['Выдержки с реквизитами и редакцией', 'Условия применимости, сравнение редакций', 'Выгрузка цитат'] },
]
/** Символы ролей: книга (учёба), колонна (дело), глаз (экспертиза) — маленькие «монеты» из тёмного камня с бронзовым знаком. */
const SYM = { student: BookOpen, entrepreneur: Landmark, expert: ScanEye } as const
type Tri = 'yes' | 'no' | 'unknown'
const TRI: { v: Tri; t: string }[] = [{ v: 'unknown', t: 'Не знаю' }, { v: 'yes', t: 'Да' }, { v: 'no', t: 'Нет' }]

export function WelcomePage() {
  document.title = 'DoorAIn'
  const nav = useNavigate()
  const qc = useQueryClient()
  const recent = useSessions('active')
  const [role, setRole] = useState<Role>('entrepreneur')
  const [title, setTitle] = useState('')
  const [asOf, setAsOf] = useState(todayISO)
  const [profile, setProfile] = useState({ sphere: '', has_site_or_app: 'unknown' as Tri, processes_pd: 'unknown' as Tri, mailings: 'unknown' as Tri, servers_location: 'unknown' as 'ru' | 'abroad' | 'both' | 'unknown' })
  const create = useMutation({
    mutationFn: () => post<Session>('/sessions', { role, title: title || null, as_of_date: asOf || null, profile: role === 'entrepreneur' ? { ...profile, sphere: profile.sphere || null } : null }),
    onSuccess: (s) => { void qc.invalidateQueries({ queryKey: ['sessions'] }); nav(`/s/${s.id}`) },
  })
  const submit = (e: FormEvent) => { e.preventDefault(); create.mutate() }
  return (
    <div className="mx-auto max-w-5xl space-y-10 px-4 py-10">
      <header className="space-y-4">
        <p className="overline">Новая сессия</p>
        <h1 className="display-xl max-w-3xl">Портрет вашего правового положения</h1>
        <p className="body-l max-w-prose text-muted">Задавайте вопросы по праву высоких технологий. Каждый ответ опирается на источники из закрытой базы знаний, а сессия постепенно складывается в карту вопросов и таблицу рисков.</p>
        <Banner>Ответы носят информационный характер и не заменяют профессиональную юридическую помощь.</Banner>
      </header>

      <form onSubmit={submit} className="space-y-6" aria-label="Новая сессия">
        <fieldset className="space-y-3">
          <legend className="display-s mb-4">Выберите роль</legend>
          <div className="grid justify-center gap-5 [grid-template-columns:repeat(auto-fit,minmax(0,310px))]">
            {ROLES.map((r) => {
              const Sym = SYM[r.id]
              return (
              <label key={r.id} className="role-card" data-on={role === r.id}>
                <input type="radio" name="role" value={r.id} checked={role === r.id} onChange={() => setRole(r.id)} className="sr-only" />
                <span className="flex items-center justify-between gap-3">
                  <span className="role-title">{r.title}</span>
                  <span className="role-sym role-coin" aria-hidden><Sym className="size-[18px]" /></span>
                </span>
                <span className="body-m text-muted">{r.text}</span>
                <span className="overline mt-1">что получите</span>
                <ul className="body-s list-disc space-y-1 pl-4 marker:text-faint">{r.gets.map((g) => <li key={g}>{g}</li>)}</ul>
              </label>
              )
            })}
          </div>
        </fieldset>

        {role === 'entrepreneur' && (
          <fieldset className="zone grid gap-4 !p-5 md:grid-cols-2">
            <legend className="float-left mb-1 w-full text-h3 font-semibold md:col-span-2">Профиль бизнеса <span className="text-small font-normal text-muted">(необязательно)</span></legend>
            <p className="hint md:col-span-2">Профиль уточняет риски. «Не знаю» не означает «нет»: такой ответ не используется как факт.</p>
            <Field id="sphere" label="Сфера деятельности"><input id="sphere" className="input" value={profile.sphere} maxLength={200} onChange={(e) => setProfile({ ...profile, sphere: e.target.value })} placeholder="Например, онлайн-школа программирования" /></Field>
            {([['has_site_or_app', 'Есть сайт или приложение'], ['processes_pd', 'Работаете с персональными данными'], ['mailings', 'Ведёте рассылки']] as const).map(([k, label]) => (
              <Field key={k} id={k} label={label}>
                <select id={k} className="input" value={profile[k]} onChange={(e) => setProfile({ ...profile, [k]: e.target.value as Tri })}>{TRI.map((o) => <option key={o.v} value={o.v}>{o.t}</option>)}</select>
              </Field>
            ))}
            <Field id="srv" label="Где размещены серверы">
              <select id="srv" className="input" value={profile.servers_location} onChange={(e) => setProfile({ ...profile, servers_location: e.target.value as typeof profile.servers_location })}>
                <option value="unknown">Не знаю</option><option value="ru">В России</option><option value="abroad">За рубежом</option><option value="both">И там, и там</option>
              </select>
            </Field>
          </fieldset>
        )}

        <div className="grid gap-4 md:grid-cols-2">
          <Field id="title" label="Название сессии" hint="Если оставить пустым, название будет создано автоматически."><input id="title" className="input" value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} /></Field>
          <Field id="asof" label="Дата правового среза" hint="Поиск использует редакции, действующие на эту дату."><input id="asof" className="input" type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} /></Field>
        </div>
        {create.error && <Banner tone="error">{errorText(create.error)}</Banner>}
        <div className="flex items-center gap-3">
          <button className="btn btn-primary btn-lg" type="submit" disabled={create.isPending} aria-busy={create.isPending || undefined}>{`Начать как «${ROLE_RU[role]}»`}</button>
          <span className="hint">Смена роли позже создаст новую сессию; прежняя сохранится.</span>
        </div>
      </form>

      {recent.data && recent.data.length > 0 && (
        <section aria-labelledby="cont" className="space-y-2">
          <h2 id="cont" className="text-h3">Продолжить</h2>
          <ul className="zone divide-y divide-line-soft overflow-hidden !p-0">
            {recent.data.slice(0, 5).map((s) => (
              <li key={s.id}><Link to={`/s/${s.id}`} className="flex min-h-11 items-center justify-between gap-3 px-4 py-2.5 no-underline hover:bg-hover"><span className="truncate text-ink">{s.title}</span><span className="shrink-0 text-small text-muted">{ROLE_RU[s.role]} · сообщений: {s.messages_count} · рисков: {s.active_risks}</span></Link></li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}
