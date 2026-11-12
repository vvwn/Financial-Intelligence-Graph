import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import App from './App'

vi.mock('./services/api', () => ({
  api: {
    ready: vi.fn().mockResolvedValue({
      data: {
        status: 'ready',
        version: '0.1.0',
        checks: { postgres: { ok: true, error: null }, neo4j: { ok: true, error: null } },
      },
      meta: { request_id: 'r1', generated_at: '2026-11-12T14:00:00Z' },
    }),
  },
}))

function renderApp() {
  return render(
    <MemoryRouter>
      <App />
    </MemoryRouter>,
  )
}

describe('App shell', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders the seven workbench entries', () => {
    renderApp()

    const links = screen.getAllByRole('link')
    expect(links).toHaveLength(7)
    expect(links.map((l) => l.textContent)).toEqual([
      '金融情报总览',
      '产业知识图谱',
      '全球金融事件',
      'A股投资机会',
      '图谱质量中心',
      '历史追踪与复盘',
      '系统管理',
    ])
  })

  it('shows dependency status from /ready', async () => {
    renderApp()

    expect(await screen.findByText('postgres')).toBeInTheDocument()
    expect(await screen.findByText('neo4j')).toBeInTheDocument()
  })
})
