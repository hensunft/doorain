import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { LoginPage } from '../features/auth/LoginPage'
import { BlockView, SafeMarkdown } from '../features/workspace/MessageView'
import type { Block, CitationChip } from '../lib/api'
import { RiskBadge } from './ui'

const chip: CitationChip = { id: 'c1', marker: 'C1', label: '152-ФЗ', locator: 'ст. 18.1', revision_label: 'ред. 2026-03-01', verified: true, is_demo: false }
const claim = (text: string): Block => ({ id: 'b1', version: 1, kind: 'claim', text, citation_ids: ['c1'], markers: ['C1'], state: 'verified', removed: false }) as Block

afterEach(() => vi.restoreAllMocks())

describe('RiskBadge', () => {
  it('дублирует цвет текстом и числом', () => {
    render(<RiskBadge level="high" score={12} />)
    expect(screen.getByText('Высокий')).toBeInTheDocument()
    expect(screen.getByText('12')).toBeInTheDocument()
  })
  it('без оценки не показывает уровень', () => {
    render(<RiskBadge level={null} />)
    expect(screen.getByText('не оценён')).toBeInTheDocument()
  })
})

describe('безопасность рендера Markdown', () => {
  it('не исполняет и не рендерит произвольный HTML', () => {
    const { container } = render(<SafeMarkdown text={'Текст <script>window.__pwned=1</script> <img src=x onerror="window.__pwned=1"> <b>жирный</b>'} />)
    expect(container.querySelector('script')).toBeNull()
    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector('b')).toBeNull()
    expect((window as unknown as { __pwned?: number }).__pwned).toBeUndefined()
  })
  it('внешние ссылки не становятся активными и не загружают ресурсы', () => {
    const { container } = render(<SafeMarkdown text={'[перейти](https://evil.example) ![пикселей](https://evil.example/x.png)'} />)
    expect(container.querySelector('a')).toBeNull()
    expect(container.querySelector('img')).toBeNull()
  })
})

describe('BlockView', () => {
  it('утверждение показывает чипы источников, клик открывает источник', async () => {
    const onCite = vi.fn()
    render(<BlockView block={claim('Оператор обязан опубликовать политику.')} chips={[chip]} onCite={onCite} />)
    await userEvent.click(screen.getByRole('button', { name: /Открыть источник: 152-ФЗ, ст\. 18\.1/ }))
    expect(onCite).toHaveBeenCalledWith('c1')
  })
  it('отказ и неподтверждённый фрагмент — отдельные заметки, а не утверждения', () => {
    render(<><BlockView block={{ ...claim('Отказ'), kind: 'refusal', citation_ids: [] }} chips={[]} onCite={() => undefined} /><BlockView block={{ ...claim('Недостаточно данных'), kind: 'notice', state: 'unsupported', citation_ids: [] }} chips={[]} onCite={() => undefined} /></>)
    expect(screen.getAllByRole('note')).toHaveLength(2)
  })
  it('факты пользователя и допущения помечены отдельно', () => {
    render(<><BlockView block={{ ...claim('Со слов пользователя: сервер за рубежом.'), kind: 'fact' }} chips={[]} onCite={() => undefined} /><BlockView block={{ ...claim('Допущение: сайт в РФ.'), kind: 'assumption' }} chips={[]} onCite={() => undefined} /></>)
    expect(screen.getByText('Со слов пользователя')).toBeInTheDocument()
    expect(screen.getByText('Допущение')).toBeInTheDocument()
  })
})

describe('LoginPage', () => {
  const renderLogin = () => render(<QueryClientProvider client={new QueryClient()}><MemoryRouter><LoginPage /></MemoryRouter></QueryClientProvider>)
  it('нет регистрации, есть подсказка про локальное создание владельца', () => {
    renderLogin()
    expect(screen.queryByText(/зарегистрир/i)).toBeNull()
    expect(screen.getByText(/create-owner/)).toBeInTheDocument()
  })
  it('показывает единое сообщение об ошибке входа', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ code: 'invalid_credentials', message: 'Неверное имя пользователя или пароль', request_id: 'abc' }), { status: 401 })))
    renderLogin()
    await userEvent.type(screen.getByLabelText('Имя пользователя'), 'owner')
    await userEvent.type(screen.getByLabelText('Пароль'), 'wrong-password')
    await userEvent.click(screen.getByRole('button', { name: 'Войти' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Неверное имя пользователя или пароль')
  })
})
