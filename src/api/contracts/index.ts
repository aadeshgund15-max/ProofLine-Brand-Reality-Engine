export type Role = 'owner' | 'editor' | 'reviewer'
export interface User { id: string; email: string; name: string; created: string }
export interface Workspace { id: string; name?: string; role: Role }
export interface Session { token: string }
export interface Profile { user: User; workspaces: Workspace[] }
export interface SourceVersion { id: string; source: string; no: number; body: string; value: number; value_type: string; created_by: string; created: string; approved_by: string | null; approved_at: string | null }
export interface BrandSource { id: string; ws: string; key: string; title: string; unit_re: string; value_type: string; archived: boolean; versions: SourceVersion[] }
export interface RuleVersion { id: string; rule: string; no: number; body: string; severity: 'high' | 'medium' | 'low'; approved_by: string | null; created: string }
export interface BrandRule { id: string; ws: string; key: string; title: string; description: string; rule_type: string; patterns: string[]; severity: 'high' | 'medium' | 'low'; applies_to: string[]; versions: RuleVersion[] }
export interface Submission { id: string; ws: string; title: string; status: 'draft' | 'awaiting_evidence' | 'processing_evidence' | 'ready_for_review' | 'in_review' | 'approved' | 'rejected' | 'changes_requested'; owner: string; revision?: Revision }
export interface Revision { id: string; sub: string; no: number; text: string; hash: string; created: string }
export interface Evidence { snippet?: string; source?: string; source_url?: string; status?: string }
export interface SubmissionEvidence { id: string; original_filename: string; mime_type: string; size_bytes: number; description: string | null; extraction_status: string; extraction_warnings: string[]; extracted_text: string; segments: Array<{ start: number; end: number; label: string; kind: string }>; created_at: string }
export interface Finding { id: string; category: string; severity: 'high' | 'medium' | 'low' | 'info'; certainty: string; quoted: string; start: number; end: number; explanation: string; action: string; evidence: Evidence[]; status: string }
export type ReviewFinding = Omit<Finding, 'id'>
export interface ReviewResult { review_run_id: string; revision_id: string; engine: string; findings: ReviewFinding[]; dependencies: Array<{ source: string; version: string; method: string }>; summary: string }
export interface ReviewRun { id: string; rev: string; engine: string; context: Record<string, unknown>; created: string }
export interface FindingDetail { finding: Finding; evidence: Evidence[]; location?: { start: number; end: number; page?: number; slide?: number }; source_records?: Array<{ id: string; url?: string; retrieved_at?: string; published_at?: string }> }
export interface EvidenceAssessment { id: string; evidence_id: string; original_filename: string; assessment: string; explanation: string; excerpt: string | null; location?: Record<string, unknown> | null }
export interface SubmissionDetail extends Submission { revision: Revision; findings: Finding[] | null; decisions: Decision[]; evidence: SubmissionEvidence[]; assessments: EvidenceAssessment[] }
export interface Decision { id: string; sub: string; rev: string; reviewer: string; decision: string; rationale: string; created: string }
export interface Impact { id: string; ws: string; sub: string; rev: string; source: string; old_version: string; new_version: string; state: string; rationale: string | null }
export interface AuditEvent { id: string; ws: string; actor: string; action: string; target: string; detail: Record<string, unknown>; created: string }
export interface DashboardSummary { facts: number; approved_facts: number; rules: number; submissions: number; review_runs: number; open_findings: number; open_findings_high: number; impact_review_required: number; recent_activity: Array<{ id: string; event_type: string; summary: string; created_at: string }> }
export interface Member { user_id: string; role: Role; email: string; name: string }
export interface ApiErrorBody { error?: { code?: string; request_id?: string } }

// Proposed-only service contract until the backend adds versioned rule routes.
export interface RulesServiceContract {
  list(workspaceId: string): Promise<BrandRule[]>
  create(workspaceId: string, input: { key: string; title: string; description: string; rule_type: string; severity: RuleVersion['severity']; body: string }): Promise<BrandRule>
  addVersion(workspaceId: string, ruleId: string, input: { body: string; severity: RuleVersion['severity'] }): Promise<RuleVersion>
  approve(workspaceId: string, ruleId: string, versionId: string): Promise<{ approved: string }>
}

// Proposed-only route notes for missing backend contracts are documented in API_CONTRACTS.md.
