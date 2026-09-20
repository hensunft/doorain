import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { DoorArt } from '../../components/art'
import { Banner } from '../../components/States'
import { Field, Spinner } from '../../components/ui'
import { ApiError, errorText, post, setCsrf } from '../../lib/api'
import type { components } from '../../lib/api-types'
import { keys } from '../../lib/queries'

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
    <div className="mx-auto grid min-h-dvh max-w-4xl items-center gap-8 px-4 py-8 md:grid-cols-[1fr_360px]">
      <div className="hidden md:block">
        <DoorArt className="h-56 w-auto text-ink" aria-hidden="true" />
        <h1 className="mt-4">DoorAIn</h1>
        <p className="mt-2 max-w-md text-muted">Ответы с проверяемыми источниками, накопительный портрет вашей консультации и объяснимая таблица рисков. Обработка выполняется на вашем сервере.</p>
      </div>
      <form onSubmit={submit} className="space-y-4" aria-label="Вход">
        <div className="md:hidden"><h1>DoorAIn</h1></div>
        <h2>Вход владельца</h2>
        <Field id="u" label="Имя пользователя"><input id="u" className="input" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required /></Field>
        <Field id="p" label="Пароль"><input id="p" className="input" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required aria-invalid={!!err} /></Field>
        {err && <Banner tone="error">{err instanceof ApiError && err.status === 429 ? 'Слишком много попыток входа. Повторите позже.' : errorText(err)}</Banner>}
        <button className="btn btn-primary w-full" type="submit" disabled={login.isPending}>{login.isPending ? <Spinner label="Входим…" /> : 'Войти'}</button>
        <p className="hint">Регистрации нет. Учётную запись владельца создаёт администратор сервера командой <code>create-owner</code>.</p>
        <p className="hint">Ответы носят информационный характер и не заменяют профессиональную юридическую помощь.</p>
      </form>
    </div>
  )
}
