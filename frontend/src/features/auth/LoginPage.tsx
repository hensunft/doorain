import { useMutation, useQueryClient } from '@tanstack/react-query'
import { UserPlus } from 'lucide-react'
import { useState, type FormEvent, type ReactNode } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { Footer } from '../../components/Footer'
import { Banner } from '../../components/States'
import { Field } from '../../components/ui'
import { ApiError, errorText, post, setCsrf } from '../../lib/api'
import type { components } from '../../lib/api-types'
import { keys } from '../../lib/queries'

/** Экран входа и регистрации: карточка по центру на фоне страницы, логотип Playfair, футер с правовыми ссылками в потоке. */
export function AuthFrame({ title, width = 420, children }: { title: string; width?: number; children: ReactNode }) {
  return (
    <div className="flex min-h-dvh flex-col items-center justify-center gap-6 bg-page px-4 py-10">
      <div className="card w-full !p-8" style={{ maxWidth: width }}>
        <p className="flex items-center gap-2"><img src="/favicon.svg" alt="" className="size-7" /><span className="display-m">DoorAIn</span></p>
        <h1 className="display-s mt-6">{title}</h1>
        <div className="mt-4">{children}</div>
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
