// Typed API client. All data comes from the backend; nothing is mocked here.

export type Role = "owner" | "editor" | "reviewer";
export type Severity = "low" | "medium" | "high";
export type FactStatus = "draft" | "approved" | "inactive";
export type ValueType = "text" | "number" | "money" | "date";
export type RuleType = "prohibited_phrase" | "required_term" | "approved_name" | "claim_requires_evidence";
export type ContentType = "text" | "docx" | "pdf" | "image" | "pptx" | "url";
export type ExtractionStatus = "complete" | "partial" | "empty" | "unsupported" | "failed";
export type FindingStatus = "open" | "accepted" | "resolved" | "dismissed" | "needs_investigation";
export type VerificationStatus =
  | "not_applicable" | "supported" | "contradicted" | "conflicting"
  | "insufficient_evidence" | "unavailable" | "needs_human_review";
export type FindingCategory =
  | "rule_violation" | "possible_inconsistency" | "verified_contradiction" | "claim_verification" | "extraction_limitation";
export type Decision = "approved" | "changes_requested" | "rejected";

export interface Workspace { id: string; name: string; role: Role; created_at: string }
export interface Member { user_id: string; email: string; role: Role }
export interface Profile { id: string; name: string; description: string | null; created_at: string }
export interface Source { id: string; kind: string; title: string; url: string | null; publisher: string | null; created_at: string }

export interface FactVersion {
  id: string; version_no: number; name: string; approved_value: string; value_type: ValueType; subject_terms: string[];
  status: FactStatus; change_note: string | null; created_at: string; created_by: string | null; is_current: boolean;
  effective_date: string | null; source_record_id: string | null;
}
export interface Fact {
  id: string; key: string; brand_profile_id: string; version_id: string; version_no: number; name: string;
  approved_value: string; value_type: ValueType; subject_terms: string[]; status: FactStatus;
  effective_date: string | null; source_record_id: string | null; change_note: string | null;
  versions?: FactVersion[]; flagged_submissions?: number;
}
export interface RuleVersion {
  id: string; version_no: number; rule_type: RuleType; description: string; patterns: string[]; severity: Severity;
  applies_to: ContentType[]; status: FactStatus; change_note: string | null; created_at: string; created_by: string | null; is_current: boolean;
}
export interface Rule {
  id: string; key: string; brand_profile_id: string; version_id: string; version_no: number; rule_type: RuleType;
  description: string; patterns: string[]; severity: Severity; applies_to: ContentType[]; status: FactStatus;
  versions?: RuleVersion[]; flagged_submissions?: number;
}

export interface SubmissionRow {
  id: string; title: string; created_at: string; version_id: string; version_no: number; source_type: ContentType;
  extraction_status: ExtractionStatus; last_run_status: RunStatus | null; last_run_id: string | null;
  last_decision: Decision | null; open_impacts: number; open_findings: number;
}
export type RunStatus = "running" | "completed" | "completed_with_warnings" | "failed";
export interface StageInfo { status: string; message: string }
export interface SubmissionDetail {
  id: string; title: string; current_version_id: string; created_at: string;
  versions: { id: string; version_no: number; source_type: ContentType; original_filename: string | null; original_url: string | null;
    extraction_status: ExtractionStatus; extraction_warnings: string[]; content_hash: string; created_at: string; created_by: string | null }[];
  review_runs: { id: string; submission_version_id: string; status: RunStatus; stages: Record<string, StageInfo>; started_at: string; finding_count: number }[];
  decisions: { id: string; submission_version_id: string; review_run_id: string; decision: Decision; comment: string | null; decided_at: string; decided_by: string | null }[];
  impacts: { id: string; submission_version_id: string; change_kind: string; status: string; created_at: string; resolved_at: string | null }[];
}
export interface VersionDetail {
  id: string; submission_id: string; title: string; version_no: number; source_type: ContentType; original_filename: string | null;
  original_url: string | null; retrieved_at: string | null; extracted_text: string; content_hash: string;
  extraction_status: ExtractionStatus; extraction_warnings: string[]; extraction_quality: Record<string, unknown>;
  segments: { start: number; end: number; label: string; kind: string }[]; created_at: string; has_original: boolean; size_bytes: number | null;
}
export interface NewVersionResult {
  id: string;
  version: { id: string; version_no: number; extraction_status: ExtractionStatus; warnings: string[]; preview: string; source_type: ContentType };
}

