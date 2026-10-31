import type { ApiErrorBody, AuditEvent, AutomatedDecision, BrandSource, DashboardSummary, Decision, Finding, Impact, Member, MonitoringChange, MonitoredSource, PaletteVersion, Profile, ProductClaim, ProductClaimCoverage, ProductCoverage, ProductFact, ProductRecord, ProductSource, ReviewFinding, ReviewResult, RiskQueueItem, Session, SourceVersion, SubmissionDetail, SubmissionEvidence, VisualAnalysis, VisualAsset, Workspace } from './contracts/index'
import { requireSupabase, supabase } from './supabase'

const apiBase = (import.meta.env.VITE_API_BASE ?? '').trim().replace(/\/$/, '')
const storageTokenExists = () => Object.keys(localStorage).some(key => key.startsWith('sb-') && key.endsWith('-auth-token'))

export const session = {
  clear() { void supabase?.auth.signOut() },
  exists() { return storageTokenExists() },
}

export class ApiError extends Error {
  constructor(message: string, readonly status?: number) { super(message); this.name = 'ApiError' }
}

type RequestOptions = { method?: string; body?: unknown; form?: FormData }
async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers = new Headers()
  const { data: { session: authSession } } = await supabase?.auth.getSession() ?? { data: { session: null } }
  if (authSession?.access_token) headers.set('Authorization', `Bearer ${authSession.access_token}`)
  let body: BodyInit | undefined
  if (options.form) body = options.form
  else if (options.body !== undefined) { headers.set('Content-Type', 'application/json'); body = JSON.stringify(options.body) }
  let response: Response
  try {
    response = await fetch(`${apiBase}/api${path}`, { method: options.method ?? (body ? 'POST' : 'GET'), headers, body })
  } catch {
    throw new ApiError('The Proofline API could not be reached. Start the FastAPI service on port 8000.')
  }
  const data = await response.json().catch(() => null) as (ApiErrorBody & T & { detail?: unknown }) | null
  if (!response.ok) {
    if (response.status === 401 && authSession) {
      session.clear()
      window.dispatchEvent(new Event('proofline:session-expired'))
    }
    const detail = data && 'detail' in data ? data.detail : undefined
    const message = typeof detail === 'string' ? detail : Array.isArray(detail)
      ? detail.map(item => { const error = item as { loc?: unknown[]; msg?: string }; const field = error.loc?.filter(part => part !== 'body').join('.'); return field ? `${field}: ${error.msg ?? 'invalid'}` : error.msg ?? 'Invalid request' }).join('; ')
      : `Request failed (${response.status}).`
    throw new ApiError(message, response.status)
  }
  if (response.status === 204) return undefined as T
  return data as T
}
async function requestBlob(path: string): Promise<Blob> {
  const { data: { session: authSession } } = await supabase?.auth.getSession() ?? { data: { session: null } }
  const headers = new Headers()
  if (authSession?.access_token) headers.set('Authorization', `Bearer ${authSession.access_token}`)
  const response = await fetch(`${apiBase}/api${path}`, { headers })
  if (!response.ok) {
    if (response.status === 401 && authSession) {
      session.clear()
      window.dispatchEvent(new Event('proofline:session-expired'))
    }
    throw new ApiError(`Download request failed (${response.status}).`, response.status)
  }
  return response.blob()
}
const get = <T,>(path: string) => request<T>(path)
const post = <T,>(path: string, body?: unknown) => request<T>(path, { method: 'POST', body: body ?? {} })
const put = <T,>(path: string, body: unknown) => request<T>(path, { method: 'PUT', body })
const patch = <T,>(path: string, body: unknown) => request<T>(path, { method: 'PATCH', body })

interface RawWorkspace { id: string; name: string; role: Workspace['role']; created_at: string }
interface RawFactVersion { id: string; version_no: number; name: string; approved_value: string; value_type: string; subject_terms: string[]; status: string; created_at: string; created_by: string | null; is_current?: boolean }
interface RawFact { id: string; key: string; brand_profile_id: string; version_id: string; version_no: number; name: string; approved_value: string; value_type: string; subject_terms: string[]; status: string; change_note?: string | null; versions?: RawFactVersion[] }
interface RawSubmission { id: string; title: string; created_at: string; current_version_id: string; brand_profile_id: string; versions: Array<{ id: string; version_no: number; created_at: string }>; review_runs: Array<{ id: string; submission_version_id: string; status: string; started_at: string; automated_outcome?: string | null; automated_risk_score?: number | null }>; decisions: Array<{ id: string; submission_version_id: string; review_run_id: string; decision: string; comment: string | null; decided_at: string; decided_by: string | null }> }
interface RawFinding { id: string; category: string; title: string; explanation: string; severity: Finding['severity']; excerpt: string | null; span_start: number | null; span_end: number | null; verification_status: string; status: string }
interface RawRun { id: string; submission_version_id: string; status: string; engine_version: string; started_at: string; findings: RawFinding[]; automated_decision?: AutomatedDecision | null; visual_analysis?: VisualAnalysis | null }

