import { useCallback, useEffect, useState } from 'react'
import type { Workspace } from '../api/contracts/index'
import type { RiskQueueItem } from '../api/contracts/index'
import { riskApi } from '../api/client'

export default function RiskQueue({ workspace, onOpen }: { workspace: Workspace; onOpen: (submissionId: string) => void }) {
  const [items, setItems] = useState<RiskQueueItem[]>([])
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState('all')
  const [loading, setLoading] = useState(true)
  const refresh = useCallback(() => { setLoading(true); void riskApi.list(workspace.id).then(setItems).catch(e => setError(e instanceof Error ? e.message : 'Risk queue could not be loaded.')).finally(() => setLoading(false)) }, [workspace.id])
  useEffect(() => { refresh() }, [refresh])
  const visible = items.filter(item => (filter === 'all' || item.severity === filter || item.automated_outcome === filter) &&
    `${item.source_label} ${item.title} ${item.explanation}`.toLowerCase().includes(query.toLowerCase()))
  return <><div className="page-heading"><div><div className="eyebrow">EXPLAINABLE PRIORITISATION</div><h1>Risk queue</h1><p>Unresolved review findings and changed public claims, ordered by their recorded risk score.</p></div><div className="heading-action"><button className="button button-secondary button-small" onClick={refresh}>↻ Refresh</button></div></div>
    {error && <div role="alert" className="feedback feedback-error">{error}</div>}<div className="filter-row"><div className="filter-tabs"><button className={filter === 'all' ? 'filter-active' : ''} onClick={() => setFilter('all')}>All · {items.length}</button><button className={filter === 'high' ? 'filter-active' : ''} onClick={() => setFilter('high')}>High severity</button><button className={filter === 'on_hold' ? 'filter-active' : ''} onClick={() => setFilter('on_hold')}>On hold</button><input aria-label="Search risk queue" value={query} onChange={e => setQuery(e.target.value)} placeholder="Search sources and findings" /></div></div>
    <section className="panel"><div className="panel-heading"><div><h2>Priority items</h2><p>Risk factors and evidence counts come from stored review records.</p></div><span className="panel-counter">{loading ? '…' : visible.length}</span></div>{loading ? <div className="mini-empty">Loading risk items…</div> : visible.length ? <div className="finding-list">{visible.map(item => <article className="finding-card" key={`${item.item_type}-${item.item_id}`}><div className="finding-head"><span className={`severity-mark severity-${item.severity}`}>{item.severity === 'high' ? '!' : '•'}</span><div><span className="finding-category">{item.item_type.replaceAll('_', ' ')} · {item.source_label}</span><h3>{item.title}</h3></div><span className="risk-score-pill">Risk {item.risk_score}/100</span></div><p>{item.explanation}</p><div className="risk-meta"><span>Assessment · {item.assessment?.replaceAll('_', ' ') ?? 'not assessed'}</span><span>Decision · {item.automated_outcome?.replaceAll('_', ' ') ?? 'pending'}</span><span>Evidence records · {item.evidence_count}</span><time>{new Date(item.created_at).toLocaleString()}</time></div>{item.item_type === 'finding' && <button className="button button-secondary button-xs" onClick={() => onOpen(item.source_id)}>Open submission</button>}</article>)}</div> : <div className="mini-empty">No unresolved items match this view.</div>}</section>
  </>
}