export interface FindingRow {
  id: string; origin: string; category: FindingCategory; title: string; explanation: string; severity: Severity;
  excerpt: string | null; span_start: number | null; span_end: number | null; location: { label: string; kind: string } | null;
  verification_status: VerificationStatus; status: FindingStatus; status_reason: string | null; evidence_count: number;
}
export interface RunDetail {
  id: string; submission_version_id: string; submission_id: string; title: string; version_no: number; status: RunStatus;
  stages: Record<string, StageInfo>; engine_version: string; started_at: string; completed_at: string | null; error: string | null;
  extraction_status: ExtractionStatus; findings: FindingRow[];
  fact_versions_used: { id: string; key: string; name: string; version_no: number; approved_value: string }[];
  rule_versions_used: { id: string; key: string; version_no: number; rule_type: RuleType }[];
}
export interface Evidence {
  id: string; kind: "brand_fact" | "brand_rule" | "external_source"; stance: "supports" | "contradicts" | "unclassified" | "reference";
  excerpt: string | null; fact_version_no: number | null; fact_name: string | null; approved_value: string | null;
  rule_version_no: number | null; rule_type: RuleType | null; rule_description: string | null;
  source_title: string | null; source_url: string | null; publisher: string | null; retrieved_at: string | null;
  published_at: string | null; access_status: string | null;
}
export interface FindingDetail extends Omit<FindingRow, "evidence_count"> {
  submission_id: string; submission_title: string; version_no: number; submission_version_id: string; review_run_id: string;
  context?: { before: string; match: string; after: string }; evidence: Evidence[];
}
export interface Impact {
  id: string; status: "review_required" | "resolved"; change_kind: "fact" | "rule"; created_at: string; resolved_at: string | null;
  submission_id: string; submission_version_id: string; title: string; flagged_version_no: number; current_version_no: number;
  current_version_id: string; entity_key: string; old_value: string | null; new_value: string | null; old_version_no: number | null;
  new_version_no: number | null; fact_name: string | null; old_rule: string | null; new_rule: string | null;
  old_patterns: string[] | null; new_patterns: string[] | null; resolved_by: string | null;
}
export interface AuditEvent { id: number; event_type: string; entity_type: string; entity_id: string | null; summary: string; created_at: string; actor: string | null }
export interface Dashboard {
  facts: number; rules: number; submissions: number; review_runs: number; open_findings: number; open_findings_high: number;
  impact_review_required: number; recent_activity: { id: number; event_type: string; summary: string; created_at: string }[];
}
export interface ProviderStatus {
  llm: { provider: string; configured: boolean; working: boolean | null; message: string | null };
  search: { provider: string; configured: boolean; working: boolean | null; message: string | null };
  auth_mode: string; storage: string; ocr: { available: boolean; version: string | null };
}
export interface PublicConfig { auth_mode: "supabase" | "local"; max_upload_mb: number; supported_types: ContentType[] }

// ------------------------------------------------------------------ transport
const BASE = import.meta.env.VITE_API_BASE ?? "";
let tokenProvider: () => Promise<string | null> = async () => null;
export function setTokenProvider(fn: () => Promise<string | null>): void { tokenProvider = fn; }

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) { super(message); this.status = status; }
}

function describe(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((d) => {
      const o = d as { msg?: string; loc?: unknown[] };
      const field = Array.isArray(o.loc) ? o.loc.filter((x) => x !== "body").join(".") : "";
      return field ? `${field}: ${o.msg ?? "invalid"}` : (o.msg ?? "invalid");
    }).join("; ");
  }
  return "Request failed";
}

