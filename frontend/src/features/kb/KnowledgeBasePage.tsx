import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { EyeOff, FileUp, GitCompare, RefreshCw, Search, Trash2 } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Banner, EmptyState, ErrorNote, Skeleton } from '../../components/States'
import { Button, Field, Spinner } from '../../components/ui'
import type { ConfirmImport, Doc, Draft, SearchHit } from '../../lib/api'
import { ApiError, del, errorText, get, patch, post } from '../../lib/api'
import { todayISO } from '../../lib/date'
import { keys, useCorpus, useDocuments, useJobs, useManifest } from '../../lib/queries'

const STATE_RU: Record<string, string> = { missing: 'Нет', imported: 'Импортирован', indexed: 'Проиндексирован', verified: 'Проверен' }
const DOC_RU: Record<string, string> = { npa: 'НПА', textbook: 'Учебник', soft_law: 'Мягкое право' }
type Meta = Omit<ConfirmImport, 'topics' | 'build_index'> & { topics?: string[] }

function ImportWizard() {
  const qc = useQueryClient()
  const [draftId, setDraftId] = useState<string | null>(null)
  const [meta, setMeta] = useState<Meta>({ doc_type: 'npa', title: '' })
  const [filled, setFilled] = useState<string | null>(null)
  const upload = useMutation({
    mutationFn: async (file: File) => { const f = new FormData(); f.append('file', file); return post<Draft>('/corpus/uploads', f) },
    onSuccess: (d) => { setDraftId(d.id); setFilled(null) },
  })
  const draft = useQuery({ queryKey: ['draft', draftId], queryFn: () => get<Draft>(`/corpus/uploads/${draftId}`), enabled: !!draftId, refetchInterval: (q) => (q.state.data?.status === 'parsing' ? 1000 : false) })
  const d = draft.data
  if (d?.status === 'ready' && filled !== d.id) {
    const g = (d.preview['guess'] ?? {}) as Record<string, string | null>
    setFilled(d.id)
    setMeta({ doc_type: (g['doc_type'] as Meta['doc_type']) ?? 'npa', title: g['title'] ?? '', act_number: g['act_number'] ?? undefined, act_date: g['act_date'] ?? undefined, revision_date: g['revision_date'] ?? undefined })
  }
  const confirm = useMutation({
    mutationFn: () => post<{ revision_id: string; created: boolean }>(`/corpus/uploads/${draftId}/confirm`, { ...meta, topics: meta.topics ?? [], build_index: true }),
    onSuccess: () => { setDraftId(null); void qc.invalidateQueries({ queryKey: keys.documents }); void qc.invalidateQueries({ queryKey: keys.corpus }); void qc.invalidateQueries({ queryKey: keys.jobs }); void qc.invalidateQueries({ queryKey: keys.manifest }) },
  })
  const set = (k: keyof Meta, v: string) => setMeta({ ...meta, [k]: v || undefined })
  const stats = (d?.preview['stats'] ?? {}) as Record<string, number>
  const onFile = (e: FormEvent<HTMLInputElement>) => { const f = e.currentTarget.files?.[0]; if (f) upload.mutate(f); e.currentTarget.value = '' }
  return (
    <section aria-labelledby="imp" className="space-y-3 rounded-lg border border-line p-4">
      <h2 id="imp" className="text-h3">Импорт документа</h2>
      <p className="hint">Поддерживаются TXT, Markdown, HTML, PDF с текстовым слоем и DOCX. Скан без текста не принимается (OCR не входит в MVP). Тексты документов — данные, а не инструкции.</p>
      {!draftId && (
        <label className="btn w-fit cursor-pointer"><FileUp className="size-4" aria-hidden />Выбрать файл<input type="file" className="sr-only" accept=".txt,.md,.markdown,.html,.htm,.pdf,.docx" onChange={onFile} /></label>
      )}
      {upload.isPending && <Spinner label="Загружаем…" />}
      {upload.error && <ErrorNote error={upload.error} />}
      {d?.status === 'parsing' && <Spinner label="Разбираем документ…" />}
      {d?.status === 'failed' && <Banner tone="error" action={<Button onClick={() => setDraftId(null)}>Другой файл</Button>}>{d.error}</Banner>}
      {d?.status === 'ready' && (
        <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); confirm.mutate() }}>
          <Banner>Файл «{d.filename}»: {stats['chars']} символов, страниц: {stats['pages']}, фрагментов: {stats['chunks']}{stats['articles'] ? `, статей: ${stats['articles']}` : ''}. Реквизиты определены автоматически — проверьте их по официальному источнику.</Banner>
          <details><summary className="cursor-pointer text-small">Предпросмотр извлечённого текста (экранированный)</summary><pre className="mt-2 max-h-60 overflow-auto whitespace-pre-wrap rounded-md bg-sidebar p-3 text-xs">{String(d.preview['text_preview'] ?? '')}</pre></details>
          <div className="grid gap-3 md:grid-cols-2">
            <Field id="dt" label="Тип источника"><select id="dt" className="input" value={meta.doc_type} onChange={(e) => setMeta({ ...meta, doc_type: e.target.value as Meta['doc_type'] })}><option value="npa">НПА</option><option value="textbook">Учебник / комментарий</option><option value="soft_law">Мягкое право</option></select></Field>
            <Field id="tt" label="Полное название"><input id="tt" className="input" required value={meta.title} onChange={(e) => setMeta({ ...meta, title: e.target.value })} /></Field>
            <Field id="sn" label="Краткое название"><input id="sn" className="input" value={meta.short_name ?? ''} onChange={(e) => set('short_name', e.target.value)} placeholder="152-ФЗ" /></Field>
            <Field id="an" label="Номер акта"><input id="an" className="input" value={meta.act_number ?? ''} onChange={(e) => set('act_number', e.target.value)} placeholder="152-ФЗ" /></Field>
            <Field id="ad" label="Дата акта"><input id="ad" type="date" className="input" value={meta.act_date ?? ''} onChange={(e) => set('act_date', e.target.value)} /></Field>
            <Field id="rd" label="Дата редакции" hint="Редакции неизменяемы: новая дата = новая редакция."><input id="rd" type="date" className="input" value={meta.revision_date ?? ''} onChange={(e) => set('revision_date', e.target.value)} /></Field>
            <Field id="ef" label="Действует с"><input id="ef" type="date" className="input" value={meta.effective_from ?? ''} onChange={(e) => set('effective_from', e.target.value)} /></Field>
            <Field id="et" label="Утратила силу с (если применимо)"><input id="et" type="date" className="input" value={meta.effective_to ?? ''} onChange={(e) => set('effective_to', e.target.value)} /></Field>
            <Field id="vf" label="Дата проверки по официальному источнику" hint="Пусто — актуальность не подтверждена, и ответы это покажут."><input id="vf" type="date" className="input" value={meta.verified_at ?? ''} onChange={(e) => set('verified_at', e.target.value)} /></Field>
            <Field id="su" label="Реквизит источника (URL, не загружается)"><input id="su" className="input" value={meta.source_url ?? ''} onChange={(e) => set('source_url', e.target.value)} placeholder="publication.pravo.gov.ru/…" /></Field>
            {meta.doc_type !== 'npa' && <Field id="ed" label="Издание (обязательно для учебника)"><input id="ed" className="input" required={meta.doc_type === 'textbook'} value={meta.edition ?? ''} onChange={(e) => set('edition', e.target.value)} /></Field>}
            {meta.doc_type !== 'npa' && <Field id="ln" label="Основание правомерного включения" hint="Лицензия, открытый материал и т. п."><input id="ln" className="input" required value={meta.license_note ?? ''} onChange={(e) => set('license_note', e.target.value)} /></Field>}
          </div>
          {confirm.error && <ErrorNote error={confirm.error} />}
          <div className="flex gap-2"><Button variant="primary" type="submit" disabled={confirm.isPending}>{confirm.isPending ? 'Импортируем…' : 'Подтвердить и проиндексировать'}</Button><Button onClick={() => setDraftId(null)}>Отмена</Button></div>
        </form>
      )}
      {confirm.isSuccess && <Banner>{confirm.data.created ? 'Редакция импортирована; индексация запущена в фоне.' : 'Этот материал уже был импортирован (повторный импорт идемпотентен).'}</Banner>}
    </section>
  )
}

