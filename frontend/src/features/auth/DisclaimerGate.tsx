import { useMutation, useQueryClient } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { post } from '../../lib/api'
import type { components } from '../../lib/api-types'
import { keys } from '../../lib/queries'
import { Spinner } from '../../components/ui'

/** Первый вход: дисклеймер показывается до работы с сервисом, факт ознакомления фиксируется на сервере. */
export function DisclaimerGate({ accepted, ownerCanRead, children }: { accepted: boolean; ownerCanRead: boolean; children: ReactNode }) {
  const qc = useQueryClient()
  const accept = useMutation({
    mutationFn: () => post<components['schemas']['AuthOut']>('/auth/accept-disclaimer', {}),
    onSuccess: (d) => qc.setQueryData(keys.me, d),
  })
  if (accepted) return <>{children}</>
  return (
    <div className="mx-auto max-w-2xl px-4 py-10">
      <h1>Прежде чем начать</h1>
      <div className="mt-4 space-y-3 text-ink">
        <p>DoorAIn отвечает <strong>только по загруженной базе знаний</strong> и указывает источник каждого вывода. Ответы носят информационный характер, сервис не оказывает юридических услуг и не заменяет юриста.</p>
        <p>Оценка рисков выполняется по экспериментальной методике и не является юридическим заключением. Для конкретной ситуации обратитесь к юристу.</p>
        <p>Ваши сессии, портрет и риски видны только вам{ownerCanRead ? ' и владельцу сервиса' : ''}. {ownerCanRead && 'Каждый просмотр владельцем записывается в журнал.'} Не вводите сведения, которые не готовы доверить владельцу сервера.</p>
      </div>
      <button className="btn btn-primary mt-6" onClick={() => accept.mutate()} disabled={accept.isPending}>
        {accept.isPending ? <Spinner label="Сохраняем…" /> : 'Я ознакомился и продолжаю'}
      </button>
    </div>
  )
}
