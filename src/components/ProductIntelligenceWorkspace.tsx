import { useCallback, useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import type { ProductCoverage, ProductRecord, SourceAssessment } from '../api/contracts/index'
import { productIntelligenceApi, submissionApi } from '../api/client'

export default function ProductIntelligenceWorkspace({ workspace }: { workspace: { id: string; role: string } }) {
  const [products, setProducts] = useState<ProductRecord[]>([])
  const [submissionOptions, setSubmissionOptions] = useState<Awaited<ReturnType<typeof submissionApi.list>>>([])
  const [submissionLoadError, setSubmissionLoadError] = useState('')
  const [selected, setSelected] = useState('')
  const [productSearch, setProductSearch] = useState('')
  const [selectedSubmission, setSelectedSubmission] = useState('')
  const [detail, setDetail] = useState<Awaited<ReturnType<typeof productIntelligenceApi.detail>> | null>(null)
  const [provider, setProvider] = useState<{ search_provider: string; configured: boolean; message: string } | null>(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [form, setForm] = useState({ product_name: '', brand: '', manufacturer: '', model_number: '', product_category: '', market: '', official_website: '', confirm_identity: false })
  const refresh = useCallback(async (id?: string) => {
    try {
      const [items, status] = await Promise.all([productIntelligenceApi.list(workspace.id), productIntelligenceApi.status(workspace.id)])
      setProducts(items); setProvider(status)
      const nextId = id ?? (items.some(item => item.id === selected) ? selected : items[0]?.id || '')
      setSelected(nextId)
      setDetail(nextId ? await productIntelligenceApi.detail(workspace.id, nextId) : null)
      setError('')
    } catch (e) { setError(e instanceof Error ? e.message : 'Could not load product research.') }
  }, [workspace.id, selected])
  useEffect(() => { void refresh() }, [refresh])
  useEffect(() => {
    let active = true
    void submissionApi.list(workspace.id).then(items => {
      if (active) { setSubmissionOptions(items); setSubmissionLoadError('') }
    }).catch(e => {
      if (active) setSubmissionLoadError(e instanceof Error ? e.message : 'Could not load submissions.')
    })
    return () => { active = false }
  }, [workspace.id])
  const act = async (fn: () => Promise<unknown>, success: string, reload = true) => {
    setBusy(true); setError(''); setNotice('')
    try { await fn(); setNotice(success); if (reload) await refresh() }
    catch (e) { setError(e instanceof Error ? e.message : 'The request failed.') }
    finally { setBusy(false) }
  }
  const create = (e: FormEvent) => {
    e.preventDefault()
    void act(async () => {
      const created = await productIntelligenceApi.create(workspace.id, { ...form, brand: form.brand || null,
        manufacturer: form.manufacturer || null, model_number: form.model_number || null,
        product_category: form.product_category || null, market: form.market || null,
        official_website: form.official_website || null })
      setForm({ product_name: '', brand: '', manufacturer: '', model_number: '', product_category: '', market: '', official_website: '', confirm_identity: false })
      await refresh(created.id)
    }, 'Product identity profile created.', false)
  }
  const current = detail
  const coverage = current?.profile?.coverage ?? (current?.latest_run?.coverage as ProductCoverage | undefined)
  const visibleProducts = products.filter(item => `${item.brand || ''} ${item.product_name} ${item.manufacturer || ''} ${item.model_number || ''}`.toLowerCase().includes(productSearch.trim().toLowerCase()))
  return <>
    <div className="page-heading"><div><div className="eyebrow">PRODUCT INTELLIGENCE ENGINE</div><h1>Product research</h1><p>Investigate discoverable public sources for an exact product and connect the research to submission reviews.</p></div><button className="button button-secondary button-small" onClick={() => void refresh()}>↻ Refresh</button></div>
    {error && <div role="alert" className="feedback feedback-error">{error}</div>}{notice && <div role="status" className="feedback feedback-success">{notice}</div>}
    {provider && !provider.configured && <div role="status" className="feedback feedback-error">Search is not configured. {provider.message}</div>}
    <div className="team-layout product-layout">
      <section className="panel"><div className="panel-heading"><div><h2>Product profiles</h2><p>Identity details are user supplied; Proofline never merges similar names automatically.</p></div><span className="panel-counter">{products.length}</span></div>
        {products.length > 0 && <label className="field product-search"><span>Search saved products</span><input type="search" value={productSearch} onChange={e => setProductSearch(e.target.value)} placeholder="Name, brand, manufacturer, or model" /></label>}
        {visibleProducts.length ? <div className="monitor-source-list">{visibleProducts.map(item => <button className={`product-pick ${selected === item.id ? 'product-pick-active' : ''}`} key={item.id} onClick={() => { setSelected(item.id); void refresh(item.id) }}><b>{item.brand ? `${item.brand} · ` : ''}{item.product_name}</b><small>{item.model_number || 'Model not provided'} · identity {item.identity_status} · research {item.latest_research_status || 'not started'}</small></button>)}</div> : products.length ? <div className="mini-empty">No product profiles match that search.</div> : <div className="mini-empty">No product profiles yet.</div>}
        <form className="form-stack product-create" onSubmit={create}><h3>Add exact product details</h3>
          <label className="field"><span>Product or service name</span><input required minLength={2} maxLength={200} value={form.product_name} onChange={e => setForm({ ...form, product_name: e.target.value })} /></label>
          <label className="field"><span>Brand</span><input value={form.brand} onChange={e => setForm({ ...form, brand: e.target.value })} /></label>
          <label className="field"><span>Manufacturer</span><input value={form.manufacturer} onChange={e => setForm({ ...form, manufacturer: e.target.value })} /></label>
          <label className="field"><span>Model / version identifier</span><input value={form.model_number} onChange={e => setForm({ ...form, model_number: e.target.value })} /></label>
          <label className="field"><span>Product category</span><input value={form.product_category} onChange={e => setForm({ ...form, product_category: e.target.value })} /></label>
          <label className="field"><span>Market or country</span><input value={form.market} onChange={e => setForm({ ...form, market: e.target.value })} /></label>
          <label className="field"><span>Official website, if known</span><input type="url" value={form.official_website} onChange={e => setForm({ ...form, official_website: e.target.value })} placeholder="https://" /></label>
          <label className="product-confirm"><input type="checkbox" checked={form.confirm_identity} onChange={e => setForm({ ...form, confirm_identity: e.target.checked })} /> I confirm these details identify the exact advertised product.</label>
          <button className="button button-primary button-wide" disabled={busy || workspace.role === 'reviewer'}>Save product profile</button>
        </form>
      </section>
      <section className="panel product-research-panel"><div className="panel-heading"><div><h2>Research record</h2><p>Source and query records are saved for each research run.</p></div>{current && <button className="button button-primary button-small" disabled={busy || workspace.role === 'reviewer' || current.latest_run?.status === 'queued' || current.latest_run?.status === 'running'} onClick={() => void act(() => productIntelligenceApi.research(workspace.id, current.product.id), 'Product research queued. Start the product research worker to process it.')}>Research / refresh</button>}</div>
        {!current ? <div className="mini-empty">Create or select a product profile to begin.</div> : <>
          <div className="product-identity"><div><span className="eyebrow">{current.product.product_category || 'PRODUCT'}</span><h3>{current.product.brand ? `${current.product.brand} · ` : ''}{current.product.product_name}</h3><p>{[current.product.manufacturer, current.product.model_number, current.product.market].filter(Boolean).join(' · ') || 'Add a manufacturer, model, and market to reduce identity ambiguity.'}</p></div><span className={`status-pill status-${current.product.identity_status}`}>{current.product.identity_status}</span></div>
          {current.latest_run && <div className="stats-grid product-coverage"><Metric label="Queries executed" value={coverage?.queries_executed ?? current.queries.length} /><Metric label="Search results" value={coverage?.search_results_discovered ?? current.queries.reduce((sum, query) => sum + Number(query.result_count || 0), 0)} /><Metric label="Unique sources" value={coverage?.unique_sources ?? current.sources.length} /><Metric label="Pages inspected" value={coverage?.sources_inspected ?? current.sources.filter(source => source.access_status === 'ok' && !['empty', 'failed', 'unsupported'].includes(source.extraction_status)).length} /><Metric label="Inaccessible" value={coverage?.sources_inaccessible ?? current.sources.filter(source => source.access_status !== 'ok' || ['empty', 'failed', 'unsupported'].includes(source.extraction_status)).length} /><Metric label="Cached pages" value={coverage?.cached_sources_used ?? current.sources.filter(source => source.cached).length} /><Metric label="Quoted facts" value={coverage?.product_facts_supported ?? 0} /><Metric label="Profile extraction" value={coverage?.profile_extraction_status || 'not assessed'} /><Metric label="Claims assessed" value={current.claim_coverage.claims_evaluated} /><Metric label="Supporting sources" value={current.claim_coverage.supporting_sources} /><Metric label="Contradicting sources" value={current.claim_coverage.contradicting_sources} /><Metric label="Inconclusive claims" value={current.claim_coverage.claims_inconclusive} /></div>}
          {current.latest_run?.error_summary && <div className="feedback feedback-error">{String(current.latest_run.error_summary)}</div>}
          <p className="product-transparency">Research is limited to sources found by the configured provider and pages safely accessible to Proofline. Source assessments show rule-based signals and unknowns; they do not certify sources or verify claims.</p>
          {current.queries.length > 0 && <details className="product-record"><summary>Queries executed ({current.queries.length})</summary>{current.queries.map(q => <div className="product-query" key={String(q.id)}><b>{String(q.category).replaceAll('_', ' ')}</b><span>{String(q.status)} · {String(q.result_count)} results</span><p>{String(q.query_text)}</p>{q.error_code != null && String(q.error_code) !== '' && <small>{String(q.error_code)}</small>}</div>)}</details>}
          <div className="product-sources"><div className="panel-heading"><div><h3>Discovered sources</h3><p>{current.sources.length} stored source records for the latest run</p></div></div>
            {current.sources.length ? current.sources.map(source => <article className="product-source" key={source.id}><div className="product-source-head"><b>{source.title}</b><span className="role-chip">{source.source_category.replaceAll('_', ' ')}</span></div><a href={safePublicUrl(source.url) || undefined} target="_blank" rel="noreferrer">{source.domain}</a><small>{source.access_status} · {source.extraction_status} · product match {source.product_match_status} · retrieved {new Date(source.retrieved_at).toLocaleString()}</small>{source.published_at && <small>Publication date reported by search provider: {source.published_at}</small>}{source.cached && <small>Reused a page safely fetched within the last 24 hours.</small>}{source.duplicate_of && <small>Duplicate content hash detected against an earlier record.</small>}{source.source_assessment && <details className="product-record"><summary>Source assessment · {source.source_assessment.overall_status.replaceAll('_', ' ')}</summary><div className="source-assessment-grid">{Object.entries(source.source_assessment.signals).map(([name, signal]) => <div key={name} className="source-assessment-item"><b>{name.replaceAll('_', ' ')} · {signal.status.replaceAll('_', ' ')}</b><p>{signal.reason}</p></div>)}</div>{source.source_assessment.limitations.map(item => <small className="source-assessment-limit" key={item}>{item}</small>)}<small>Policy {source.source_assessment.policy_version}{source.source_assessment.assessed_at ? ` · assessed ${new Date(source.source_assessment.assessed_at).toLocaleString()}` : ''}</small></details>}{source.query_ids?.length ? <details><summary>Discovered by {source.query_ids.length} search query record(s)</summary>{source.query_ids.map(id => { const query = current.queries.find(item => String(item.id) === id); return query && <p className="product-query-provenance" key={id}><b>{String(query.category).replaceAll('_', ' ')}</b><br />{String(query.query_text)}</p> })}</details> : null}{source.excerpt && <details><summary>Page excerpt</summary><p>{source.excerpt}</p></details>}</article>) : <div className="mini-empty">No source records yet. Queue a research run and start the worker.</div>}
          </div>
          {current.profile && <div className="product-profile"><div className="panel-heading"><div><h3>Product profile · v{current.profile.version_no}</h3><p>Updated {new Date(current.profile.created_at).toLocaleString()}</p></div><span className="role-chip">{current.profile.coverage.profile_extraction_status || 'not assessed'}</span></div><p className="side-copy">These are source-bound observations copied from inspected pages. They have not been independently verified, checked against authoritative registries, or assessed for source independence.</p>{current.profile.profile.facts?.length ? <div className="product-claims">{current.profile.profile.facts.map((fact, index) => <article className="product-claim" key={`${fact.source_id}-${index}`}><div className="product-source-head"><b>{fact.category.replaceAll('_', ' ')}</b><span className="role-chip">supported by cited page</span></div><blockquote>{fact.quote}</blockquote><a href={safePublicUrl(fact.source_url) || undefined} target="_blank" rel="noreferrer">{fact.source_title}</a><small>Retrieved {new Date(fact.retrieved_at).toLocaleString()} · exact passage retained</small></article>)}</div> : <div className="mini-empty">No product facts passed source and exact-quote checks. This research is inconclusive and cannot satisfy the product review gate.</div>}{current.profile.profile.warnings?.map(warning => <p className="side-copy" key={warning}>{warning}</p>)}{current.profile.profile.limitations_note && <p className="side-copy">{current.profile.profile.limitations_note}</p>}</div>}
          <div className="product-profile"><div className="panel-heading"><div><h3>Marketing claim investigations</h3><p>Latest saved review for each linked submission version; only inspected, identifier-matched sources appear as product evidence.</p></div></div>
            {current.claims.length ? <div className="product-claims">{current.claims.map(claim => <article className="product-claim" key={claim.finding_id}><div className="product-source-head"><b>{claim.claim_text || claim.finding_title}</b><span className={`status-pill status-${claim.verification_status || 'unknown'}`}>{(claim.verification_status || 'not assessed').replaceAll('_', ' ')}</span></div><small>Submission: {claim.submission_title}</small><p>{claim.explanation}</p>{claim.evidence?.length ? <div className="product-claim-evidence">{claim.evidence.map(evidence => <div className="product-evidence-row" key={evidence.source_id}><div className="product-source-head"><b>{evidence.source_title}</b><span className="role-chip">{evidence.stance}</span></div><a href={safePublicUrl(evidence.source_url) || undefined} target="_blank" rel="noreferrer">{evidence.publisher || evidence.source_url}</a><blockquote>{evidence.evidence_excerpt}</blockquote><small>{evidence.product_research_source_id ? 'Linked to the product research source record.' : 'Found during claim-specific web search.'}{evidence.published_at ? ` Publication date: ${evidence.published_at}.` : ''}</small>{evidence.source_assessment && <SourceAssessmentDetails assessment={evidence.source_assessment} />}{evidence.search_query && <details><summary>Search provenance</summary><p>{evidence.search_query}</p></details>}</div>)}</div> : <div className="mini-empty">No source passage was retained for this claim. The review status remains inconclusive.</div>}</article>)}</div> : <div className="mini-empty">No claim review records are linked to this product yet. Link the product to a submission version and run a review.</div>}
          </div>
          <div className="product-profile"><div className="panel-heading"><div><h3>Connect to a submission</h3><p>Reviews use the product identity in claim-search context and hold approval until research is complete.</p></div></div>{submissionLoadError && <div role="alert" className="feedback feedback-error">Submissions could not be loaded: {submissionLoadError}<button className="button button-secondary button-xs" onClick={() => { setSubmissionLoadError(''); void submissionApi.list(workspace.id).then(setSubmissionOptions).catch(e => setSubmissionLoadError(e instanceof Error ? e.message : 'Could not load submissions.')) }}>Retry</button></div>}<label className="field"><span>Submission to link</span><select disabled={!!submissionLoadError} value={selectedSubmission} onChange={e => setSelectedSubmission(e.target.value)}><option value="">Choose a submission</option>{submissionOptions.map(item => <option key={item.id} value={item.revision?.id}>{item.title} · revision {item.revision?.no}</option>)}</select></label><button className="button button-secondary button-small" disabled={busy || !!submissionLoadError || !selectedSubmission || workspace.role === 'reviewer'} onClick={() => void act(() => submissionApi.linkProduct(workspace.id, selectedSubmission, current.product.id), 'Product linked to the submission version.')}>Link product to submission</button><small className="field-caption">A version can link one product. To change the product, create a new submission version.</small></div>
        </>}
      </section>
    </div>
  </>
}

function Metric({ label, value }: { label: string; value: number | string }) { return <div className="stat-card"><div className="stat-label">{label}</div><div className="stat-value">{value}</div></div> }
function safePublicUrl(value: string) { try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) ? url.toString() : '' } catch { return '' } }
function SourceAssessmentDetails({ assessment }: { assessment: SourceAssessment }) {
  return <details className="product-record"><summary>Source signals · {assessment.overall_status.replaceAll('_', ' ')}</summary><div className="source-assessment-grid">{Object.entries(assessment.signals).map(([name, signal]) => <div key={name} className="source-assessment-item"><b>{name.replaceAll('_', ' ')} · {signal.status.replaceAll('_', ' ')}</b><p>{signal.reason}</p></div>)}</div>{assessment.limitations.map(item => <small className="source-assessment-limit" key={item}>{item}</small>)}<small>Policy {assessment.policy_version}{assessment.assessed_at ? ` · assessed ${new Date(assessment.assessed_at).toLocaleString()}` : ''}</small></details>
}