function Compare({ docs }: { docs: Doc[] }) {
  const multi = docs.filter((d) => d.revisions.length > 1)
  const [doc, setDoc] = useState('')
  const [l, setL] = useState('')
  const [r, setR] = useState('')
  const cur = multi.find((d) => d.id === doc)
  const diff = useQuery({ queryKey: ['cmp', l, r], queryFn: () => get<{ summary: Record<string, number>; items: { locator: string; status: string; ops: { op: string; text: string }[]; left_text?: string; right_text?: string }[]; left: Record<string, string>; right: Record<string, string> }>(`/corpus/compare?left=${l}&right=${r}`), enabled: !!l && !!r && l !== r })
  const label = (x: Doc['revisions'][number]) => (x.revision_date ? `от ${x.revision_date}` : x.edition ?? x.original_name)
  return (
    <section aria-labelledby="cmp" className="space-y-3 rounded-lg border border-line p-4">
      <h2 id="cmp" className="text-h3">Сравнение редакций</h2>
      {multi.length === 0 ? <p className="hint">Нужны хотя бы две загруженные редакции одного документа. Отсутствующая редакция не генерируется.</p> : (
        <div className="flex flex-wrap items-end gap-3">
          <Field id="cd" label="Документ"><select id="cd" className="input" value={doc} onChange={(e) => { setDoc(e.target.value); setL(''); setR('') }}><option value="">—</option>{multi.map((d) => <option key={d.id} value={d.id}>{d.short_name ?? d.title}</option>)}</select></Field>
          <Field id="cl" label="Было"><select id="cl" className="input" value={l} onChange={(e) => setL(e.target.value)}><option value="">—</option>{cur?.revisions.map((x) => <option key={x.id} value={x.id}>{label(x)}</option>)}</select></Field>
          <Field id="cr" label="Стало"><select id="cr" className="input" value={r} onChange={(e) => setR(e.target.value)}><option value="">—</option>{cur?.revisions.map((x) => <option key={x.id} value={x.id}>{label(x)}</option>)}</select></Field>
        </div>
      )}
      {diff.isLoading && <Skeleton lines={3} />}
      {diff.error && <ErrorNote error={diff.error} />}
      {diff.data && (
        <div className="space-y-3">
          <p className="text-small tnum">Изменено: {diff.data.summary['changed']}, добавлено: {diff.data.summary['added']}, удалено: {diff.data.summary['removed']}, без изменений: {diff.data.summary['unchanged']}</p>
          {diff.data.items.length === 0 && <p className="hint">Тексты редакций совпадают.</p>}
          {diff.data.items.map((it) => (
            <div key={it.locator} className="rounded-md border border-line p-3 text-small">
              <p className="mb-1 font-medium">{it.locator} — {it.status === 'changed' ? 'изменено' : it.status === 'added' ? 'добавлено' : 'удалено'}</p>
              <p className="whitespace-pre-wrap break-words leading-relaxed">
                {it.status === 'changed' ? it.ops.map((o, i) => o.op === 'equal' ? <span key={i}>{o.text}</span> : o.op === 'insert' ? <ins key={i} className="bg-risk-low-soft text-risk-low no-underline">{o.text}</ins> : <del key={i} className="bg-risk-high-soft text-risk-high">{o.text}</del>) : (it.left_text ?? it.right_text)}
              </p>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}

/** Исключение и удаление документа. Удаление отклоняется, пока на документ ссылаются сохранённые ответы — иначе цитата перестала бы открываться. */
function DocActions({ doc }: { doc: Doc }) {
  const qc = useQueryClient()
  const [confirm, setConfirm] = useState(false)
  const refresh = () => { void qc.invalidateQueries({ queryKey: keys.documents }); void qc.invalidateQueries({ queryKey: keys.corpus }); void qc.invalidateQueries({ queryKey: keys.manifest }); void qc.invalidateQueries({ queryKey: keys.jobs }) }
  const exclude = useMutation({ mutationFn: () => patch<Doc>(`/corpus/documents/${doc.id}`, { excluded: !doc.excluded }), onSuccess: refresh })
  const remove = useMutation({ mutationFn: () => del<{ chunks: number }>(`/corpus/documents/${doc.id}`), onSuccess: () => { setConfirm(false); refresh() } })
  return (
    <div className="mt-2 flex flex-wrap items-center gap-2">
      <Button onClick={() => exclude.mutate()} disabled={exclude.isPending}>
        <EyeOff className="size-4" aria-hidden />{doc.excluded ? 'Вернуть в корпус' : 'Исключить из корпуса'}
      </Button>
      {doc.cited_in_sessions > 0 ? (
        <span className="hint">Удаление недоступно: на документ ссылаются ответы в {doc.cited_in_sessions} сессиях. Удалите эти сессии и очистите их в разделе «Администрирование», либо исключите документ.</span>
      ) : confirm ? (
        <>
          <span className="text-small">Удалить безвозвратно вместе с фрагментами и файлами?</span>
          <Button variant="danger" onClick={() => remove.mutate()} disabled={remove.isPending}>{remove.isPending ? 'Удаляем…' : 'Да, удалить'}</Button>
          <Button onClick={() => setConfirm(false)}>Отмена</Button>
        </>
      ) : (
        <Button onClick={() => setConfirm(true)}><Trash2 className="size-4" aria-hidden />Удалить</Button>
      )}
      {exclude.error && <ErrorNote error={exclude.error} />}
      {remove.error && <ErrorNote error={remove.error} />}
    </div>
  )
}

export function KnowledgeBasePage() {
  document.title = 'База знаний — DoorAIn'
  const qc = useQueryClient()
  const corpus = useCorpus()
  const manifest = useManifest()
  const docs = useDocuments()
  const jobs = useJobs()
  const [q, setQ] = useState('')
  const [hits, setHits] = useState<SearchHit[] | null>(null)
  const build = useMutation({ mutationFn: () => post('/corpus/generations/build'), onSuccess: () => qc.invalidateQueries({ queryKey: keys.jobs }) })
  const verify = useMutation({ mutationFn: (v: { id: string; date: string }) => patch(`/corpus/revisions/${v.id}`, { verified_at: v.date }), onSuccess: () => { void qc.invalidateQueries({ queryKey: keys.documents }); void qc.invalidateQueries({ queryKey: keys.corpus }) } })
  const search = useMutation({ mutationFn: () => get<SearchHit[]>(`/corpus/search?q=${encodeURIComponent(q)}`), onSuccess: setHits })
  const removeDemo = useMutation({
    mutationFn: () => post<{ items: { document: string; action: string }[] }>('/corpus/documents/demo/remove'),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: keys.documents }); void qc.invalidateQueries({ queryKey: keys.corpus }); void qc.invalidateQueries({ queryKey: keys.manifest }) },
  })
  const c = corpus.data
  const running = jobs.data?.filter((j) => j.status === 'queued' || j.status === 'running') ?? []
  return (
    <div className="neutral mx-auto max-w-5xl space-y-6 px-4 py-6">
      <div className="flex flex-wrap items-center justify-between gap-2"><h1>База знаний</h1><Button onClick={() => build.mutate()} disabled={build.isPending || running.length > 0}><RefreshCw className="size-4" aria-hidden />Переиндексировать</Button></div>
      {corpus.isLoading && <Skeleton lines={3} />}
      {corpus.isError && <ErrorNote error={corpus.error} onRetry={() => corpus.refetch()} />}
      {c?.empty && <EmptyState title="Корпус пуст">Загрузите проверенные тексты законов ниже. Приложение не скачивает законы само: обновление — управляемый импорт локальных файлов (см. docs/knowledge-base.md). Пока корпус пуст, диалог честно откажет в ответе.</EmptyState>}
      {c && !c.empty && (
        <p className="text-small text-muted tnum">Документов: {c.documents} · редакций: {c.revisions} · фрагментов: {c.chunks} · активная generation: {c.active_generation ? `№${c.active_generation.seq}, контрольный поиск ${c.active_generation.control_search['passed'] as number}/${c.active_generation.control_search['checked'] as number}` : 'нет (индекс не построен)'}</p>
      )}
      {c?.has_demo && (
        <Banner tone="warn" action={<Button onClick={() => removeDemo.mutate()} disabled={removeDemo.isPending}>{removeDemo.isPending ? 'Убираем…' : 'Убрать демонстрационные данные'}</Button>}>
          В корпусе есть демонстрационные данные — не нормативная база. Не используйте их для реальных выводов. Документы без ссылок в ответах будут удалены, остальные — исключены из корпуса.
        </Banner>
      )}
      {removeDemo.error && <ErrorNote error={removeDemo.error} />}
      {running.length > 0 && <Banner><Spinner label={`Выполняется: ${running.map((j) => (j.type === 'build_generation' ? `индексация${j.progress['total'] ? ` ${j.progress['done']}/${j.progress['total']}` : ''}` : 'разбор документа')).join(', ')}`} /></Banner>}
      {jobs.data?.find((j) => j.status === 'failed') && <Banner tone="error">Последнее задание завершилось ошибкой: {jobs.data.find((j) => j.status === 'failed')?.error}</Banner>}
      <ImportWizard />
      <section aria-labelledby="mf" className="space-y-2">
        <h2 id="mf" className="text-h3">Перечень источников из концепции</h2>
        <p className="hint">Это список кандидатов, а не утверждение об актуальности или достаточности актов. Реквизиты и редакции проверяются при импорте.</p>
        {manifest.data && (
          <ul className="divide-y divide-line rounded-lg border border-line text-small">
            {manifest.data.map((m) => (
              <li key={m.id} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2"><span className="min-w-0 flex-1">{m.title}{m.note && <span className="block text-muted">{m.note}</span>}</span><span className="chip">{m.tier === 'start' ? 'Стартовый' : 'Расширенный'}</span><span className={`chip ${m.status === 'missing' ? 'risk-none' : m.status === 'verified' ? 'risk-low' : 'risk-medium'}`}>{STATE_RU[m.status]}</span></li>
            ))}
          </ul>
        )}
      </section>
      <section aria-labelledby="docs" className="space-y-2">
        <h2 id="docs" className="text-h3">Документы и редакции</h2>
        {docs.data?.length === 0 && <p className="hint">Документов пока нет.</p>}
        {docs.data?.map((d) => (
          <div key={d.id} className="rounded-lg border border-line p-3 text-small">
            <p className="font-medium">{d.title} <span className="chip ml-1">{DOC_RU[d.doc_type]}</span>{d.is_demo && <span className="chip risk-medium ml-1">демо</span>}{d.excluded && <span className="chip risk-high ml-1">исключён из корпуса</span>}</p>
            <ul className="mt-2 space-y-1">
              {d.revisions.map((r) => (
                <li key={r.id} className="flex flex-wrap items-center gap-2 tnum">
                  <span>{r.revision_date ? `редакция от ${r.revision_date}` : r.edition ?? 'без даты'}</span>
                  <span className="text-muted">действует с {r.effective_from ?? '—'}{r.effective_to ? ` по ${r.effective_to}` : ''}</span>
                  <span className="chip">{STATE_RU[r.corpus_state]}</span>
                  <span className="text-muted">фрагментов: {r.chunk_count}</span>
                  {r.verified_at ? <span className="chip risk-low">проверена {r.verified_at}</span> : (
                    <button type="button" className="chip" onClick={() => verify.mutate({ id: r.id, date: todayISO() })}>Отметить проверенной сегодня</button>
                  )}
                  <a href={`/api/v1/revisions/${r.id}/file`} download>оригинал</a>
                </li>
              ))}
            </ul>
            <DocActions doc={d} />
          </div>
        ))}
        {verify.error && <ErrorNote error={verify.error} />}
      </section>
      {docs.data && <Compare docs={docs.data} />}
      <section aria-labelledby="srch" className="space-y-2">
        <h2 id="srch" className="text-h3">Поиск по базе</h2>
        <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (q.trim().length >= 2) search.mutate() }}>
          <label className="sr-only" htmlFor="q">Запрос</label>
          <input id="q" className="input" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Номер статьи или фраза, например: ст. 18.1" />
          <Button type="submit"><Search className="size-4" aria-hidden />Найти</Button>
        </form>
        {search.error instanceof ApiError && <p role="alert" className="text-small text-risk-high">{errorText(search.error)}</p>}
        {hits && hits.length === 0 && <p className="hint">Ничего не найдено.</p>}
        <ul className="space-y-2">{hits?.map((h) => <li key={h.chunk_id} className="rounded-md border border-line p-3 text-small"><p className="font-medium">{h.document_title}, {h.locator} <span className="text-muted tnum">({h.revision_date ? `ред. ${h.revision_date}` : h.edition})</span> {!h.applicable && <span className="chip">не действует на сегодня в активной generation</span>}</p><p className="mt-1 whitespace-pre-wrap break-words text-muted">{h.excerpt}</p></li>)}</ul>
        <p className="hint"><GitCompare className="mr-1 inline size-3.5" aria-hidden />Семантический поиск выполняется в диалоге (локальные embeddings и reranker); здесь — точный поиск по статье и подстроке.</p>
      </section>
    </div>
  )
}
