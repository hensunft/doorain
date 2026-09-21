import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
import { post } from '../../lib/api'
import type { components } from '../../lib/api-types'
import { keys } from '../../lib/queries'
import { AuthFrame } from './LoginPage'

/** Первый вход: дисклеймер показывается до работы с сервисом, продолжить можно только отметив ознакомление;
 *  факт ознакомления фиксируется на сервере. */
export function DisclaimerGate({ accepted, ownerCanRead, children }: { accepted: boolean; ownerCanRead: boolean; children: ReactNode }) {
  const qc = useQueryClient()
  const [read, setRead] = useState(false)
  const accept = useMutation({
    mutationFn: () => post<components['schemas']['AuthOut']>('/auth/accept-disclaimer', {}),
    onSuccess: (d) => qc.setQueryData(keys.me, d),
  })
  if (accepted) return <>{children}</>
  return (
    <AuthFrame title="Прежде чем начать" width={560}>
      <div className="body-m space-y-3">
        <p>DoorAIn отвечает <strong>только по загруженной базе знаний</strong> и указывает источник каждого вывода. Сервис не оказывает юридических услуг и не заменяет юриста.</p>
        <p>Оценка рисков выполняется по экспериментальной методике и не является юридическим заключением. Для конкретной ситуации обратитесь к юристу.</p>
        <p>Ваши сессии, портрет и риски видны только вам{ownerCanRead ? ' и владельцу сервиса' : ''}. {ownerCanRead && 'Каждый просмотр владельцем записывается в журнал.'} Не вводите сведения, которые не готовы доверить владельцу сервера.</p>
      </div>
      <label className="mt-5 flex min-h-11 cursor-pointer items-center gap-3">
        <input type="checkbox" className="mt-0.5 size-5 shrink-0 accent-[var(--brand)]" checked={read} onChange={(e) => setRead(e.target.checked)} />
        <span className="body-m">Я прочитал(а) и понимаю, что ответы носят информационный характер</span>
      </label>
      <button className="btn btn-primary btn-lg mt-5 w-full" onClick={() => accept.mutate()} disabled={!read || accept.isPending} aria-busy={accept.isPending || undefined}>Продолжить</button>
    </AuthFrame>
  )
}