async function request<T>(method: string, path: string, body?: unknown, form?: FormData): Promise<T> {
  const headers: Record<string, string> = {};
  const token = await tokenProvider();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  let payload: BodyInit | undefined;
  if (form) payload = form;
  else if (body !== undefined) { headers["Content-Type"] = "application/json"; payload = JSON.stringify(body); }
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, { method, headers, body: payload });
  } catch {
    throw new ApiError(0, "Cannot reach the Proofline API. Check that the backend is running.");
  }
  if (!res.ok) {
    let detail: unknown = res.statusText;
    try { detail = ((await res.json()) as { detail?: unknown }).detail ?? detail; } catch { /* non-JSON error body */ }
    throw new ApiError(res.status, describe(detail));
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

const get = <T,>(p: string) => request<T>("GET", p);
const post = <T,>(p: string, b?: unknown) => request<T>("POST", p, b ?? {});
const put = <T,>(p: string, b: unknown) => request<T>("PUT", p, b);
const patch = <T,>(p: string, b: unknown) => request<T>("PATCH", p, b);
const ws = (id: string) => `/api/workspaces/${id}`;

export interface FactInput {
  brand_profile_id: string; key: string; name: string; approved_value: string; value_type: ValueType;
  subject_terms: string[]; status: FactStatus; source_record_id?: string | null; effective_date?: string | null; change_note?: string | null;
}
export interface RuleInput {
  brand_profile_id: string; key: string; rule_type: RuleType; description: string; patterns: string[]; severity: Severity;
  applies_to: ContentType[]; status: FactStatus; change_note?: string | null;
}

export const api = {
  config: () => get<PublicConfig>("/api/config"),
  signup: (email: string, password: string) => post<{ access_token: string }>("/api/auth/signup", { email, password }),
  login: (email: string, password: string) => post<{ access_token: string }>("/api/auth/login", { email, password }),
  me: () => get<{ id: string; email: string }>("/api/me"),
  workspaces: () => get<Workspace[]>("/api/workspaces"),
  createWorkspace: (name: string) => post<Workspace>("/api/workspaces", { name }),
  members: (w: string) => get<Member[]>(`${ws(w)}/members`),
  addMember: (w: string, email: string, role: Role) => post<Member>(`${ws(w)}/members`, { email, role }),
  profiles: (w: string) => get<Profile[]>(`${ws(w)}/profiles`),
  createProfile: (w: string, name: string, description: string) => post<Profile>(`${ws(w)}/profiles`, { name, description: description || null }),
  dashboard: (w: string) => get<Dashboard>(`${ws(w)}/dashboard`),
  providers: (w: string, probe: boolean) => get<ProviderStatus>(`${ws(w)}/settings/providers?probe=${probe}`),

  sources: (w: string) => get<Source[]>(`${ws(w)}/sources?kind=reference`),
  createSource: (w: string, title: string, url: string, publisher: string) =>
    post<Source>(`${ws(w)}/sources`, { title, url: url || null, publisher: publisher || null }),
  facts: (w: string) => get<Fact[]>(`${ws(w)}/facts`),
  fact: (w: string, id: string) => get<Fact>(`${ws(w)}/facts/${id}`),
  createFact: (w: string, b: FactInput) => post<Fact>(`${ws(w)}/facts`, b),
  updateFact: (w: string, id: string, b: Partial<Omit<FactInput, "brand_profile_id" | "key">>) => put<Fact>(`${ws(w)}/facts/${id}`, b),
  rules: (w: string) => get<Rule[]>(`${ws(w)}/rules`),
  rule: (w: string, id: string) => get<Rule>(`${ws(w)}/rules/${id}`),
  createRule: (w: string, b: RuleInput) => post<Rule>(`${ws(w)}/rules`, b),
  updateRule: (w: string, id: string, b: Partial<Omit<RuleInput, "brand_profile_id" | "key">>) => put<Rule>(`${ws(w)}/rules/${id}`, b),

  submissions: (w: string) => get<SubmissionRow[]>(`${ws(w)}/submissions`),
  submission: (w: string, id: string) => get<SubmissionDetail>(`${ws(w)}/submissions/${id}`),
  version: (w: string, id: string) => get<VersionDetail>(`${ws(w)}/submission-versions/${id}`),
  createSubmission: (w: string, f: FormData) => request<NewVersionResult>("POST", `${ws(w)}/submissions`, undefined, f),
  createVersion: (w: string, id: string, f: FormData) => request<NewVersionResult>("POST", `${ws(w)}/submissions/${id}/versions`, undefined, f),
  runReview: (w: string, versionId: string) => post<RunDetail>(`${ws(w)}/submission-versions/${versionId}/review`),
  run: (w: string, id: string) => get<RunDetail>(`${ws(w)}/review-runs/${id}`),
  finding: (w: string, id: string) => get<FindingDetail>(`${ws(w)}/findings/${id}`),
  setFindingStatus: (w: string, id: string, status: FindingStatus, reason: string) =>
    patch<{ id: string; status: FindingStatus }>(`${ws(w)}/findings/${id}/status`, { status, reason: reason || null }),
  decide: (w: string, versionId: string, decision: Decision, runId: string, comment: string) =>
    post<{ impacts_resolved: number; impacts_still_open: number; note: string | null }>(
      `${ws(w)}/submission-versions/${versionId}/decisions`, { decision, review_run_id: runId, comment: comment || null }),
  impacts: (w: string, status?: "review_required" | "resolved") => get<Impact[]>(`${ws(w)}/impacts${status ? `?status=${status}` : ""}`),
  audit: (w: string, beforeId?: number) => get<AuditEvent[]>(`${ws(w)}/audit?limit=50${beforeId ? `&before_id=${beforeId}` : ""}`),
  originalUrl: (w: string, versionId: string) => `${BASE}${ws(w)}/submission-versions/${versionId}/original`,
  downloadOriginal: async (w: string, versionId: string, filename: string) => {
    const token = await tokenProvider();
    const res = await fetch(`${BASE}${ws(w)}/submission-versions/${versionId}/original`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
    if (!res.ok) throw new ApiError(res.status, "Could not download the original file");
    const url = URL.createObjectURL(await res.blob());
    const a = document.createElement("a");
    a.href = url; a.download = filename; a.click();
    URL.revokeObjectURL(url);
  },
};
