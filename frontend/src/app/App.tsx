import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'
import { Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { LoginPage } from '../features/auth/LoginPage'
import { HistoryPage } from '../features/sessions/HistoryPage'
import { KnowledgeBasePage } from '../features/kb/KnowledgeBasePage'
import { SettingsPage } from '../features/settings/SettingsPage'
import { WelcomePage } from '../features/welcome/WelcomePage'
import { WorkspacePage } from '../features/workspace/WorkspacePage'
import { ApiError, get, setCsrf, setUnauthorizedHandler } from '../lib/api'
import type { components } from '../lib/api-types'
import { keys } from '../lib/queries'
import { ErrorNote, Skeleton } from '../components/States'
import { AppShell } from './AppShell'

type AuthOut = components['schemas']['AuthOut']

export function useMe() {
  return useQuery({
    queryKey: keys.me,
    retry: false,
    queryFn: async () => {
      const d = await get<AuthOut>('/auth/me')
      setCsrf(d.csrf_token)
      return d
    },
  })
}

function RequireAuth() {
  const me = useMe()
  const loc = useLocation()
  const nav = useNavigate()
  const qc = useQueryClient()
  useEffect(() => {
    setUnauthorizedHandler(() => { qc.clear(); nav('/login', { replace: true }) })
    return () => setUnauthorizedHandler(null)
  }, [nav, qc])
  if (me.isLoading) return <div className="mx-auto max-w-md p-8"><Skeleton lines={4} /></div>
  if (me.error instanceof ApiError && me.error.status === 401) return <Navigate to="/login" replace state={{ from: loc.pathname }} />
  if (me.isError) return <div className="mx-auto max-w-md p-8"><ErrorNote error={me.error} onRetry={() => me.refetch()} /></div>
  return <AppShell />
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<RequireAuth />}>
        <Route index element={<WelcomePage />} />
        <Route path="s/:id" element={<WorkspacePage />} />
        <Route path="history" element={<HistoryPage />} />
        <Route path="kb" element={<KnowledgeBasePage />} />
        <Route path="settings" element={<SettingsPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
