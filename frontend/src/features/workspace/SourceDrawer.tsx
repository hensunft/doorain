import { Copy, Download, FileText } from 'lucide-react'
import { useState } from 'react'
import { Dialog } from '../../components/Dialog'
import { Banner, ErrorNote, Skeleton } from '../../components/States'
import { Button } from '../../components/ui'
import { useCitation } from '../../lib/queries'
import { useSelection } from '../../lib/selection'

const TYPE_RU: Record<string, string> = { npa: 'НПА (нормативный правовой акт)', textbook: 'Учебник / комментарий', soft_law: 'Мягкое право (не общеобязательный закон)' }

export function SourceDrawer() {
  const { sel, openCitation } = useSelection()
  const q = useCitation(sel.citationId)
  const [copied, setCopied] = useState(false)
  const c = q.data
  const sn = c?.snapshot as Record<string, string | number | boolean | null> | undefined
  const copy = async () => {
    if (!c) return
    try { await navigator.clipboard.writeText(c.formatted) } catch { /* без clipboard: пользователь выделит текст вручную */ }
    setCopied(true)
    window.setTimeout(() => setCopied(false), 2000)
  }
  return (
    <Dialog open={!!sel.citationId} onClose={() => openCitation(null)} title="Источник" variant="side">
      {q.isLoading && <Skeleton lines={8} />}
      {q.isError && <ErrorNote error={q.error} onRetry={() => q.refetch()} />}
      {c && sn && (
        <div className="space-y-4 text-small">
          {sn['archived'] === true && <Banner tone="warn">Источник выведен из базы знаний: основание недействительно и показано только для истории.</Banner>}
          {!sn['verified_at'] && <Banner tone="warn">Актуальность этой редакции не подтверждена: ответ нельзя считать актуальным на сегодняшнюю дату.</Banner>}
          <div>
            <h3>{String(sn['act_title'])}</h3>
            <p className="text-muted">{TYPE_RU[String(sn['doc_type'])] ?? String(sn['doc_type'])}</p>
          </div>
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
            <dt className="text-muted">Номер акта</dt><dd>{String(sn['act_number'] ?? '—')}</dd>
            <dt className="text-muted">Дата акта</dt><dd className="tnum">{String(sn['act_date'] ?? '—')}</dd>
            <dt className="text-muted">Фрагмент</dt><dd>{String(sn['locator'])}{sn['page'] ? `, с. ${String(sn['page'])}` : ''}</dd>
            <dt className="text-muted">Редакция</dt><dd className="tnum">{sn['revision_date'] ? `от ${String(sn['revision_date'])}` : sn['edition'] ? `издание: ${String(sn['edition'])}` : 'дата не указана'}</dd>
            <dt className="text-muted">Действует с</dt><dd className="tnum">{String(sn['effective_from'] ?? '—')}{sn['effective_to'] ? ` по ${String(sn['effective_to'])}` : ''}</dd>
            <dt className="text-muted">Проверена</dt><dd className="tnum">{String(sn['verified_at'] ?? 'не проверена')}</dd>
            <dt className="text-muted">Реквизит источника</dt><dd className="break-all">{String(sn['source_url'] ?? 'не указан')}</dd>
          </dl>
          <section aria-label="Текст фрагмента">
            <h4 className="mb-1 font-semibold">Сохранённая выдержка</h4>
            {c.context_before && <details className="mb-1 text-muted"><summary className="cursor-pointer">Предыдущий фрагмент (контекст)</summary><p className="mt-1 whitespace-pre-wrap">{c.context_before}</p></details>}
            <blockquote className="whitespace-pre-wrap break-words rounded-md border border-line bg-sidebar px-3 py-2 leading-relaxed">{c.excerpt}</blockquote>
            {c.context_after && <details className="mt-1 text-muted"><summary className="cursor-pointer">Следующий фрагмент (контекст)</summary><p className="mt-1 whitespace-pre-wrap">{c.context_after}</p></details>}
            <p className="hint mt-1">Выдержка и реквизиты сохранены на момент ответа и не меняются при загрузке новых редакций.</p>
          </section>
          <div className="flex flex-wrap gap-2">
            <Button onClick={copy}><Copy className="size-4" aria-hidden />{copied ? 'Скопировано' : 'Копировать цитату'}</Button>
            <a className="btn no-underline" href={`/api/v1/citations/${c.id}/export`} download><Download className="size-4" aria-hidden />Скачать .txt</a>
            <a className="btn no-underline" href={c.file_url} download><FileText className="size-4" aria-hidden />Оригинал документа</a>
          </div>
          <p role="status" className="sr-only">{copied ? 'Цитата скопирована' : ''}</p>
        </div>
      )}
    </Dialog>
  )
}
