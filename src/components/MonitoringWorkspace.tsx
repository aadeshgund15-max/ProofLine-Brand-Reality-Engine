import { useCallback, useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import type { Workspace } from '../api/contracts/index'
import { monitoringApi, productIntelligenceApi } from '../api/client'

export default function MonitoringWorkspace({ workspace }: { workspace: Workspace }) {
  const [sources, setSources] = useState<Awaited<ReturnType<typeof monitoringApi.sources>>>([])
  const [changes, setChanges] = useState<Awaited<ReturnType<typeof monitoringApi.changes>>>([])
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState('')
  const [label, setLabel] = useState('')
  const [url, setUrl] = useState('')
  const [interval, setInterval] = useState(60)
  const [reasons, setReasons] = useState<Record<string, string>>({})
  const [products, setProducts] = useState<Awaited<ReturnType<typeof productIntelligenceApi.list>>>([])
  const [productLoadError, setProductLoadError] = useState('')
  const [productId, setProductId] = useState('')
  const refresh = useCallback(async () => {
    try { const [s, c] = await Promise.all([monitoringApi.sources(workspace.id), monitoringApi.changes(workspace.id)]); setSources(s); setChanges(c); setError('') }
    catch (e) { setError(e instanceof Error ? e.message : 'Could not load monitoring data.') }
  }, [workspace.id])
  useEffect(() => { void refresh() }, [refresh])
  useEffect(() => {
    let active = true
    void productIntelligenceApi.list(workspace.id).then(items => {
      if (active) { setProducts(items); setProductLoadError('') }
    }).catch(e => {
      if (active) setProductLoadError(e instanceof Error ? e.message : 'Could not load products.')
    })
    return () => { active = false }
  }, [workspace.id])
  const act = async (key: string, fn: () => Promise<unknown>, message: string) => {
    setBusy(key); setError(''); setNotice('')
    try { await fn(); setNotice(message); await refresh(); return true }
    catch (e) { setError(e instanceof Error ? e.message : 'The request failed.'); return false }
    finally { setBusy('') }
  }
  const add = (e: FormEvent) => {
    e.preventDefault()
    void act('add', () => monitoringApi.create(workspace.id, { url: url.trim(), label: label.trim(), interval_minutes: interval, product_id: productId || undefined }), 'Public source registered for scheduled checks.')
      .then(ok => { if (ok) { setLabel(''); setUrl(''); setProductId('') } })
  }
  const decide = (id: string, status: 'reviewed' | 'dismissed') => {
    const reason = (reasons[id] ?? '').trim()
    if (reason.length < 3) { setError('Add a short rationale before updating this alert.'); return }
    void act(id, () => monitoringApi.updateChange(workspace.id, id, status, reason), `Change marked ${status}.`)
  }
  return <><div className="page-heading"><div><div className="eyebrow">CONTINUOUS BRAND MONITORING</div><h1>Published content</h1><p>Scheduled snapshots, change alerts, and automatic re-review of changed page text.</p></div><div className="heading-action"><button className="button button-secondary button-small" onClick={() => void refresh()}>↻ Refresh</button></div></div>
    {error && <div role="alert" className="feedback feedback-error">{error}</div>}{notice && <div role="status" className="feedback feedback-success">{notice}</div>}
    <div className="stats-grid"><div className="stat-card"><div className="stat-label">Active sources</div><div className="stat-value">{sources.filter(s => s.status === 'active').length}</div></div><div className="stat-card"><div className="stat-label">Open changes</div><div className="stat-value">{changes.filter(c => c.status === 'open').length}</div></div><div className="stat-card"><div className="stat-label">Sources in error</div><div className="stat-value">{sources.filter(s => s.status === 'error').length}</div></div></div>
    <section className="panel product-monitor-link">{productLoadError && <div role="alert" className="feedback feedback-error">Product list could not be loaded: {productLoadError}<button className="button button-secondary button-xs" onClick={() => { setProductLoadError(''); void productIntelligenceApi.list(workspace.id).then(setProducts).catch(e => setProductLoadError(e instanceof Error ? e.message : 'Could not load products.')) }}>Retry</button></div>}<label className="field"><span>Associate new monitored pages with a product</span><select disabled={!!productLoadError} value={productId} onChange={e => setProductId(e.target.value)}><option value="">No product association</option>{products.map(product => <option key={product.id} value={product.id}>{product.brand ? `${product.brand} · ` : ''}{product.product_name} · {product.model_number || 'model unspecified'}</option>)}</select></label><small className="field-caption">Product-linked changes include product identifiers in the shared re-review decision. Create the product profile first in Product Research.</small></section>
    <div className="team-layout monitoring-layout"><section className="panel"><div className="panel-heading"><div><h2>Monitored sources</h2><p>A separate worker process checks due public pages; a browser tab is not required.</p></div><span className="panel-counter">{sources.length}</span></div>{sources.length ? <div className="monitor-source-list">{sources.map(source => <article className="monitor-source" key={source.id}><div className="monitor-source-main"><div><b>{source.label}</b><a href={source.url} target="_blank" rel="noreferrer">{source.url}</a></div><span className={`status-pill status-${source.status}`}><span />{source.status}</span></div><small>Every {source.interval_minutes} min · snapshots {source.snapshot_count} · open alerts {source.open_changes}</small><small>Last checked {source.last_checked_at ? new Date(source.last_checked_at).toLocaleString() : 'Not checked yet'} · next {new Date(source.next_check_at).toLocaleString()}</small><div className="monitor-actions"><button className="button button-secondary button-xs" disabled={!!busy} onClick={() => void act(source.id, () => monitoringApi.check(workspace.id, source.id), 'Monitoring check queued for the background worker.')}>Check now</button>{source.status === 'active' ? <button className="button button-secondary button-xs" disabled={!!busy} onClick={() => void act(source.id, () => monitoringApi.update(workspace.id, source.id, { status: 'paused' }), 'Source paused.')}>Pause</button> : <button className="button button-secondary button-xs" disabled={!!busy} onClick={() => void act(source.id, () => monitoringApi.update(workspace.id, source.id, { status: 'active' }), 'Source resumed.')}>Resume</button>}<button className="button button-secondary button-xs" disabled={!!busy} onClick={() => { if (window.confirm(`Remove monitoring for ${source.label}? History will remain.`)) void act(source.id, () => monitoringApi.update(workspace.id, source.id, { status: 'removed' }), 'Source removed; history retained.') }}>Remove</button></div></article>)}</div> : <div className="mini-empty">No public sources registered.</div>}</section>
      <section className="panel"><div className="form-panel-header"><span className="form-panel-icon">↻</span><div><h2>Register a public page</h2><p>Unsafe addresses and redirects are blocked by the server.</p></div></div>{workspace.role === 'owner' || workspace.role === 'editor' ? <form className="form-stack" onSubmit={add}><label className="field"><span>Source label</span><input required maxLength={120} value={label} onChange={e => setLabel(e.target.value)} placeholder="Product page" /></label><label className="field"><span>Public URL</span><input required type="url" value={url} onChange={e => setUrl(e.target.value)} placeholder="https://example.com/product" /></label><label className="field"><span>Check interval</span><select value={interval} onChange={e => setInterval(Number(e.target.value))}><option value={60}>Every hour</option><option value={360}>Every 6 hours</option><option value={1440}>Daily</option><option value={10080}>Weekly</option></select></label><button className="button button-primary button-wide" disabled={busy === 'add'}>{busy === 'add' ? 'Registering…' : 'Register source'} →</button></form> : <p className="permission-note">Owner or editor permissions required.</p>}</section></div>
    <section className="panel monitoring-alerts"><div className="panel-heading"><div><h2>Change intelligence</h2><p>New or changed text is stored with a before-and-after snapshot and re-reviewed.</p></div><span className="panel-counter">{changes.length}</span></div>{changes.length ? <div className="finding-list">{changes.map(change => <article className="finding-card" key={change.id}><div className="finding-head"><span className="severity-mark severity-medium">↻</span><div><span className="finding-category">{change.label} · snapshot {change.previous_version} → {change.current_version}</span><h3>{change.change_summary}</h3><small>{new Date(change.created_at).toLocaleString()} · status {change.status}</small></div>{change.outcome && <span className={`status-pill status-${change.outcome}`}>{change.outcome.replaceAll('_', ' ')}</span>}</div><pre className="change-diff">{change.change_excerpt || 'Text changed, but no concise line diff was produced.'}</pre>{change.review_status && <p className="side-copy">Automatic review: {change.review_status}; risk {change.risk_score ?? '—'}/100. {change.report?.decision_rationale ? String(change.report.decision_rationale) : ''}</p>}{change.status === 'open' && (workspace.role === 'owner' || workspace.role === 'reviewer') && <div className="monitor-actions"><input aria-label="Review rationale" value={reasons[change.id] ?? ''} onChange={e => setReasons(v => ({ ...v, [change.id]: e.target.value }))} placeholder="Reason for updating this alert" /><button className="button button-secondary button-xs" disabled={!!busy} onClick={() => decide(change.id, 'reviewed')}>Mark reviewed</button><button className="button button-secondary button-xs" disabled={!!busy} onClick={() => decide(change.id, 'dismissed')}>Dismiss</button></div>}</article>)}</div> : <div className="mini-empty">No changes detected yet. First check captures the baseline snapshot.</div>}</section>
  </>
}
