import { useMutation, useQueryClient } from '@tanstack/react-query'
import { CalendarDays, FileDown, GitBranch, GraduationCap, ListChecks, Network, Repeat, X } from 'lucide-react'
import { useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { Dialog } from '../../components/Dialog'
import { Banner, ErrorNote, Skeleton } from '../../components/States'
import { Button } from '../../components/ui'
import type { Role, Session } from '../../lib/api'
import { errorText, patch, post } from '../../lib/api'
import { useLayoutMode, useLocalState } from '../../lib/hooks'
import { keys, useSession, useStatus } from '../../lib/queries'
import { ROLE_RU } from '../../lib/risk'
import { SelectionProvider, useSelection } from '../../lib/selection'
import { ChatPanel } from './ChatPanel'
import { ExportDialog, QuizDialog } from './Dialogs'
import { PortraitPanel } from './PortraitPanel'
import { RisksPanel } from './RisksPanel'
import { SourceDrawer } from './SourceDrawer'
import { Splitter } from './Splitter'

export type PortraitMode = 'map' | 'timeline' | 'plan'
const MODES: [PortraitMode, string, typeof Network][] = [['map', 'Карта тем', Network], ['timeline', 'Хронология', GitBranch], ['plan', 'План-схема', ListChecks]]

function TopBar({ session, mode, setMode, onExport, onQuiz, showModes = true }: { session: Session; mode: PortraitMode; setMode: (m: PortraitMode) => void; onExport: () => void; onQuiz: () => void; showModes?: boolean }) {
  const status = useStatus()
  const qc = useQueryClient()
  const nav = useNavigate()
  const { sel, clear } = useSelection()
  const [editing, setEditing] = useState(false)
  const [title, setTitle] = useState(session.title)
  const [roleOpen, setRoleOpen] = useState(false)
  const rename = useMutation({ mutationFn: (t: string) => patch<Session>(`/sessions/${session.id}`, { title: t }), onSuccess: () => { setEditing(false); void qc.invalidateQueries({ queryKey: keys.session(session.id) }); void qc.invalidateQueries({ queryKey: ['sessions'] }) } })
  const changeRole = useMutation({ mutationFn: (role: Role) => post<Session>(`/sessions/${session.id}/change-role`, { role }), onSuccess: (s) => { setRoleOpen(false); void qc.invalidateQueries({ queryKey: ['sessions'] }); nav(`/s/${s.id}`) } })
  const st = status.data
  const model = st?.model
  const [dev] = useLocalState('doorain.dev', false)
  const anySel = !!(sel.riskId || sel.nodeId || sel.messageId)
  return (
    <header className="glass relative z-10 mx-3 mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 rounded-[var(--r-zone)] px-4 py-2">
      <div className="min-w-[min(100%,18rem)] flex-1">
        {editing ? (
          <form onSubmit={(e) => { e.preventDefault(); if (title.trim()) rename.mutate(title) }} className="flex gap-2">
            <label className="sr-only" htmlFor="ttl">Название сессии</label>
            <input id="ttl" className="input !min-h-8" value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} onKeyDown={(e: KeyboardEvent) => { if (e.key === 'Escape') setEditing(false) }} autoFocus />
            <Button type="submit">Сохранить</Button>
          </form>
        ) : (
          <button type="button" className="display-s min-h-11 max-w-full truncate rounded-[var(--r-control)] px-1.5 text-left hover:bg-hover" onClick={() => { setTitle(session.title); setEditing(true) }} title="Переименовать сессию">{session.title}</button>
        )}
        <p className="caption flex flex-wrap items-center gap-x-3 gap-y-0.5 px-1.5">
          <span className="chip">{ROLE_RU[session.role]}</span>
          <span className="tnum flex items-center gap-1"><CalendarDays className="size-3.5 text-faint" aria-hidden />Срез на {session.as_of_date}</span>
          {st?.corpus_empty && <span>Корпус пуст</span>}
          {dev && st && !st.corpus_empty && <span className="mono-m">generation №{st.generation_seq}</span>}
          {model && model.state !== 'ready' && <span className={`chip ${model.state === 'unavailable' ? 'risk-high' : 'risk-medium'}`}>{model.state === 'unavailable' ? 'Модель недоступна' : 'Тестовый режим: не языковая модель'}</span>}
          {session.status === 'archived' && <span className="chip">В архиве</span>}
        </p>
        {rename.error && <p role="alert" className="text-small text-risk-high">{errorText(rename.error)}</p>}
      </div>
      {showModes && (
        <div className="seg" role="tablist" aria-label="Режим портрета">
          {MODES.map(([id, label, Icon]) => (
            <button key={id} role="tab" className="seg-item" aria-selected={mode === id} onClick={() => setMode(id)}><Icon className="size-3.5" aria-hidden />{label}</button>
          ))}
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2">
        {anySel && <Button variant="tertiary" onClick={clear}><X className="size-4" aria-hidden />Снять выделение</Button>}
        {session.role === 'student' && <Button onClick={onQuiz}><GraduationCap className="size-4" aria-hidden />Проверить себя</Button>}
        <Button onClick={() => setRoleOpen(true)}><Repeat className="size-4" aria-hidden />Сменить роль</Button>
        <Button onClick={onExport}><FileDown className="size-4" aria-hidden />Выгрузить PDF</Button>
      </div>
      <Dialog open={roleOpen} onClose={() => setRoleOpen(false)} title="Сменить роль">
        <p className="mb-3 text-small text-muted">Смена роли создаёт новую сессию со своим слепком и рисками. Текущая сессия и её данные сохранятся; сведения между сессиями не переносятся.</p>
        <div className="flex flex-col gap-2">
          {(['student', 'entrepreneur', 'expert'] as const).filter((r) => r !== session.role).map((r) => <Button key={r} disabled={changeRole.isPending} onClick={() => changeRole.mutate(r)}>Открыть новую сессию: {ROLE_RU[r]}</Button>)}
        </div>
        {changeRole.error && <p role="alert" className="mt-2 text-small text-risk-high">{errorText(changeRole.error)}</p>}
      </Dialog>
    </header>
  )
}

const SIDE_MIN = 260
const SIDE_MAX = 560
const CENTER_MIN = 360
const CHROME = 24 + 64  // внутренние отступы сетки и две зоны захвата

/** Три зоны по макету: чат 300 px, слепок — гибкая ширина (не уже 360 px), риски 360 px. Боковые зоны тянутся мышью, касанием или стрелками. */
function ThreePanels({ chat, portrait, risks }: { chat: React.ReactNode; portrait: React.ReactNode; risks: React.ReactNode }) {
  const [w, setW] = useLocalState<[number, number]>('doorain.zones', [300, 360])
  const box = useRef<HTMLDivElement>(null)
  const [total, setTotal] = useState(0)
  useEffect(() => {
    const el = box.current
    if (!el) return
    const ro = new ResizeObserver(() => setTotal(el.clientWidth))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  const maxFor = (other: number) => Math.max(SIDE_MIN, Math.min(SIDE_MAX, total ? total - CHROME - CENTER_MIN - other : SIDE_MAX))
  const left = Math.min(w[0], maxFor(w[1]))
  const right = Math.min(w[1], maxFor(left))
  return (
    <div ref={box} className="grid min-h-0 flex-1 gap-0 p-3" style={{ gridTemplateColumns: `${left}px 32px minmax(${CENTER_MIN}px, 1fr) 32px ${right}px` }}>
      <section aria-label="Диалог" className="zone min-h-0 min-w-0 overflow-hidden !p-0">{chat}</section>
      <Splitter label="Изменить ширину диалога" value={left} min={SIDE_MIN} max={maxFor(right)} dir={1} onChange={(v) => setW([v, right])} />
      <section aria-label="Цифровой слепок" className="zone min-h-0 min-w-0 overflow-hidden !p-0">{portrait}</section>
      <Splitter label="Изменить ширину рисков" value={right} min={SIDE_MIN} max={maxFor(left)} dir={-1} onChange={(v) => setW([left, v])} />
      <section aria-label="Риски" className="zone min-h-0 min-w-0 overflow-hidden !p-0">{risks}</section>
    </div>
  )
}

function Inner({ session }: { session: Session }) {
  const mode = useLayoutMode()
  const [draft, setDraft] = useState('')
  const [tab, setTab] = useState<'chat' | 'portrait' | 'risks'>('chat')
  const [pmode, setPmode] = useState<PortraitMode>('map')
  const [right, setRight] = useState<'portrait' | 'risks'>('portrait')
  const [exportOpen, setExportOpen] = useState(false)
  const [quizOpen, setQuizOpen] = useState(false)
  const { sel } = useSelection()
  useEffect(() => { document.title = `${session.title} — DoorAIn` }, [session.title])
  // Выбор риска/узла на узком экране не должен ломать контекст: панели остаются смонтированными (ввод и прокрутка сохраняются).
  const chat = <ChatPanel session={session} draft={draft} setDraft={setDraft} />
  const portrait = <PortraitPanel session={session} mode={pmode} />
  const risks = <RisksPanel session={session} />
  const tabBtn = (id: string, label: string, on: boolean, set: () => void) => (
    <button key={id} role="tab" aria-selected={on} className={`btn ${on ? 'btn-primary' : 'btn-tertiary'} flex-1`} onClick={set}>{label}</button>
  )
  return (
    <div className="flex h-full min-h-0 flex-col">
      <TopBar session={session} mode={pmode} setMode={setPmode} onExport={() => setExportOpen(true)} onQuiz={() => setQuizOpen(true)} showModes={mode !== 'narrow' || tab === 'portrait'} />
      {mode === 'wide' && <ThreePanels chat={chat} portrait={portrait} risks={risks} />}
      {mode === 'mid' && (
        <div className="grid min-h-0 flex-1 grid-cols-[minmax(320px,46fr)_minmax(320px,54fr)]">
          <section aria-label="Диалог" className="zone m-3 mr-1.5 min-h-0 min-w-0 overflow-hidden !p-0">{chat}</section>
          <section className="zone m-3 ml-1.5 flex min-h-0 min-w-0 flex-col overflow-hidden !p-0" aria-label="Портрет и риски">
            <div role="tablist" aria-label="Правая панель" className="flex gap-1 border-b border-line-soft px-3 py-2">{tabBtn('portrait', 'Портрет', right === 'portrait', () => setRight('portrait'))}{tabBtn('risks', 'Риски', right === 'risks', () => setRight('risks'))}</div>
            <div className={`min-h-0 flex-1 ${right === 'portrait' ? '' : 'hidden'}`}>{portrait}</div>
            <div className={`min-h-0 flex-1 ${right === 'risks' ? '' : 'hidden'}`}>{risks}</div>
          </section>
        </div>
      )}
      {mode === 'narrow' && (
        <>
          <div role="tablist" aria-label="Разделы сессии" className="glass mx-3 mt-2 flex gap-1 rounded-[var(--r-card)] p-1">{tabBtn('chat', 'Диалог', tab === 'chat', () => setTab('chat'))}{tabBtn('portrait', 'Портрет', tab === 'portrait', () => setTab('portrait'))}{tabBtn('risks', 'Риски', tab === 'risks', () => setTab('risks'))}</div>
          <div className={`min-h-0 flex-1 ${tab === 'chat' ? '' : 'hidden'}`}>{chat}</div>
          <div className={`min-h-0 flex-1 ${tab === 'portrait' ? '' : 'hidden'}`}>{portrait}</div>
          <div className={`min-h-0 flex-1 ${tab === 'risks' ? '' : 'hidden'}`}>{risks}</div>
        </>
      )}
      <SourceDrawer />
      <ExportDialog session={session} open={exportOpen} onClose={() => setExportOpen(false)} />
      <QuizDialog session={session} open={quizOpen} onClose={() => setQuizOpen(false)} />
      <span className="sr-only" aria-live="polite">{sel.riskId ? 'Риск выбран, связанные узлы подсвечены' : ''}</span>
    </div>
  )
}

export function WorkspacePage() {
  const { id = '' } = useParams()
  const session = useSession(id)
  if (session.isLoading) return <div className="p-6"><Skeleton lines={6} /></div>
  if (session.isError) return <div className="mx-auto max-w-lg space-y-3 p-6"><ErrorNote error={session.error} onRetry={() => session.refetch()} /><Link to="/history" className="btn no-underline">К истории</Link></div>
  if (!session.data) return null
  return (
    <SelectionProvider key={session.data.id}>
      {session.data.status === 'archived' && <Banner tone="warn">Сессия в архиве: чтение доступно, отправка новых вопросов отключена.</Banner>}
      <Inner session={session.data} />
    </SelectionProvider>
  )
}
