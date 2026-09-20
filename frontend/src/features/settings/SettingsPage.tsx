import { useMutation, useQueryClient } from '@tanstack/react-query'
import { LogOut } from 'lucide-react'
import { useState, type FormEvent, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { Banner, ErrorNote, Skeleton } from '../../components/States'
import { Field, Spinner } from '../../components/ui'
import { errorText, post, setCsrf } from '../../lib/api'
import type { components } from '../../lib/api-types'
import { useDiagnostics } from '../../lib/queries'

function Row({ k, children }: { k: string; children: ReactNode }) {
  return <div className="flex justify-between gap-4 border-b border-line py-1.5 text-small"><dt className="text-muted">{k}</dt><dd className="text-right">{children}</dd></div>
}
const ok = (v: boolean | undefined) => (v ? 'Работает' : 'Недоступно')

export function SettingsPage() {
  document.title = 'Настройки — DoorAIn'
  const d = useDiagnostics()
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
  return (
    <div className="mx-auto max-w-3xl space-y-8 px-4 py-6">
      <h1>Настройки</h1>
      <section aria-labelledby="diag" className="space-y-2">
        <h2 id="diag" className="text-h3">Диагностика системы</h2>
        {d.isLoading && <Skeleton lines={6} />}
        {d.isError && <ErrorNote error={d.error} onRetry={() => d.refetch()} />}
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
          <Field id="cur" label="Текущий пароль"><input id="cur" className="input" type="password" autoComplete="current-password" value={cur} onChange={(e) => setCur(e.target.value)} required /></Field>
          <Field id="new" label="Новый пароль" hint="Не короче 12 символов. После смены все остальные сессии входа будут завершены."><input id="new" className="input" type="password" autoComplete="new-password" minLength={12} value={next} onChange={(e) => setNext(e.target.value)} required /></Field>
          {change.error && <Banner tone="error">{errorText(change.error)}</Banner>}
          {done && <Banner>Пароль изменён. Остальные сессии входа отозваны.</Banner>}
          <button className="btn btn-primary" type="submit" disabled={change.isPending}>{change.isPending ? <Spinner label="Сохраняем…" /> : 'Сменить пароль'}</button>
        </form>
      </section>
      <section className="space-y-2">
        <h2 className="text-h3">Сессия входа</h2>
        <button className="btn" onClick={() => logout.mutate()} disabled={logout.isPending}><LogOut className="size-4" aria-hidden />Выйти</button>
      </section>
    </div>
  )
}
