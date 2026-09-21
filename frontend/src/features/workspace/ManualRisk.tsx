import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Dialog } from '../../components/Dialog'
import { ErrorNote } from '../../components/States'
import { Field } from '../../components/ui'
import type { Risk } from '../../lib/api'
import { post } from '../../lib/api'
import { keys } from '../../lib/queries'
import { LEVEL_RU, levelOf } from '../../lib/risk'

const SCALE = [1, 2, 3, 4, 5]

/** Свой риск: пользователь добавляет его без нормативного основания; помечается как пользовательский. */
export function ManualRiskDialog({ sessionId, open, onClose }: { sessionId: string; open: boolean; onClose: () => void }) {
  const qc = useQueryClient()
  const [f, setF] = useState({ title: '', description: '', p: 3, s: 3, consequences: '', recommendation: '' })
  const create = useMutation({
    mutationFn: () => post<Risk>(`/sessions/${sessionId}/risks`, f),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: keys.risks(sessionId) }); setF({ title: '', description: '', p: 3, s: 3, consequences: '', recommendation: '' }); onClose() },
  })
  const lv = levelOf(f.p * f.s)
  return (
    <Dialog open={open} onClose={onClose} title="Добавить свой риск">
      <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); create.mutate() }}>
        <p className="hint">Риск без нормативного основания помечается как ваш и не участвует в оценке качества извлечения. Агент не перезаписывает вашу оценку.</p>
        <Field id="mr-t" label="Название — от последствия"><input id="mr-t" className="input" required minLength={3} maxLength={300} value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} placeholder="Например: претензии подрядчика к правам на код" /></Field>
        <Field id="mr-d" label="Суть"><textarea id="mr-d" className="input min-h-16" maxLength={500} value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field>
        <div className="grid grid-cols-2 gap-3">
          <Field id="mr-p" label="Вероятность P"><select id="mr-p" className="input" value={f.p} onChange={(e) => setF({ ...f, p: Number(e.target.value) })}>{SCALE.map((x) => <option key={x} value={x}>{x}</option>)}</select></Field>
          <Field id="mr-s" label="Тяжесть S"><select id="mr-s" className="input" value={f.s} onChange={(e) => setF({ ...f, s: Number(e.target.value) })}>{SCALE.map((x) => <option key={x} value={x}>{x}</option>)}</select></Field>
        </div>
        <p className="mono-m">P × S = {f.p * f.s}{lv ? ` · ${LEVEL_RU[lv].toLowerCase()}` : ''}</p>
        <Field id="mr-c" label="Последствия"><input id="mr-c" className="input" maxLength={1000} value={f.consequences} onChange={(e) => setF({ ...f, consequences: e.target.value })} /></Field>
        <Field id="mr-r" label="Что сделать"><input id="mr-r" className="input" maxLength={1000} value={f.recommendation} onChange={(e) => setF({ ...f, recommendation: e.target.value })} placeholder="Действие и срок" /></Field>
        {create.error && <ErrorNote error={create.error} />}
        <div className="flex gap-2"><button className="btn btn-primary" type="submit" disabled={create.isPending || f.title.trim().length < 3}>Добавить риск</button><button className="btn" type="button" onClick={onClose}>Отмена</button></div>
      </form>
    </Dialog>
  )
}
