import { BookOpenText, History, Menu, PanelLeftClose, PanelLeftOpen, Plus, Settings, ShieldUser } from 'lucide-react'
import { useState } from 'react'
import { Link, NavLink, Outlet, useLocation, useParams } from 'react-router-dom'
import { Dialog } from '../components/Dialog'
import { Footer } from '../components/Footer'
import { Banner, OfflineBanner } from '../components/States'
import { ThemeToggle } from '../components/ThemeToggle'
import { useMe } from './App'
import { useLayoutMode, useLocalState, useOnline } from '../lib/hooks'
import { useSessions, useStatus } from '../lib/queries'
import { ROLE_RU } from '../lib/risk'

function Brand({ compact }: { compact?: boolean }) {
  return (
    <Link to="/" className="flex items-center gap-2 px-2 py-1 no-underline" aria-label="DoorAIn — на главную">
      <img src="/favicon.svg" alt="" className="size-6" />
      {!compact && <span className="font-serif text-lg font-semibold tracking-tight text-ink">DoorAIn</span>}
    </Link>
  )
}

function SidebarNav({ compact, onNavigate }: { compact: boolean; onNavigate?: () => void }) {
  const sessions = useSessions('active')
  const isOwner = useMe().data?.user.access_level === 'owner'
  const { id } = useParams()
  const item = 'flex min-h-11 items-center gap-2 rounded-md px-2 py-1.5 text-small no-underline text-ink hover:bg-hover'
  const active = 'bg-selected font-medium'
  return (
    <nav aria-label="Основная навигация" className="flex min-h-0 flex-1 flex-col gap-1 px-2">
      <Link to="/" onClick={onNavigate} className={`btn mb-2 no-underline ${compact ? "btn-icon self-center" : ""}`}><Plus className="size-4" aria-hidden />{!compact && 'Новая сессия'}{compact && <span className="sr-only">Новая сессия</span>}</Link>
      <NavLink to="/history" onClick={onNavigate} className={({ isActive }) => `${item} ${isActive ? active : ''}`}><History className="size-4 shrink-0" aria-hidden />{compact ? <span className="sr-only">Мои сессии</span> : 'Мои сессии'}</NavLink>
      {isOwner && <NavLink to="/kb" onClick={onNavigate} className={({ isActive }) => `${item} ${isActive ? active : ''}`}><BookOpenText className="size-4 shrink-0" aria-hidden />{compact ? <span className="sr-only">База знаний</span> : 'База знаний'}</NavLink>}
      {isOwner && <NavLink to="/admin" onClick={onNavigate} className={({ isActive }) => `${item} ${isActive ? active : ''}`}><ShieldUser className="size-4 shrink-0" aria-hidden />{compact ? <span className="sr-only">Администрирование</span> : 'Администрирование'}</NavLink>}
      <NavLink to="/settings" onClick={onNavigate} className={({ isActive }) => `${item} ${isActive ? active : ''}`}><Settings className="size-4 shrink-0" aria-hidden />{compact ? <span className="sr-only">Настройки</span> : 'Настройки'}</NavLink>
      {!compact && (
        <div className="mt-4 min-h-0 flex-1 overflow-y-auto">
          <h2 className="px-2 pb-1 text-xs font-medium text-muted">Недавние сессии</h2>
          {sessions.data?.length === 0 && <p className="px-2 text-small text-muted">Пока нет сессий</p>}
          <ul className="space-y-0.5">
            {sessions.data?.slice(0, 10).map((s) => (
              <li key={s.id}>
                <Link to={`/s/${s.id}`} onClick={onNavigate} title={s.title} aria-current={id === s.id ? 'page' : undefined} className={`${item} ${id === s.id ? active : ''} flex-col !items-start gap-0`}>
                  <span className="w-full truncate">{s.title}</span>
                  <span className="text-xs text-muted">{ROLE_RU[s.role]}</span>
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
    </nav>
  )
}

/** Низ боковой панели: имя пользователя и тема — ниже навигации и списка сессий; в свёрнутом виде — иконки с подписями. */
function SidebarFooter({ compact, onNavigate }: { compact: boolean; onNavigate?: () => void }) {
  const user = useMe().data?.user
  const name = user?.display_name ?? ''
  const initials = name.split(/\s+/).map((w) => w[0]).join('').slice(0, 2).toUpperCase()
  return (
    <div className={`mt-auto flex shrink-0 gap-2 border-t border-line px-2 pt-2 ${compact ? 'flex-col items-center' : 'items-center justify-between'}`}>
      <Link to="/settings" onClick={onNavigate} className={`flex min-h-11 min-w-0 items-center gap-2 rounded-md px-1 text-small text-ink no-underline hover:bg-hover ${compact ? 'justify-center' : ''}`} title={compact ? `${name} — профиль и настройки` : 'Профиль и настройки'} aria-label={compact ? `${name}: профиль и настройки` : undefined}>
        <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-selected text-xs font-semibold" aria-hidden>{initials || '?'}</span>
        {!compact && <span className="truncate">{name}</span>}
      </Link>
      <ThemeToggle compact={compact} />
    </div>
  )
}

export function AppShell() {
  const mode = useLayoutMode()
  const [collapsed, setCollapsed] = useLocalState('doorain.sidebar.collapsed', false)
  const [menu, setMenu] = useState(false)
  const online = useOnline()
  const status = useStatus()
  const loc = useLocation()
  const inWorkspace = loc.pathname.startsWith('/s/')
  const compact = (collapsed || inWorkspace) && mode !== 'narrow'
  return (
    <div className="flex h-dvh min-h-0 flex-col">
      {!online && <OfflineBanner />}
      {status.data?.maintenance && <Banner tone="warn">Идёт обслуживание или резервное копирование: запись временно недоступна.</Banner>}
      <div className="flex min-h-0 flex-1">
        {mode !== 'narrow' && (
          <aside className={`flex shrink-0 flex-col gap-2 border-r border-line bg-sidebar py-2 transition-[width] duration-150 ${compact ? 'w-14' : 'w-60'}`}>
            <div className="flex items-center justify-between px-1">
              <Brand compact={compact} />
              {!compact && <button className="btn btn-tertiary btn-icon" aria-label="Свернуть панель" onClick={() => setCollapsed(true)}><PanelLeftClose className="size-4" aria-hidden /></button>}
            </div>
            {compact && !inWorkspace && <button className="btn btn-tertiary btn-icon mx-auto" aria-label="Развернуть панель" onClick={() => setCollapsed(false)}><PanelLeftOpen className="size-4" aria-hidden /></button>}
            <SidebarNav compact={compact} />
            <SidebarFooter compact={compact} />
          </aside>
        )}
        <div className="flex min-w-0 flex-1 flex-col">
          {mode === 'narrow' && (
            <div className="flex items-center gap-2 border-b border-line bg-sidebar px-2 py-1.5">
              <button className="btn btn-tertiary btn-icon" aria-label="Открыть меню" onClick={() => setMenu(true)}><Menu className="size-5" aria-hidden /></button>
              <Brand />
            </div>
          )}
          <main className={`min-h-0 flex-1 ${inWorkspace ? 'overflow-hidden' : 'flex flex-col overflow-y-auto'}`}>
            {inWorkspace ? <Outlet /> : <><div className="flex-1"><Outlet /></div><Footer className="border-t border-line px-4 py-3" /></>}
          </main>
          {inWorkspace && mode !== 'narrow' && <Footer className="border-t border-line bg-page px-4 py-1.5" />}
        </div>
      </div>
      <Dialog open={menu} onClose={() => setMenu(false)} title="Меню" variant="side"><div className="-mx-3 flex h-full flex-col gap-2"><SidebarNav compact={false} onNavigate={() => setMenu(false)} /><SidebarFooter compact={false} onNavigate={() => setMenu(false)} /><Footer className="px-3 pb-2" /></div></Dialog>
    </div>
  )
}
