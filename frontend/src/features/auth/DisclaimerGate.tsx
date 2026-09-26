import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { post } from '../../lib/api'
import type { components } from '../../lib/api-types'
import { keys } from '../../lib/queries'
import { useLegal } from '../legal/LegalPages'
import { AuthFrame } from './LoginPage'

/** Первый вход: короткое честное уведомление до работы с сервисом; ознакомление фиксируется на сервере.
 *  Доступ администратора к обращениям описан одной фразой со ссылкой на Политику, без повторов на рабочих экранах. */
export function DisclaimerGate({ accepted, children }: { accepted: boolean; children: ReactNode }) {
  const qc = useQueryClient()
  const legal = useLegal()
  const [read, setRead] = useState(false)
  const accept = useMutation({
    mutationFn: () => post<components['schemas']['AuthOut']>('/auth/accept-disclaimer', {}),
    onSuccess: (d) => qc.setQueryData(keys.me, d),
  })
  if (accepted) return <>{children}</>
  return (
    <AuthFrame title="Прежде чем начать">
      <div className="body-m space-y-3">
        <p>DoorAIn отвечает <strong>только по загруженной базе знаний</strong> и указывает источник каждого вывода. Сервис не оказывает юридических услуг: ответы носят информационный характер и не заменяют юридическую консультацию.</p>
        <p>Оценка рисков выполняется по экспериментальной методике и не является юридическим заключением.</p>
        {legal.data?.owner_can_read_user_sessions !== false && <p>Администратор может просматривать обращения для сопровождения сервиса; такие просмотры фиксируются. Подробнее — в <Link to="/privacy">Политике обработки персональных данных</Link>.</p>}
      </div>
      <label className="mt-5 flex min-h-11 cursor-pointer items-center gap-3">
        <input type="checkbox" className="mt-0.5 size-5 shrink-0 accent-[var(--brand)]" checked={read} onChange={(e) => setRead(e.target.checked)} />
        <span className="body-m">Я прочитал(а) и понимаю, что ответы носят информационный характер</span>
      </label>
      <button className="btn btn-primary btn-lg mt-5 w-full" onClick={() => accept.mutate()} disabled={!read || accept.isPending} aria-busy={accept.isPending || undefined}>Продолжить</button>
    </AuthFrame>
  )
}