const roleFrom = (role: string): Workspace['role'] => role === 'owner' || role === 'reviewer' ? role : 'editor'
const toVersion = (v: RawFactVersion, factId: string): SourceVersion => ({ id: v.id, source: factId, no: v.version_no, body: v.approved_value, value: Number(v.approved_value.replace(/[^0-9.-]/g, '')) || 0, value_type: v.value_type, created_by: v.created_by ?? '—', created: v.created_at, approved_by: v.status === 'approved' ? v.created_by ?? 'approved' : null, approved_at: v.status === 'approved' ? v.created_at : null })
const toBrandSource = (fact: RawFact): BrandSource => ({ id: fact.id, ws: '', key: fact.key, title: fact.name, unit_re: (fact.subject_terms ?? []).join(', '), value_type: fact.value_type, archived: fact.status === 'inactive', versions: (fact.versions?.length ? fact.versions : [{ id: fact.version_id, version_no: fact.version_no, name: fact.name, approved_value: fact.approved_value, value_type: fact.value_type, subject_terms: fact.subject_terms, status: fact.status, created_at: new Date().toISOString(), created_by: null }]).map(v => toVersion(v, fact.id)) })

async function ensureBrandProfile(workspaceId: string): Promise<string> {
  const profiles = await get<Array<{ id: string; name: string }>>(`/workspaces/${workspaceId}/profiles`)
  if (profiles[0]) return profiles[0].id
  const created = await post<{ id: string }>(`/workspaces/${workspaceId}/profiles`, { name: 'Brand profile', description: 'Default Proofline brand profile' })
  return created.id
}
const toFinding = (f: RawFinding): Finding => ({ id: f.id, category: f.category, severity: f.severity, certainty: f.verification_status, quoted: f.excerpt ?? '', start: f.span_start ?? 0, end: f.span_end ?? 0, explanation: f.explanation || f.title, action: 'Review this finding against its recorded evidence and context.', evidence: [], status: f.status })

export const authApi = {
  async login(email: string, password: string): Promise<Session> {
    const { data, error } = await requireSupabase().auth.signInWithPassword({ email: email.trim(), password })
    if (error) throw new ApiError(error.message)
    if (!data.session) throw new ApiError('Sign-in succeeded but no Proofline session was returned.')
    return { token: data.session.access_token }
  },
  async register(email: string, name: string, password: string, emailRedirectTo: string) {
    const { data, error } = await requireSupabase().auth.signUp({ email: email.trim(), password, options: { data: { name: name.trim() }, emailRedirectTo } })
    if (error) throw new ApiError(error.message)
    return { id: data.user?.id ?? '', email: data.user?.email ?? email.trim(), verification_required: !data.session as true }
  },
  async resendVerification(email: string, emailRedirectTo: string) {
    const { error } = await requireSupabase().auth.resend({ type: 'signup', email: email.trim(), options: { emailRedirectTo } })
    if (error) throw new ApiError(error.message)
    return { accepted: true as const }
  },
  async me(): Promise<Profile> {
    const client = requireSupabase()
    const { data: { user }, error } = await client.auth.getUser()
    if (error || !user?.email) throw new ApiError(error?.message ?? 'Your Supabase session is no longer valid.')
    const [apiUser, workspaces] = await Promise.all([get<{ id: string; email: string }>('/me'), get<RawWorkspace[]>('/workspaces')])
    return { user: { id: apiUser.id, email: apiUser.email, name: String(user.user_metadata?.name ?? user.user_metadata?.full_name ?? apiUser.email.split('@')[0]), created: user.created_at }, workspaces: workspaces.map(w => ({ id: w.id, name: w.name, role: roleFrom(w.role) })) }
  },
}

