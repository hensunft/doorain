import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Download, FileDown, GraduationCap } from 'lucide-react'
import { useState } from 'react'
import { Dialog } from '../../components/Dialog'
import { Banner, ErrorNote, Skeleton } from '../../components/States'
import { Button, Spinner } from '../../components/ui'
import type { Export, Quiz, QuizAttempt, Session } from '../../lib/api'
import { ApiError, errorText, get, post } from '../../lib/api'
import { keys, useQuiz } from '../../lib/queries'
import { useSelection } from '../../lib/selection'

/** Самопроверка студента: 3–5 вопросов по материалам сессии; ошибки → учебные риски, не деловые. */
export function QuizDialog({ session, open, onClose }: { session: Session; open: boolean; onClose: () => void }) {
  const qc = useQueryClient()
  const { openCitation } = useSelection()
  const [quizId, setQuizId] = useState<string | null>(null)
  const [answers, setAnswers] = useState<Record<string, number>>({})
  const [result, setResult] = useState<QuizAttempt | null>(null)
  const quiz = useQuiz(quizId)
  const create = useMutation({ mutationFn: () => post<Quiz>(`/sessions/${session.id}/quiz`), onSuccess: (q) => { setQuizId(q.id); setAnswers({}); setResult(null) } })
  const submit = useMutation({
    mutationFn: () => post<QuizAttempt>(`/quizzes/${quizId}/attempts`, { answers }),
    onSuccess: (r) => { setResult(r); void qc.invalidateQueries({ queryKey: keys.risks(session.id) }); void qc.invalidateQueries({ queryKey: keys.graph(session.id) }) },
  })
  const q = quiz.data
  return (
    <Dialog open={open} onClose={onClose} title="Самопроверка" variant="modal" footer={result ? <Button onClick={() => { setQuizId(null); setResult(null) }}>Новая самопроверка</Button> : undefined}>
      <div className="space-y-4 text-small">
        {!quizId && (
          <>
            <p>Вопросы составляются по источникам, которые уже использовались в этой сессии. Оценка выставляется только за данные вами ответы; факт обращения оценкой не считается.</p>
            {create.error && <ErrorNote error={create.error} />}
            <Button variant="primary" onClick={() => create.mutate()} disabled={create.isPending}><GraduationCap className="size-4" aria-hidden />{create.isPending ? 'Готовим…' : 'Составить вопросы'}</Button>
          </>
        )}
        {quizId && q?.status === 'queued' && <Spinner label="Составляю вопросы локальной моделью…" />}
        {q?.status === 'failed' && <Banner tone="error">{q.error ?? 'Не удалось составить вопросы'}</Banner>}
        {q?.status === 'ready' && !result && (
          <form onSubmit={(e) => { e.preventDefault(); submit.mutate() }} className="space-y-4">
            {q.questions.map((x, i) => (
              <fieldset key={x.id} className="space-y-1">
                <legend className="font-medium">{i + 1}. {x.question}</legend>
                {x.options.map((o, j) => <label key={j} className="flex cursor-pointer items-start gap-2 rounded-md px-2 py-1 hover:bg-sidebar"><input type="radio" name={x.id} checked={answers[x.id] === j} onChange={() => setAnswers({ ...answers, [x.id]: j })} className="mt-1" /><span>{o}</span></label>)}
              </fieldset>
            ))}
            {submit.error && <ErrorNote error={submit.error} />}
            <Button variant="primary" type="submit" disabled={submit.isPending || !Object.keys(answers).length}>Проверить ответы</Button>
          </form>
        )}
        {result && q && (
          <div className="space-y-3">
            <p className="font-medium">Верно: {result.correct} из {result.total}</p>
            {result.results.map((r) => {
              const question = q.questions.find((x) => x.id === r['question_id'])
              const ok = r['correct'] === true
              return (
                <div key={String(r['question_id'])} className="rounded-md border border-line p-3">
                  <p className="font-medium">{question?.question}</p>
                  <p className={ok ? 'text-risk-low' : 'text-risk-high'}>{ok ? 'Верно' : `Неверно. Правильный ответ: ${question?.options[Number(r['correct_index'])]}`}</p>
                  <p>{String(r['explanation'])}</p>
                  {typeof r['citation_id'] === 'string' && <button type="button" className="chip mt-1" onClick={() => openCitation(String(r['citation_id']))}>Открыть источник</button>}
                  {!ok && <p className="hint mt-1">Ошибка сохранена как учебный риск понимания (не как деловой риск).</p>}
                </div>
              )
            })}
          </div>
        )}
      </div>
    </Dialog>
  )
}

