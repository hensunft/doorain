import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { Banner } from '../../components/States'
import { Button, Spinner } from '../../components/ui'
import type { Risk } from '../../lib/api'
import { errorText, newRequestId, post } from '../../lib/api'
import type { components } from '../../lib/api-types'
import { keys } from '../../lib/queries'

export type ClosureResult = components['schemas']['ClosureResult']
export type ClosureAttempt = components['schemas']['ClosureAttemptOut']

export const VERIFICATION_RU = { user_claim: 'со слов пользователя, независимой проверки нет', corroborated: 'подтверждено фактами, которые вы сообщили в сессии' } as const

/** Итог проверки ответа: одинаково в плане, карточке и детали риска. */
export function ClosureOutcome({ a }: { a: ClosureAttempt }) {
  if (a.state === 'failed') return <Banner tone="warn">Проверка не выполнена: {a.explanation} Риск остаётся открытым — повторите позже.</Banner>
  if (a.state === 'stale') return <Banner tone="warn">{a.explanation}</Banner>
  if (a.decision === 'close') {
    return (
      <Banner>
        <b>{a.resolution_kind === 'not_applicable' ? 'Риск отмечен как неприменимый' : 'Риск закрыт'}</b> — {a.verification ? VERIFICATION_RU[a.verification] : ''}. {a.explanation}
        {a.citations.length > 0 && <span className="mt-1 block text-muted">Основание: {a.citations.map((c) => c.label).join('; ')}</span>}
      </Banner>
    )
  }
  if (a.decision === 'other_risk') return <Banner tone="warn">Похоже, ответ о другой проблеме: «{a.question}». Исходный риск остаётся открытым. Опишите новую ситуацию в диалоге — новый риск появится, только если для него найдётся норма в базе знаний. {a.explanation}</Banner>
  if (a.decision === 'keep_open') return <Banner tone="warn">Риск остаётся открытым. {a.explanation}</Banner>
  return <Banner tone="warn"><b>Нужно уточнение:</b> {a.question} <span className="block text-muted">{a.explanation}</span></Banner>
}

/** «Предложить закрытие»: ответ оценивает сервер (модель + проверки). До результата риск активен, повторный клик заблокирован;
 *  повтор после обрыва сети отправляет тот же ключ идемпотентности и не создаёт вторую проверку. */
export function ClosureForm({ risk, sessionId, source, notApplicable = false, onCancel }: {
  risk: Risk
  sessionId: string
  source: 'plan' | 'detail'
  notApplicable?: boolean
  onCancel?: () => void
}) {
  const qc = useQueryClient()
  const [answer, setAnswer] = useState('')
  const key = useRef<{ text: string; id: string } | null>(null)
  const check = useMutation({
    mutationFn: () => {
      const text = answer.trim()
      if (key.current?.text !== text) key.current = { text, id: newRequestId() }
      return post<ClosureResult>(`/risks/${risk.id}/closure`, { version: risk.version, answer: text, source, idempotency_key: key.current.id })
    },
    onSuccess: () => {
      key.current = null  // ответ получен: следующая попытка — новая проверка; ключ сохраняется только при обрыве сети
      void qc.invalidateQueries({ queryKey: keys.risks(sessionId) })
      void qc.invalidateQueries({ queryKey: keys.graph(sessionId) })
      void qc.invalidateQueries({ queryKey: keys.risk(risk.id) })
    },
  })
  const id = `cl-${source}-${risk.id}`
  const result = check.data
  return (
    <div className="mt-2 space-y-2">
      {result && <div aria-live="polite"><ClosureOutcome a={result} /></div>}
      {result?.applied ? null : (
        <form className="space-y-2" onSubmit={(e) => { e.preventDefault(); if (answer.trim() && !check.isPending) check.mutate() }}>
          <label className="label" htmlFor={id}>{notApplicable ? 'Почему риск к вам не относится' : 'Что именно сделано'}</label>
          <textarea
            id={id} className="input min-h-20" value={answer} maxLength={2000} required autoFocus
            onChange={(e) => setAnswer(e.target.value)} disabled={check.isPending}
            placeholder={notApplicable ? 'Например: сайта нет, персональные данные не собираем' : 'Например: опубликовали политику обработки персональных данных'}
            aria-describedby={`${id}-hint`}
          />
          <p id={`${id}-hint`} className="hint">Достаточно написать, что сделано. Слова «готово» или «решено» без предмета риск не закрывают. Закрытие отмечается как «со слов пользователя».</p>
          <div className="flex flex-wrap items-center gap-2">
            <Button type="submit" loading={check.isPending} disabled={!answer.trim()}>{check.isPending ? 'Проверяем ответ…' : 'Проверить и закрыть'}</Button>
            {onCancel && <Button variant="tertiary" onClick={onCancel} disabled={check.isPending}>Отмена</Button>}
            {check.isPending && <Spinner label="Проверяем ответ по риску и нормам" />}
          </div>
        </form>
      )}
      {check.error && <p role="alert" className="body-s text-risk-high">{errorText(check.error)}</p>}
    </div>
  )
}
