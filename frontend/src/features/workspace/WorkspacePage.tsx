import { useMutation, useQueryClient } from '@tanstack/react-query'
import { FileDown, GraduationCap, Repeat, X } from 'lucide-react'
import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react'
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

export type PortraitMode = 'map' | 'timeline' | 'plan'
const MODES: [PortraitMode, string][] = [['map', 'Карта тем'], ['timeline', 'Хронология'], ['plan', 'План-схема']]

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
    <header className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line bg-canvas px-4 py-2">
      <div className="min-w-[min(100%,18rem)] flex-1">
        {editing ? (
          <form onSubmit={(e) => { e.preventDefault(); if (title.trim()) rename.mutate(title) }} className="flex gap-2">
            <label className="sr-only" htmlFor="ttl">Название сессии</label>
            <input id="ttl" className="input !min-h-8" value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} onKeyDown={(e: KeyboardEvent) => { if (e.key === 'Escape') setEditing(false) }} autoFocus />
            <Button type="submit">Сохранить</Button>
          </form>
        ) : (
          <button type="button" className="display-s min-h-11 max-w-full truncate rounded-md px-1 text-left hover:bg-hover" onClick={() => { setTitle(session.title); setEditing(true) }} title="Переименовать сессию">{session.title}</button>
        )}
        <p className="caption flex flex-wrap items-center gap-x-3 gap-y-0.5">
          <span className="chip">{ROLE_RU[session.role]}</span>
          <span className="tnum">Срез на {session.as_of_date}</span>
          {st?.corpus_empty && <span>Корпус пуст</span>}
          {dev && st && !st.corpus_empty && <span className="mono-m">generation №{st.generation_seq}</span>}
          {model && model.state !== 'ready' && <span className={`chip ${model.state === 'unavailable' ? 'risk-high' : 'risk-medium'}`}>{model.state === 'unavailable' ? 'Модель недоступна' : 'Тестовый режим: не языковая модель'}</span>}
          {st?.has_demo && <span className="chip risk-medium">Демонстрационные данные — не нормативная база</span>}
          {session.status === 'archived' && <span className="chip">В архиве</span>}
        </p>
        {rename.error && <p role="alert" className="text-small text-risk-high">{errorText(rename.error)}</p>}
      </div>
      {showModes && (
        <div className="seg" role="tablist" aria-label="Режим портрета">
          {MODES.map(([id, label]) => (
            <button key={id} role="tab" className="seg-item" aria-selected={mode === id} onClick={() => setMode(id)}>{label}</button>
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

/** Три зоны по макету: чат 300 px, слепок — гибкая ширина, риски 360 px. Боковые зоны тянутся мышью или стрелками. */
function ThreePanels({ chat, portrait, risks }: { chat: React.ReactNode; portrait: React.ReactNode; risks: React.ReactNode }) {
  const [w, setW] = useLocalState<[number, number]>('doorain.zones', [300, 360])
  const drag = useRef<{ i: 0 | 1; x: number; start: [number, number] } | null>(null)
  const clamp = (v: number) => Math.max(260, Math.min(560, v))
  const down = (i: 0 | 1) => (e: PointerEvent) => { drag.current = { i, x: e.clientX, start: [w[0], w[1]] }; (e.target as HTMLElement).setPointerCapture(e.pointerId) }
  const move = (e: PointerEvent) => {
    const d = drag.current
    if (!d) return
    const dx = e.clientX - d.x
    setW(d.i === 0 ? [clamp(d.start[0] + dx), d.start[1]] : [d.start[0], clamp(d.start[1] - dx)])
  }
  const key = (i: 0 | 1) => (e: KeyboardEvent) => {
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return
    e.preventDefault()
    const step = (e.key === 'ArrowRight' ? 20 : -20) * (i === 0 ? 1 : -1)
    setW(i === 0 ? [clamp(w[0] + step), w[1]] : [w[0], clamp(w[1] + step)])
  }
  const Handle = ({ i }: { i: 0 | 1 }) => (
    <div role="separator" aria-orientation="vertical" aria-label={i === 0 ? 'Изменить ширину диалога' : 'Изменить ширину рисков'} tabIndex={0} onPointerDown={down(i)} onPointerMove={move} onPointerUp={() => { drag.current = null }} onKeyDown={key(i)} className="group flex w-8 cursor-col-resize justify-center bg-page focus-visible:shadow-none"><span className="h-full w-0.5 rounded-full group-hover:bg-line group-focus-visible:bg-gold" /></div>
  )
  return (
    <div className="grid min-h-0 flex-1 gap-0 bg-page p-3" style={{ gridTemplateColumns: `${w[0]}px 32px minmax(360px, 1fr) 32px ${w[1]}px` }}>
      <section aria-label="Диалог" className="zone min-h-0 min-w-0 overflow-hidden !p-0">{chat}</section>
      <Handle i={0} />
      <section aria-label="Цифровой слепок" className="zone min-h-0 min-w-0 overflow-hidden !p-0">{portrait}</section>
      <Handle i={1} />
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
          <section aria-label="Диалог" className="min-h-0 min-w-0 border-r border-line">{chat}</section>
          <section className="flex min-h-0 min-w-0 flex-col" aria-label="Портрет и риски">
            <div role="tablist" aria-label="Правая панель" className="flex gap-1 border-b border-line px-3 py-2">{tabBtn('portrait', 'Портрет', right === 'portrait', () => setRight('portrait'))}{tabBtn('risks', 'Риски', right === 'risks', () => setRight('risks'))}</div>
            <div className={`min-h-0 flex-1 ${right === 'portrait' ? '' : 'hidden'}`}>{portrait}</div>
            <div className={`min-h-0 flex-1 ${right === 'risks' ? '' : 'hidden'}`}>{risks}</div>
          </section>
        </div>
      )}
      {mode === 'narrow' && (
        <>
          <div role="tablist" aria-label="Разделы сессии" className="flex gap-1 border-b border-line px-2 py-1.5">{tabBtn('chat', 'Диалог', tab === 'chat', () => setTab('chat'))}{tabBtn('portrait', 'Портрет', tab === 'portrait', () => setTab('portrait'))}{tabBtn('risks', 'Риски', tab === 'risks', () => setTab('risks'))}</div>
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
