import { useQuery } from '@tanstack/react-query'
import type { Citation, CorpusOverview, Diagnostics, Doc, Graph, Job, ManifestItem, Message, Quiz, Risks, RiskDetail, Session, SystemStatus, TimelineItem } from './api'
import { get } from './api'

export const keys = {
  me: ['me'] as const,
  sessions: (s: string) => ['sessions', s] as const,
  session: (id: string) => ['session', id] as const,
  messages: (id: string) => ['messages', id] as const,
  graph: (id: string) => ['graph', id] as const,
  timeline: (id: string) => ['timeline', id] as const,
  risks: (id: string) => ['risks', id] as const,
  risk: (id: string) => ['risk', id] as const,
  citation: (id: string) => ['citation', id] as const,
  status: ['status'] as const,
  diagnostics: ['diagnostics'] as const,
  corpus: ['corpus'] as const,
  manifest: ['manifest'] as const,
  documents: ['documents'] as const,
  jobs: ['jobs'] as const,
}

export const useSessions = (status: 'active' | 'archived' | 'all' = 'active') => useQuery({ queryKey: keys.sessions(status), queryFn: () => get<Session[]>(`/sessions?status=${status}`) })
export const useSession = (id: string) => useQuery({ queryKey: keys.session(id), queryFn: () => get<Session>(`/sessions/${id}`) })
export const useMessages = (id: string) => useQuery({ queryKey: keys.messages(id), queryFn: () => get<Message[]>(`/sessions/${id}/messages`) })
export const useGraph = (id: string) => useQuery({ queryKey: keys.graph(id), queryFn: () => get<Graph>(`/sessions/${id}/graph`) })
export const useTimeline = (id: string) => useQuery({ queryKey: keys.timeline(id), queryFn: () => get<TimelineItem[]>(`/sessions/${id}/timeline`) })
export const useRisks = (id: string) => useQuery({ queryKey: keys.risks(id), queryFn: () => get<Risks>(`/sessions/${id}/risks`) })
export const useRiskDetail = (id: string | null) => useQuery({ queryKey: keys.risk(id ?? ''), queryFn: () => get<RiskDetail>(`/risks/${id}`), enabled: !!id })
export const useCitation = (id: string | null) => useQuery({ queryKey: keys.citation(id ?? ''), queryFn: () => get<Citation>(`/citations/${id}`), enabled: !!id })
export const useStatus = () => useQuery({ queryKey: keys.status, queryFn: () => get<SystemStatus>('/system/status'), refetchInterval: 20_000 })
export const useDiagnostics = () => useQuery({ queryKey: keys.diagnostics, queryFn: () => get<Diagnostics>('/system/diagnostics') })
export const useCorpus = () => useQuery({ queryKey: keys.corpus, queryFn: () => get<CorpusOverview>('/corpus/overview'), refetchInterval: 5_000 })
export const useManifest = () => useQuery({ queryKey: keys.manifest, queryFn: () => get<ManifestItem[]>('/corpus/manifest') })
export const useDocuments = () => useQuery({ queryKey: keys.documents, queryFn: () => get<Doc[]>('/corpus/documents') })
export const useJobs = () => useQuery({ queryKey: keys.jobs, queryFn: () => get<Job[]>('/corpus/jobs'), refetchInterval: 3_000 })
export const useQuiz = (id: string | null) => useQuery({ queryKey: ['quiz', id], queryFn: () => get<Quiz>(`/quizzes/${id}`), enabled: !!id, refetchInterval: (q) => (q.state.data?.status === 'queued' ? 1500 : false) })
