import { useMutation, useQueryClient } from '@tanstack/react-query'
import { UserPlus } from 'lucide-react'
import { useState, type FormEvent, type ReactNode } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { Footer } from '../../components/Footer'
import { DoorMark } from '../../components/DoorMark'
import { Medallion } from '../../components/Medallion'
import { Banner } from '../../components/States'
import { Field } from '../../components/ui'
import { ApiError, errorText, post, setCsrf } from '../../lib/api'
import type { components } from '../../lib/api-types'
import { keys } from '../../lib/queries'

/** Экран входа и регистрации: слева — медальон с весами (декоративный, на узком экране скрыт), справа — форма на стекле.
 *  Обе колонки фиксированной ширины, пара центрирована в окне; карточка входа и регистрации одной ширины — при переходе
 *  между маршрутами форма не сдвигается. Футер — в потоке, под формой. */
export function AuthFrame({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="flex min-h-dvh flex-col gap-6 px-4 py-8">
      <div className="grid flex-1 grid-cols-[minmax(0,30rem)] items-center justify-center gap-16 lg:grid-cols-[24rem_30rem] xl:gap-24">
        <div className="hidden flex-col items-center gap-10 text-center lg:flex" data-testid="auth-art">
          <div className="portrait-light"><Medallion size={320} /></div>
          <div className="space-y-3">
            <p className="overline">Цифровой правовой портрет</p>
            <p className="serif text-[28px] font-semibold leading-tight text-ink">Правовое положение — на одних весах: факты, нормы, риски</p>
            <p className="body-m text-muted">Каждый ответ опирается на источники, а сессия складывается в карту вашего правового положения: обязанности, связи, риски.</p>
          </div>
        </div>
        <div className="glass w-full max-w-[30rem] rounded-[var(--r-zone)] p-6 sm:p-8" data-testid="auth-card">
          <p className="flex items-center gap-2"><DoorMark className="size-7" /><span className="serif text-[24px] font-semibold">DoorAIn</span></p>
          <h1 className="display-m mt-6">{title}</h1>
          <div className="mt-5">{children}</div>
        </div>
      </div>
      <Footer className="w-full justify-center text-center" />
    </div>
  )
}

export function LoginPage() {
  const nav = useNavigate()
  const loc = useLocation()
  const qc = useQueryClient()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const login = useMutation({
    mutationFn: () => post<components['schemas']['AuthOut']>('/auth/login', { username, password }),
    onSuccess: (d) => {
      setCsrf(d.csrf_token)
      qc.setQueryData(keys.me, d)
      nav((loc.state as { from?: string } | null)?.from ?? '/', { replace: true })
    },
  })
  const submit = (e: FormEvent) => { e.preventDefault(); if (username && password) login.mutate() }
  document.title = 'Вход — DoorAIn'
  const err = login.error
  return (
    <AuthFrame title="Вход">
      <form onSubmit={submit} className="space-y-4" aria-label="Вход">
        <Field id="u" label="Логин"><input id="u" className="input" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required /></Field>
        <Field id="p" label="Пароль"><input id="p" className="input" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required aria-invalid={!!err} /></Field>
        {err && <Banner tone="error">{err instanceof ApiError && err.status === 429 ? 'Слишком много попыток входа. Повторите позже.' : errorText(err)}</Banner>}
        <button className="btn btn-primary btn-lg w-full" type="submit" disabled={login.isPending} aria-busy={login.isPending || undefined}>Войти</button>
      </form>
      <div className="mt-5 space-y-2 border-t border-line pt-4">
        <p className="hint">Нет учётной записи? Регистрация возможна только по коду приглашения от администратора.</p>
        <Link to="/register" className="btn btn-lg w-full no-underline"><UserPlus className="size-4" aria-hidden />Регистрация по приглашению</Link>
      </div>
    </AuthFrame>
  )
}