export const workspaceApi = {
  summary(workspaceId: string) {
    return get<DashboardSummary>(`/workspaces/${workspaceId}/dashboard`)
  },
  async create(name: string) {
    const created = await post<RawWorkspace>('/workspaces', { name })
    await post(`/workspaces/${created.id}/profiles`, { name: 'Brand profile', description: 'Default Proofline brand profile' })
    return created
  },
}
export const brandApi = {
  async list(workspaceId: string) {
    const facts = await get<RawFact[]>(`/workspaces/${workspaceId}/facts`)
    return Promise.all(facts.map(async fact => toBrandSource({ ...fact, versions: (await get<RawFact>(`/workspaces/${workspaceId}/facts/${fact.id}`)).versions })))
  },
  async create(workspaceId: string, body: { key: string; title: string; value_type: string; subject_terms: string[]; body: string }) {
    const profileId = await ensureBrandProfile(workspaceId)
    const fact = await post<RawFact>(`/workspaces/${workspaceId}/facts`, { brand_profile_id: profileId, key: body.key, name: body.title, approved_value: body.body, value_type: body.value_type, subject_terms: body.subject_terms, status: 'approved' })
    return toBrandSource(fact)
  },
  async addVersion(workspaceId: string, factId: string, body: string) {
    const fact = await put<RawFact>(`/workspaces/${workspaceId}/facts/${factId}`, { approved_value: body, change_note: 'Updated approved wording' })
    return toBrandSource(fact).versions[0]
  },
  async approve(workspaceId: string, factId: string) {
    const fact = await put<RawFact>(`/workspaces/${workspaceId}/facts/${factId}`, { status: 'approved', change_note: 'Approved for use in reviews' })
    return { approved: fact.version_id }
  },
}

