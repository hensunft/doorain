import { CircleAlert, Info, ShieldQuestion } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import type { Block, CitationChip } from '../../lib/api'

/** Markdown без произвольного HTML: skipHtml, ссылки не подгружаются автоматически и не становятся активными. */
export function SafeMarkdown({ text }: { text: string }) {
  return (
    <div className="prose-answer">
      <ReactMarkdown skipHtml components={{ a: ({ children }) => <span>{children}</span>, img: () => null }}>{text}</ReactMarkdown>
    </div>
  )
}

const BARE = new Set(['да', 'нет', 'не', 'неизвестно', 'знаю', 'возможно', 'может', 'быть', 'наверное', 'ок', 'ага', 'угу', 'так'])
export const factBody = (text: string) => text.replace(/^Со слов пользователя\s*[:,—–-]?\s*/i, '').trim()
/** Факт — утверждение с предметом; зеркало серверной проверки verify.fact_has_subject. */
export function factHasSubject(body: string) {
  const words = body.toLowerCase().match(/[а-яёa-z0-9]+/g) ?? []
  return words.length >= 3 && words.filter((w) => !BARE.has(w)).length >= 2
}

interface BlockProps {
  block: Block
  chips: CitationChip[]
  onCite: (id: string) => void
}

function Chips({ block, chips, onCite }: BlockProps) {
  const found = block.citation_ids.map((id) => chips.find((c) => c.id === id)).filter((c): c is CitationChip => !!c)
  if (!found.length) return null
  return (
    <div className="mt-1 flex flex-wrap gap-1.5">
      {found.map((c) => (
        <button key={c.id} type="button" className="chip max-w-full" onClick={() => onCite(c.id)} title={`${c.label}, ${c.locator} (${c.revision_label})`} aria-label={`Открыть источник: ${c.label}, ${c.locator}, ${c.revision_label}`}>
          <span className="truncate">{c.label}, {c.locator}</span>
          <span className="text-muted">{c.revision_label}</span>
          {!c.verified && <span className="text-risk-medium" title="Актуальность редакции не подтверждена">?</span>}
          {c.archived && <span className="text-muted">архив</span>}
        </button>
      ))}
    </div>
  )
}

export function BlockView({ block, chips, onCite }: BlockProps) {
  const p = { block, chips, onCite }
  switch (block.kind) {
    case 'refusal':
      return <div role="note" className="flex gap-2 rounded-md bg-risk-medium-soft px-3 py-2 text-small text-risk-medium"><ShieldQuestion className="mt-0.5 size-4 shrink-0" aria-hidden /><p>{block.text}</p></div>
    case 'notice':
      return <div role="note" className="flex gap-2 rounded-md bg-sidebar px-3 py-2 text-small text-muted"><CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden /><p>{block.text}</p></div>
    case 'currency':
      return <div role="note" className="flex gap-2 text-small text-muted"><Info className="mt-0.5 size-4 shrink-0" aria-hidden /><p>{block.text}</p></div>
    case 'fact': {
      const body = factBody(block.text)
      // старые записи до исправления: «нет.» без предмета не показывается как факт пользователя
      if (!factHasSubject(body)) return <p className="text-small text-muted">Ответ без предмета («{body || '—'}») не учитывается как факт.</p>
      return <div><span className="chip mb-1">Со слов пользователя</span><SafeMarkdown text={body} /></div>
    }
    case 'assumption':
      return <div><span className="chip mb-1">Допущение</span><SafeMarkdown text={block.text.replace(/^Допущение:\s*/i, '')} /></div>
    case 'clarification':
      return <div><span className="chip mb-1">Нужно уточнить</span><SafeMarkdown text={block.text} /></div>
    default:
      return <div><SafeMarkdown text={block.text} /><Chips {...p} /></div>
  }
}

export function Blocks({ blocks, chips, onCite }: { blocks: Block[]; chips: CitationChip[]; onCite: (id: string) => void }) {
  return <div className="space-y-3">{blocks.map((b) => <BlockView key={b.id} block={b} chips={chips} onCite={onCite} />)}</div>
}
