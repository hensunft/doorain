import type { components } from './api-types'

type S = components['schemas']
export type Session = S['SessionOut']
export type Message = S['MessageOut']
export type Block = S['AnswerBlock']
export type CitationChip = S['CitationChip']
export type Citation = S['CitationOut']
export type RunSnapshot = S['RunSnapshot']
export type Graph = S['GraphOut']
export type GraphNode = S['GraphNodeOut']
export type GraphEdge = S['GraphEdgeOut']
export type TimelineItem = S['TimelineItem']
export type Risk = S['RiskOut']
export type Risks = S['RisksOut']
export type RiskDetail = S['RiskDetail']
export type SystemStatus = S['SystemStatus']
export type Diagnostics = S['Diagnostics']
export type CorpusOverview = S['CorpusOverview']
export type ManifestItem = S['ManifestItem']
export type Draft = S['DraftOut']
export type Doc = S['DocumentOut']
export type Revision = S['RevisionOut']
export type Job = S['JobOut']
export type Quiz = S['QuizOut']
export type QuizAttempt = S['QuizAttemptOut']
export type Export = S['ExportOut']
export type SearchHit = S['SearchHit']
export type ConfirmImport = S['ConfirmImportIn']
export type Role = S['SessionCreate']['role']
export type Level = NonNullable<Risk['level']>

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details?: unknown,
    public requestId?: string | null,
  ) {
    super(message)
  }
}

let csrf = ''
let onUnauthorized: (() => void) | null = null
export const setCsrf = (t: string) => { csrf = t }
export const setUnauthorizedHandler = (fn: (() => void) | null) => { onUnauthorized = fn }

export async function api<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {}
  let payload: BodyInit | undefined
  if (body instanceof FormData) payload = body
  else if (body !== undefined) { headers['Content-Type'] = 'application/json'; payload = JSON.stringify(body) }
  if (method !== 'GET') headers['X-CSRF-Token'] = csrf
  let res: Response
  try {
    res = await fetch(`/api/v1${path}`, { method, headers, body: payload, credentials: 'same-origin' })
  } catch {
    throw new ApiError(0, 'offline', 'Нет соединения с сервером')
  }
  if (res.status === 204) return undefined as T
  const text = await res.text()
  let data: unknown = null
  try { data = text ? JSON.parse(text) : null } catch { /* не JSON */ }
  if (!res.ok) {
    const d = (data ?? {}) as { code?: string; message?: string; details?: unknown; request_id?: string }
    if (res.status === 401 && path !== '/auth/login' && path !== '/auth/me') onUnauthorized?.()
    throw new ApiError(res.status, d.code ?? `http_${res.status}`, d.message ?? 'Ошибка запроса', d.details, d.request_id)
  }
  return data as T
}

export const get = <T,>(p: string) => api<T>('GET', p)
export const post = <T,>(p: string, b?: unknown) => api<T>('POST', p, b ?? {})
export const patch = <T,>(p: string, b: unknown) => api<T>('PATCH', p, b)
export const put = <T,>(p: string, b: unknown) => api<T>('PUT', p, b)
export const del = <T,>(p: string) => api<T>('DELETE', p)

export function errorText(e: unknown): string {
  if (e instanceof ApiError) return e.requestId ? `${e.message} (код запроса ${e.requestId})` : e.message
  return 'Неожиданная ошибка'
}

export const newRequestId = () => (crypto.randomUUID ? crypto.randomUUID().replaceAll('-', '') : String(Date.now()) + Math.random().toString(16).slice(2))
