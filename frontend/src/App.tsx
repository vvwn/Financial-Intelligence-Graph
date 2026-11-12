import { useEffect, useState } from 'react'
import { Link, Route, Routes } from 'react-router-dom'

import { api, type ReadyPayload } from './services/api'

type ProbeState =
  | { kind: 'loading' }
  | { kind: 'ready'; payload: ReadyPayload }
  | { kind: 'degraded'; payload: ReadyPayload }
  | { kind: 'error'; message: string }

const PAGES = [
  { path: '/', label: '金融情报总览' },
  { path: '/graph', label: '产业知识图谱' },
  { path: '/events', label: '全球金融事件' },
  { path: '/opportunities', label: 'A股投资机会' },
  { path: '/quality', label: '图谱质量中心' },
  { path: '/history', label: '历史追踪与复盘' },
  { path: '/admin', label: '系统管理' },
]

function useReadiness(): ProbeState {
  const [state, setState] = useState<ProbeState>({ kind: 'loading' })

  useEffect(() => {
    let cancelled = false

    api
      .ready()
      .then(({ data }) => {
        if (!cancelled) setState({ kind: 'ready', payload: data })
      })
      .catch((err: unknown) => {
        const details = (err as { details?: { checks?: ReadyPayload['checks'] } }).details
        if (details?.checks) {
          if (!cancelled) {
            setState({
              kind: 'degraded',
              payload: { status: 'degraded', version: '', checks: details.checks },
            })
          }
          return
        }
        if (!cancelled) {
          setState({ kind: 'error', message: err instanceof Error ? err.message : '未知错误' })
        }
      })

    return () => {
      cancelled = true
    }
  }, [])

  return state
}

function StatusDot({ ok }: { ok: boolean }) {
  return (
    <span
      style={{
        display: 'inline-block',
        width: 7,
        height: 7,
        borderRadius: '50%',
        marginRight: 6,
        background: ok ? 'var(--ok)' : 'var(--danger)',
      }}
    />
  )
}

function Placeholder({ title }: { title: string }) {
  return (
    <section>
      <h1 style={{ fontSize: 18, fontWeight: 500, margin: '0 0 8px' }}>{title}</h1>
      <p style={{ color: 'var(--text-secondary)', margin: 0 }}>
        该页面属于 Phase 4 交付范围（TASK-503）。当前仅有骨架，接口契约见{' '}
        <code>docs/api-contracts.md</code>。
      </p>
    </section>
  )
}

export default function App() {
  const probe = useReadiness()

  return (
    <div style={{ display: 'flex', minHeight: '100%' }}>
      <aside
        style={{
          width: 208,
          borderRight: '1px solid var(--border)',
          background: 'var(--bg-panel)',
          padding: '16px 12px',
          flexShrink: 0,
        }}
      >
        <div style={{ fontSize: 15, fontWeight: 500, letterSpacing: '0.02em' }}>FIG</div>
        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 20 }}>
          金融情报图谱 · v0.1
        </div>

        <nav style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          {PAGES.map((p) => (
            <Link
              key={p.path}
              to={p.path}
              style={{
                padding: '7px 10px',
                borderRadius: 6,
                fontSize: 13,
                color: 'var(--text-secondary)',
              }}
            >
              {p.label}
            </Link>
          ))}
        </nav>

        <div
          style={{
            marginTop: 24,
            paddingTop: 12,
            borderTop: '1px solid var(--border)',
            fontSize: 11,
            color: 'var(--text-muted)',
          }}
        >
          {probe.kind === 'loading' && <span>依赖检查中…</span>}
          {probe.kind === 'error' && (
            <span>
              <StatusDot ok={false} />
              后端不可达
            </span>
          )}
          {(probe.kind === 'ready' || probe.kind === 'degraded') &&
            Object.entries(probe.payload.checks).map(([name, c]) => (
              <div key={name} style={{ marginBottom: 3 }}>
                <StatusDot ok={c.ok} />
                {name}
              </div>
            ))}
        </div>
      </aside>

      <main style={{ flex: 1, padding: '28px 32px', overflow: 'auto' }}>
        <Routes>
          <Route path="/" element={<Placeholder title="金融情报总览" />} />
          <Route path="/graph" element={<Placeholder title="产业知识图谱" />} />
          <Route path="/events" element={<Placeholder title="全球金融事件" />} />
          <Route path="/opportunities" element={<Placeholder title="A股投资机会" />} />
          <Route path="/quality" element={<Placeholder title="图谱质量中心" />} />
          <Route path="/history" element={<Placeholder title="历史追踪与复盘" />} />
          <Route path="/admin" element={<Placeholder title="系统管理" />} />
          <Route path="*" element={<Placeholder title="页面不存在" />} />
        </Routes>
      </main>
    </div>
  )
}