/** Экспорт «Правового слепка сессии» в PDF из согласованного снимка. Реплик диалога в документе нет; неполный снимок — только по явному выбору. */
export function ExportDialog({ session, open, onClose }: { session: Session; open: boolean; onClose: () => void }) {
  const [exportId, setExportId] = useState<string | null>(null)
  const create = useMutation({ mutationFn: (allow: boolean) => post<Export>(`/sessions/${session.id}/exports`, { allow_incomplete: allow }), onSuccess: (e) => setExportId(e.id) })
  const status = useQuery({ queryKey: ['export', exportId], queryFn: () => get<Export>(`/exports/${exportId}`), enabled: !!exportId, refetchInterval: (q) => (q.state.data && (q.state.data.status === 'ready' || q.state.data.status === 'failed') ? false : 1200) })
  const past = useQuery({ queryKey: ['exports', session.id, open], queryFn: () => get<Export[]>(`/sessions/${session.id}/exports`), enabled: open })
  const pending = create.error instanceof ApiError && create.error.code === 'analysis_pending'
  const ex = status.data
  return (
    <Dialog open={open} onClose={onClose} title="Экспорт портрета в PDF">
      <div className="space-y-4 text-small">
        <p>«Правовой слепок сессии»: сводка, граф-слепок, матрица и карточки рисков, нормативные основания и методика оценки. Реплик диалога в документе нет. PDF собирается из снимка на момент запроса и не меняется после обновления корпуса.</p>
        {pending && (
          <Banner tone="warn" action={<Button onClick={() => create.mutate(true)}>Выгрузить неполный</Button>}>
            Анализ сессии ещё выполняется или завершился ошибкой. Дождитесь завершения либо явно выгрузите неполный снимок (он будет помечен в PDF).
          </Banner>
        )}
        {create.error && !pending && <ErrorNote error={create.error} />}
        {!exportId && <Button variant="primary" onClick={() => create.mutate(false)} disabled={create.isPending}><FileDown className="size-4" aria-hidden />{create.isPending ? 'Создаём…' : 'Сформировать PDF'}</Button>}
        {exportId && !ex && <Skeleton lines={2} />}
        {ex && (ex.status === 'queued' || ex.status === 'running') && <Spinner label="Формирую PDF…" />}
        {ex?.status === 'failed' && <Banner tone="error">{ex.error ?? errorText(null)}</Banner>}
        {ex?.status === 'ready' && (
          <div className="space-y-2">
            {ex.incomplete && <Banner tone="warn">Это неполный снимок: он помечен в документе.</Banner>}
            <a className="btn btn-primary no-underline" href={`/api/v1/exports/${ex.id}/download`}><Download className="size-4" aria-hidden />Скачать PDF ({Math.round((ex.size ?? 0) / 1024)} КБ)</a>
            <Button variant="quiet" onClick={() => setExportId(null)}>Сформировать ещё раз</Button>
          </div>
        )}
        {past.data && past.data.length > 0 && (
          <section><h3 className="mb-1 text-small font-semibold">Прежние выгрузки</h3>
            <ul className="space-y-1">{past.data.filter((p) => p.status === 'ready').slice(0, 5).map((p) => <li key={p.id}><a href={`/api/v1/exports/${p.id}/download`}>{new Date(p.created_at).toLocaleString('ru-RU')}{p.incomplete ? ' (неполный)' : ''}</a></li>)}</ul>
          </section>
        )}
      </div>
    </Dialog>
  )
}
