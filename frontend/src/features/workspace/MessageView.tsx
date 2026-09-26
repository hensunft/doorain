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

/** Смысловые метки блоков: цвет линии и метки — из токенов; сама метка — текст, цвет не единственный носитель смысла. */
const SEM = {
  user: { ['--sem' as string]: 'var(--brand-deep)', ['--sem-ink' as string]: 'var(--risk-high-ink)' },
  ask: { ['--sem' as string]: 'var(--gold)', ['--sem-ink' as string]: 'var(--gold)' },
  warn: { ['--sem' as string]: 'var(--risk-mid)', ['--sem-ink' as string]: 'var(--risk-mid-ink)' },
} as const

interface BlockProps {
  block: Block
  chips: CitationChip[]
  onCite: (id: string) => void
}

function Chips({ block, chips, onCite }: BlockProps) {
  const found = block.citation_ids.map((id) => chips.find((c) => c.id === id)).filter((c): c is CitationChip => !!c)
  if (!found.length) return null
  return (
    <div className="mt-1.5 flex flex-col items-start gap-0.5">
      {found.map((c) => (
        <button key={c.id} type="button" className="cite" onClick={() => onCite(c.id)} title={`${c.label}, ${c.locator} (${c.revision_label})`} aria-label={`Открыть источник: ${c.label}, ${c.locator}, ${c.revision_label}`}>
          <span className="truncate">{c.label}, {c.locator}</span>
          <span className="shrink-0 text-faint">{c.revision_label}</span>
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
      return <div role="note" className="sem" style={SEM.warn}><p className="overline flex items-center gap-1"><ShieldQuestion className="size-3.5" aria-hidden />Без ответа по существу</p><p className="text-small text-ink-2">{block.text}</p></div>
    case 'notice':
      return <div role="note" className="sem"><p className="overline flex items-center gap-1"><CircleAlert className="size-3.5" aria-hidden />Примечание</p><p className="text-small text-muted">{block.text}</p></div>
    case 'currency':
      return <div role="note" className="flex gap-2 text-xs text-muted"><Info className="mt-0.5 size-3.5 shrink-0" aria-hidden /><p>{block.text}</p></div>
    case 'fact': {
      const body = factBody(block.text)
      // старые записи до исправления: «нет.» без предмета не показывается как факт пользователя
      if (!factHasSubject(body)) return <p className="text-small text-muted">Ответ без предмета («{body || '—'}») не учитывается как факт.</p>
      return <div className="sem" style={SEM.user}><p className="overline">Со слов пользователя</p><SafeMarkdown text={body} /></div>
    }
    case 'assumption':
      return <div className="sem"><p className="overline">Допущение</p><SafeMarkdown text={block.text.replace(/^Допущение:\s*/i, '')} /></div>
    case 'clarification':
      return <div className="sem" style={SEM.ask}><p className="overline">Нужно уточнить</p><SafeMarkdown text={block.text} /></div>
    default:
      return <div><SafeMarkdown text={block.text} /><Chips {...p} /></div>
  }
}

export function Blocks({ blocks, chips, onCite }: { blocks: Block[]; chips: CitationChip[]; onCite: (id: string) => void }) {
  return <div className="space-y-3">{blocks.map((b) => <BlockView key={b.id} block={b} chips={chips} onCite={onCite} />)}</div>
}
