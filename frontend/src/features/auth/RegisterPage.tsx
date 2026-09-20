import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { DoorArt } from '../../components/art'
import { Banner } from '../../components/States'
import { Field, Spinner } from '../../components/ui'
import { ApiError, errorText, post, setCsrf } from '../../lib/api'
import type { components } from '../../lib/api-types'
import { keys } from '../../lib/queries'

/** Регистрация возможна только по коду приглашения от владельца: публичной саморегистрации нет. */
export function RegisterPage() {
  const nav = useNavigate()
  const qc = useQueryClient()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const reg = useMutation({
    mutationFn: () => post<components['schemas']['AuthOut']>('/auth/register', { username, password, invite_code: code }),
    onSuccess: (d) => {
      setCsrf(d.csrf_token)
      qc.setQueryData(keys.me, d)
      nav('/', { replace: true })
    },
  })
  const submit = (e: FormEvent) => { e.preventDefault(); if (username && password && code) reg.mutate() }
  document.title = 'Регистрация — DoorAIn'
  const err = reg.error
  return (
    <div className="mx-auto grid min-h-dvh max-w-4xl items-center gap-8 px-4 py-8 md:grid-cols-[1fr_360px]">
      <div className="hidden md:block">
        <DoorArt className="h-56 w-auto text-ink" aria-hidden="true" />
        <h1 className="mt-4">DoorAIn</h1>
        <p className="mt-2 max-w-md text-muted">Ответы с проверяемыми источниками, накопительный портрет консультации и объяснимая таблица рисков. Обработка выполняется на сервере владельца.</p>
      </div>
      <form onSubmit={submit} className="space-y-4" aria-label="Регистрация">
        <div className="md:hidden"><h1>DoorAIn</h1></div>
        <h2>Регистрация по приглашению</h2>
        <Field id="ic" label="Код приглашения" hint="Код выдаёт владелец сервиса"><input id="ic" className="input" value={code} onChange={(e) => setCode(e.target.value)} required aria-invalid={err instanceof ApiError && err.code === 'invalid_invite'} /></Field>
        <Field id="ru" label="Имя пользователя" hint="3–64 символа: латиница, цифры, точка, дефис или подчёркивание"><input id="ru" className="input" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required /></Field>
        <Field id="rp" label="Пароль" hint="Не короче 12 символов"><input id="rp" className="input" type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={12} /></Field>
        {err && <Banner tone="error">{err instanceof ApiError && err.status === 429 ? 'Слишком много попыток. Повторите позже.' : errorText(err)}</Banner>}
        <button className="btn btn-primary w-full" type="submit" disabled={reg.isPending}>{reg.isPending ? <Spinner label="Создаём учётную запись…" /> : 'Создать учётную запись'}</button>
        <p className="hint">Уже есть доступ? <Link to="/login">Войти</Link></p>
        <p className="hint">Ответы носят информационный характер и не заменяют профессиональную юридическую помощь.</p>
      </form>
    </div>
  )
}
