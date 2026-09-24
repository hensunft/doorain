import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Banner } from '../../components/States'
import { Field } from '../../components/ui'
import { ApiError, errorText, post, setCsrf } from '../../lib/api'
import type { components } from '../../lib/api-types'
import { keys } from '../../lib/queries'
import { AuthFrame } from './LoginPage'

const LOGIN_RE = /^[a-z0-9._-]{3,64}$/
const NAME_RE = /^[\p{L}]+(?:[ '\-.][\p{L}]+)*\.?$/u
const EMAIL_RE = /^[^@\s]{1,64}@[^@\s]{1,150}\.[^@\s.]{2,}$/
const MIN_PASSWORD = 12

type Form = { code: string; username: string; first: string; last: string; email: string; password: string; repeat: string; terms: boolean; pd: boolean }

/** Проверки дублируют серверные для быстрых подсказок; решает сервер. */
export function validate(f: Form): Partial<Record<keyof Form, string>> {
  const e: Partial<Record<keyof Form, string>> = {}
  if (!f.code.trim()) e.code = 'Введите код приглашения'
  if (!LOGIN_RE.test(f.username.trim().toLowerCase())) e.username = '3–64 символа: латиница, цифры, точка, дефис или подчёркивание'
  if (!NAME_RE.test(f.first.trim().replace(/\s+/g, ' ')) || f.first.trim().length > 80) e.first = 'Только буквы, пробел, дефис или апостроф'
  if (!NAME_RE.test(f.last.trim().replace(/\s+/g, ' ')) || f.last.trim().length > 80) e.last = 'Только буквы, пробел, дефис или апостроф'
  if (!EMAIL_RE.test(f.email.trim()) || f.email.trim().length > 200) e.email = 'Адрес вида name@example.com'
  if (f.password.length < MIN_PASSWORD) e.password = `Не короче ${MIN_PASSWORD} символов`
  if (f.repeat !== f.password) e.repeat = 'Пароли не совпадают'
  if (!f.terms) e.terms = 'Нужно ознакомиться с Условиями и Политикой'
  if (!f.pd) e.pd = 'Без согласия на обработку данных учётную запись создать нельзя'
  return e
}

/** Регистрация возможна только по коду приглашения: публичной саморегистрации нет. Ссылка из админки передаёт код во фрагменте (#code=…),
 *  который не уходит на сервер и в журналы; после чтения фрагмент убирается из адресной строки. */
export function RegisterPage() {
  const nav = useNavigate()
  const qc = useQueryClient()
  const [f, setF] = useState<Form>({ code: '', username: '', first: '', last: '', email: '', password: '', repeat: '', terms: false, pd: false })
  const [touched, setTouched] = useState(false)
  useEffect(() => {
    const m = /(?:^|&)code=([^&]+)/.exec(window.location.hash.slice(1))
    if (m?.[1]) {
      setF((x) => ({ ...x, code: decodeURIComponent(m[1] ?? '') }))
      window.history.replaceState(null, '', window.location.pathname)
    }
  }, [])
  const reg = useMutation({
    mutationFn: () => post<components['schemas']['AuthOut']>('/auth/register', {
      username: f.username.trim().toLowerCase(), first_name: f.first.trim(), last_name: f.last.trim(), email: f.email.trim(),
      password: f.password, password_repeat: f.repeat, invite_code: f.code.trim(), accept_terms: f.terms, accept_pd: f.pd,
    }),
    onSuccess: (d) => {
      setCsrf(d.csrf_token)
      qc.setQueryData(keys.me, d)
      nav('/', { replace: true })
    },
  })
  const errs = validate(f)
  const show = (k: keyof Form) => (touched ? errs[k] : undefined)
  const submit = (e: FormEvent) => { e.preventDefault(); setTouched(true); if (!Object.keys(errs).length) reg.mutate() }
  document.title = 'Регистрация — DoorAIn'
  const err = reg.error
  const code = err instanceof ApiError ? err.code : ''
  const set = (k: keyof Form) => (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value })
  const field = (k: keyof Form, id: string, label: string, props: React.InputHTMLAttributes<HTMLInputElement>, hint?: string) => (
    <Field id={id} label={label} hint={show(k) ?? hint}>
      <input id={id} className="input" value={f[k] as string} onChange={set(k)} aria-invalid={!!show(k) || undefined} {...props} />
    </Field>
  )
  return (
    <AuthFrame title="Регистрация по приглашению" width={520}>
      <form onSubmit={submit} noValidate className="space-y-4" aria-label="Регистрация">
        {field('code', 'ic', 'Код приглашения', { required: true, autoComplete: 'off', 'aria-invalid': code === 'invalid_invite' || !!show('code') || undefined }, 'Код выдаёт администратор; он действует один раз')}
        {field('username', 'ru', 'Логин', { required: true, autoComplete: 'username', maxLength: 64 }, 'Постоянный идентификатор для входа: латиница, цифры, точка, дефис, подчёркивание. Изменить его позже нельзя')}
        <div className="grid gap-4 sm:grid-cols-2">
          {field('first', 'rf', 'Имя', { required: true, autoComplete: 'given-name', maxLength: 80 })}
          {field('last', 'rl', 'Фамилия', { required: true, autoComplete: 'family-name', maxLength: 80 })}
        </div>
        {field('email', 're', 'Электронная почта', { required: true, type: 'email', autoComplete: 'email', maxLength: 200 }, 'Письмом не подтверждается; нужна для связи по вашей учётной записи')}
        <div className="grid gap-4 sm:grid-cols-2">
          {field('password', 'rp', 'Пароль', { required: true, type: 'password', autoComplete: 'new-password', minLength: MIN_PASSWORD, maxLength: 256 }, `Не короче ${MIN_PASSWORD} символов`)}
          {field('repeat', 'rr', 'Повтор пароля', { required: true, type: 'password', autoComplete: 'new-password', maxLength: 256 })}
        </div>
        <p className="hint">Администратор может просматривать обращения для сопровождения сервиса; такие просмотры фиксируются. Подробнее — в <Link to="/privacy">Политике</Link>.</p>
        <label className="flex min-h-11 cursor-pointer items-start gap-3">
          <input type="checkbox" className="mt-1 size-5 shrink-0 accent-[var(--brand)]" checked={f.terms} onChange={set('terms')} aria-invalid={!!show('terms') || undefined} aria-describedby="terms-err" />
          <span className="body-m">Я ознакомлен(а) с <Link to="/terms" target="_blank">Условиями использования</Link> и <Link to="/privacy" target="_blank">Политикой обработки персональных данных</Link></span>
        </label>
        {show('terms') && <p id="terms-err" className="hint text-risk-high">{show('terms')}</p>}
        <label className="flex min-h-11 cursor-pointer items-start gap-3">
          <input type="checkbox" className="mt-1 size-5 shrink-0 accent-[var(--brand)]" checked={f.pd} onChange={set('pd')} aria-invalid={!!show('pd') || undefined} aria-describedby="pd-err" />
          <span className="body-m">Даю согласие на обработку моих персональных данных (логин, имя, фамилия, адрес почты, содержание обращений) для целей, указанных в Политике</span>
        </label>
        {show('pd') && <p id="pd-err" className="hint text-risk-high">{show('pd')}</p>}
        {err && <Banner tone="error">{err instanceof ApiError && err.status === 429 ? 'Слишком много попыток. Повторите позже.' : errorText(err)}</Banner>}
        <button className="btn btn-primary btn-lg w-full" type="submit" disabled={reg.isPending} aria-busy={reg.isPending || undefined}>Создать учётную запись</button>
        <p className="hint">Уже есть доступ? <Link to="/login">Войти</Link></p>
      </form>
    </AuthFrame>
  )
}