function submissionForm(profileId: string, title: string, sourceType: string, text?: string, file?: File, url?: string) {
  const form = new FormData(); form.append('brand_profile_id', profileId); form.append('title', title); form.append('source_type', sourceType)
  if (text) form.append('text', text)
  if (file) form.append('file', file)
  if (url) form.append('url', url)
  return form
}
export const rulesApi = {
  async list(workspaceId: string) {
    const profileId = await ensureBrandProfile(workspaceId)
    const rules = await get<Array<{ id: string; key: string; brand_profile_id: string; version_id: string; version_no: number; rule_type: string; description: string; patterns: string[]; severity: 'high' | 'medium' | 'low'; applies_to: string[]; status: string }>>(`/workspaces/${workspaceId}/rules?brand_profile_id=${profileId}`)
    return Promise.all(rules.map(async rule => {
      const detail = await get<{ versions?: Array<{ id: string; version_no: number; rule_type: string; description: string; patterns: string[]; severity: 'high' | 'medium' | 'low'; status: string; created_at: string; created_by?: string | null }> }>(`/workspaces/${workspaceId}/rules/${rule.id}`)
      const versions = detail.versions ?? []
      return { id: rule.id, ws: workspaceId, key: rule.key, title: rule.description, description: rule.description, rule_type: rule.rule_type, patterns: rule.patterns, severity: rule.severity, applies_to: rule.applies_to, versions: versions.map(version => ({ id: version.id, rule: rule.id, no: version.version_no, body: `${version.description} · ${version.patterns.join(', ')}`, severity: version.severity, approved_by: version.status === 'approved' ? version.created_by ?? 'approved' : null, created: version.created_at })) }
    }))
  },
  async create(workspaceId: string, input: { key: string; rule_type: string; description: string; patterns: string[]; severity: 'high' | 'medium' | 'low'; applies_to: string[] }) {
    const brand_profile_id = await ensureBrandProfile(workspaceId)
    return post(`/workspaces/${workspaceId}/rules`, { ...input, brand_profile_id, status: 'approved' })
  },
  async update(workspaceId: string, ruleId: string, input: { rule_type: string; description: string; patterns: string[]; severity: 'high' | 'medium' | 'low'; applies_to: string[]; change_note?: string }) {
    return put(`/workspaces/${workspaceId}/rules/${ruleId}`, { ...input, status: 'approved' })
  },
}
export const submissionApi = {
  async list(workspaceId: string) {
    const rows = await get<Array<RawSubmission & { version_id: string; version_no: number; last_run_status: string | null; last_decision: string | null; last_automated_outcome: string | null; open_impacts: number; open_findings: number }>>(`/workspaces/${workspaceId}/submissions`)
    return rows.map(row => ({ id: row.id, ws: workspaceId, title: row.title, status: row.last_decision === 'approved' || row.last_decision === 'rejected' || row.last_decision === 'changes_requested' ? row.last_decision : row.last_automated_outcome === 'approved' ? 'approved' as const : row.last_automated_outcome === 'rejected' ? 'rejected' as const : row.last_automated_outcome === 'on_hold' ? 'on_hold' as const : row.last_run_status && row.last_run_status !== 'failed' ? 'in_review' as const : 'awaiting_evidence' as const, owner: '—', revision: { id: row.version_id, sub: row.id, no: row.version_no, text: '', hash: '', created: row.created_at } }))
  },
  async create(workspaceId: string, title: string, text: string, options: { sourceType?: string; file?: File; url?: string } = {}) {
    const profileId = await ensureBrandProfile(workspaceId)
    const sourceType = options.sourceType ?? 'text'
    const response = await request<{ id: string; version: { id: string; version_no: number } }>(`/workspaces/${workspaceId}/submissions`, { method: 'POST', form: submissionForm(profileId, title, sourceType, text, options.file, options.url) })
    return { id: response.id, ws: workspaceId, title, status: 'draft' as const, owner: '—', revision: { id: response.version.id, sub: response.id, no: response.version.version_no, text, hash: '', created: new Date().toISOString() } }
  },
  async detail(workspaceId: string, submissionId: string): Promise<SubmissionDetail> {
    const raw = await get<RawSubmission>(`/workspaces/${workspaceId}/submissions/${submissionId}`)
    const currentVersion = await get<{ id: string; submission_id: string; version_no: number; extracted_text: string; content_hash: string; created_at: string }>(`/workspaces/${workspaceId}/submission-versions/${raw.current_version_id}`)
    const run = raw.review_runs.filter(item => item.submission_version_id === raw.current_version_id).sort((a, b) => b.started_at.localeCompare(a.started_at))[0]
    const latestRun = run ? await get<RawRun & { findings: RawFinding[] }>(`/workspaces/${workspaceId}/review-runs/${run.id}`) : null
    const [evidence, product_link] = await Promise.all([
      get<SubmissionEvidence[]>(`/workspaces/${workspaceId}/submission-versions/${raw.current_version_id}/evidence`),
      get<SubmissionDetail['product_link']>(`/workspaces/${workspaceId}/submission-versions/${raw.current_version_id}/product`),
    ])
    const findings = latestRun ? await Promise.all(latestRun.findings.map(async finding => {
      const detail = await get<{ evidence: Array<{ excerpt: string | null; source_url: string | null; access_status: string | null }> }>(`/workspaces/${workspaceId}/findings/${finding.id}`)
      return { ...toFinding(finding), evidence: detail.evidence.map(e => ({ snippet: e.excerpt ?? undefined, source_url: e.source_url ?? undefined, status: e.access_status ?? undefined })) }
    })) : null
    const decisions = raw.decisions.map(d => ({ id: d.id, sub: submissionId, rev: d.submission_version_id, reviewer: d.decided_by ?? 'Unknown reviewer', decision: d.decision, rationale: d.comment ?? '', created: d.decided_at }))
    const decision = decisions.find(d => d.rev === raw.current_version_id)
    const automatedOutcome = latestRun?.automated_decision?.outcome
    const status = decision?.decision === 'approved' || decision?.decision === 'rejected' || decision?.decision === 'changes_requested' ? decision.decision : automatedOutcome === 'approved' ? 'approved' : automatedOutcome === 'rejected' ? 'rejected' : automatedOutcome === 'on_hold' ? 'on_hold' : latestRun && latestRun.status !== 'failed' ? 'in_review' : evidence.length ? 'ready_for_review' : 'awaiting_evidence'
    return { id: raw.id, ws: workspaceId, title: raw.title, status, owner: '—', revision: { id: currentVersion.id, sub: submissionId, no: currentVersion.version_no, text: currentVersion.extracted_text, hash: currentVersion.content_hash, created: currentVersion.created_at }, findings, decisions, evidence, automated_decision: latestRun?.automated_decision ?? null, visual_analysis: latestRun?.visual_analysis ?? null, assessments: (latestRun as (RawRun & { evidence_assessments?: SubmissionDetail['assessments'] }) | null)?.evidence_assessments ?? [], product_link }
  },
  async revise(workspaceId: string, submissionId: string, text: string) {
    const profileId = await ensureBrandProfile(workspaceId)
    return request(`/workspaces/${workspaceId}/submissions/${submissionId}/versions`, { method: 'POST', form: submissionForm(profileId, 'Revision', 'text', text) })
  },
  async addEvidence(workspaceId: string, versionId: string, file: File, description?: string) {
    const form = new FormData()
    form.append('file', file)
    if (description?.trim()) form.append('description', description.trim())
    return request<SubmissionEvidence>(`/workspaces/${workspaceId}/submission-versions/${versionId}/evidence`, { method: 'POST', form })
  },
  linkProduct(workspaceId: string, versionId: string, productId: string) {
    return post(`/workspaces/${workspaceId}/submission-versions/${versionId}/product?product_id=${encodeURIComponent(productId)}`)
  },
  report(workspaceId: string, submissionId: string) {
    return requestBlob(`/workspaces/${workspaceId}/submissions/${submissionId}/report.pdf`)
  },
}
export const productIntelligenceApi = {
  status(workspaceId: string) { return get<{ search_provider: string; configured: boolean; message: string }>(`/workspaces/${workspaceId}/product-intelligence/status`) },
  list(workspaceId: string) { return get<ProductRecord[]>(`/workspaces/${workspaceId}/product-intelligence/products`) },
  async create(workspaceId: string, input: Omit<ProductRecord, 'id' | 'brand_profile_id' | 'identity_status' | 'identity_confirmed'> & { confirm_identity: boolean }) {
    const brand_profile_id = await ensureBrandProfile(workspaceId)
    return post<ProductRecord>(`/workspaces/${workspaceId}/product-intelligence/products`, { ...input, brand_profile_id })
  },
  detail(workspaceId: string, id: string) {
    return get<{ product: ProductRecord; runs: Array<Record<string, unknown>>; latest_run: Record<string, unknown> | null; queries: Array<Record<string, unknown>>; sources: ProductSource[]; profile: { version_no: number; profile: { facts?: ProductFact[]; warnings?: string[]; limitations_note?: string }; coverage: ProductCoverage; created_at: string } | null; claims: ProductClaim[]; claim_coverage: ProductClaimCoverage }>(`/workspaces/${workspaceId}/product-intelligence/products/${id}`)
  },
  research(workspaceId: string, id: string) { return post(`/workspaces/${workspaceId}/product-intelligence/products/${id}/research`) },
}
export const visualApi = {
  async library(workspaceId: string) {
    const profileId = await ensureBrandProfile(workspaceId)
    const [assets, palettes] = await Promise.all([
      get<VisualAsset[]>(`/workspaces/${workspaceId}/visual/assets`),
      get<PaletteVersion[]>(`/workspaces/${workspaceId}/visual/palette?brand_profile_id=${encodeURIComponent(profileId)}`),
    ])
    return { profileId, assets, palettes }
  },
  async upload(workspaceId: string, profileId: string, name: string, assetType: string, category: string, file: File) {
    const form = new FormData()
    form.append('brand_profile_id', profileId); form.append('name', name); form.append('asset_type', assetType)
    form.append('category', category); form.append('file', file)
    return request<VisualAsset>(`/workspaces/${workspaceId}/visual/assets`, { method: 'POST', form })
  },
  content(workspaceId: string, assetId: string) { return requestBlob(`/workspaces/${workspaceId}/visual/assets/${assetId}/content`) },
  savePalette(workspaceId: string, profileId: string, colors: string[]) {
    return post<PaletteVersion>(`/workspaces/${workspaceId}/visual/palette`, { brand_profile_id: profileId, colors })
  },
}
export const monitoringApi = {
  sources(workspaceId: string) { return get<MonitoredSource[]>(`/workspaces/${workspaceId}/monitoring/sources`) },
  changes(workspaceId: string) { return get<MonitoringChange[]>(`/workspaces/${workspaceId}/monitoring/changes`) },
  async create(workspaceId: string, input: { url: string; label: string; interval_minutes: number; product_id?: string }) {
    const brand_profile_id = await ensureBrandProfile(workspaceId)
    return post<MonitoredSource>(`/workspaces/${workspaceId}/monitoring/sources`, { ...input, brand_profile_id })
  },
  update(workspaceId: string, sourceId: string, input: { url?: string; label?: string; interval_minutes?: number; status?: string }) {
    return patch<MonitoredSource>(`/workspaces/${workspaceId}/monitoring/sources/${sourceId}`, input)
  },
  check(workspaceId: string, sourceId: string) { return post(`/workspaces/${workspaceId}/monitoring/sources/${sourceId}/check`) },
  updateChange(workspaceId: string, changeId: string, status: 'reviewed' | 'dismissed', reason: string) {
    return patch(`/workspaces/${workspaceId}/monitoring/changes/${changeId}`, { status, reason })
  },
}
export const riskApi = { list(workspaceId: string) { return get<RiskQueueItem[]>(`/workspaces/${workspaceId}/risk-queue`) } }
export const reviewApi = {
  async run(workspaceId: string, submissionId: string): Promise<ReviewResult> {
    const detail = await submissionApi.detail(workspaceId, submissionId)
    const run = await post<RawRun & { findings: RawFinding[] }>(`/workspaces/${workspaceId}/submission-versions/${detail.revision.id}/review`)
    const findings: ReviewFinding[] = run.findings.map(finding => ({ category: finding.category, severity: finding.severity, certainty: finding.verification_status, quoted: finding.excerpt ?? '', start: finding.span_start ?? 0, end: finding.span_end ?? 0, explanation: finding.explanation || finding.title, action: 'Review the evidence and context before deciding.', evidence: [], status: finding.status }))
    return { review_run_id: run.id, revision_id: run.submission_version_id, engine: run.engine_version, findings, dependencies: [], summary: `Automated decision: ${run.automated_decision?.outcome.replaceAll('_', ' ') ?? 'not available'} · risk ${run.automated_decision?.risk_score ?? '—'}/100. ${run.automated_decision?.rationale ?? ''}` }
  },
}
export const reviewDecisionApi = {
  async decide(workspaceId: string, submissionId: string, revisionId: string, decision: Decision['decision'], rationale: string) {
    const detail = await get<RawSubmission>(`/workspaces/${workspaceId}/submissions/${submissionId}`)
    const run = detail.review_runs.filter(item => item.submission_version_id === revisionId).sort((a, b) => b.started_at.localeCompare(a.started_at))[0]
    if (!run || run.status === 'failed') throw new ApiError('Run a successful review on this exact version before recording a decision.')
    await post(`/workspaces/${workspaceId}/submission-versions/${revisionId}/decisions`, { decision, review_run_id: run.id, comment: rationale || null })
    return submissionApi.detail(workspaceId, submissionId)
  },
}
export const findingApi = { resolve(workspaceId: string, findingId: string, rationale: string) { return patch(`/workspaces/${workspaceId}/findings/${findingId}/status`, { status: 'resolved', reason: rationale }) } }
export const impactApi = {
  async list(workspaceId: string): Promise<Impact[]> {
    const rows = await get<Array<Record<string, unknown>>>(`/workspaces/${workspaceId}/impacts`)
    return rows.map(row => ({ id: String(row.id), ws: workspaceId, sub: String(row.submission_id), rev: String(row.submission_version_id), source: String(row.entity_key ?? row.change_kind), old_version: `${row.change_kind} v${row.old_version_no ?? '—'}`, new_version: `${row.change_kind} v${row.new_version_no ?? '—'}`, state: row.status === 'review_required' ? 'needs_review' : 'not_affected', rationale: row.status === 'resolved' ? `Resolved ${row.resolved_at ?? ''}` : null }))
  },
}
export const auditApi = {
  async list(workspaceId: string): Promise<AuditEvent[]> {
    const rows = await get<Array<Record<string, unknown>>>(`/workspaces/${workspaceId}/audit?limit=50`)
    return rows.map(row => ({ id: String(row.id), ws: workspaceId, actor: String(row.actor ?? 'System'), action: String(row.event_type), target: String(row.entity_id ?? row.entity_type), detail: (row.payload ?? {}) as Record<string, unknown>, created: String(row.created_at) }))
  },
}
export const teamApi = {
  async list(workspaceId: string): Promise<Member[]> {
    const rows = await get<Array<{ user_id: string; email: string; role: string }>>(`/workspaces/${workspaceId}/members`)
    return rows.map(row => ({ user_id: row.user_id, email: row.email, name: row.email.split('@')[0], role: roleFrom(row.role) }))
  },
  add(workspaceId: string, email: string, role: string) { return post(`/workspaces/${workspaceId}/members`, { email, role }) },
}
