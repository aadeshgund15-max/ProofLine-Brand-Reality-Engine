export type Role = 'owner' | 'editor' | 'reviewer'
export interface User { id: string; email: string; name: string; created: string }
export interface Workspace { id: string; name?: string; role: Role }
export interface Session { token: string }
export interface Profile { user: User; workspaces: Workspace[] }
export interface SourceVersion { id: string; source: string; no: number; body: string; value: number; value_type: string; created_by: string; created: string; approved_by: string | null; approved_at: string | null }
export interface BrandSource { id: string; ws: string; key: string; title: string; unit_re: string; value_type: string; archived: boolean; versions: SourceVersion[] }
export interface RuleVersion { id: string; rule: string; no: number; body: string; severity: 'high' | 'medium' | 'low'; approved_by: string | null; created: string }
export interface BrandRule { id: string; ws: string; key: string; title: string; description: string; rule_type: string; patterns: string[]; severity: 'high' | 'medium' | 'low'; applies_to: string[]; versions: RuleVersion[] }
export interface Submission { id: string; ws: string; title: string; status: 'draft' | 'awaiting_evidence' | 'processing_evidence' | 'ready_for_review' | 'in_review' | 'on_hold' | 'approved' | 'rejected' | 'changes_requested'; owner: string; revision?: Revision }
export interface Revision { id: string; sub: string; no: number; text: string; hash: string; created: string }
export interface Evidence { snippet?: string; source?: string; source_url?: string; status?: string }
export interface SubmissionEvidence { id: string; original_filename: string; mime_type: string; size_bytes: number; description: string | null; extraction_status: string; extraction_warnings: string[]; extracted_text: string; segments: Array<{ start: number; end: number; label: string; kind: string }>; created_at: string }
export interface Finding { id: string; category: string; severity: 'high' | 'medium' | 'low' | 'info'; certainty: string; quoted: string; start: number; end: number; explanation: string; action: string; evidence: Evidence[]; status: string }
export type ReviewFinding = Omit<Finding, 'id'>
export interface ReviewResult { review_run_id: string; revision_id: string; engine: string; findings: ReviewFinding[]; dependencies: Array<{ source: string; version: string; method: string }>; summary: string }
export interface ReviewRun { id: string; rev: string; engine: string; context: Record<string, unknown>; created: string }
export interface FindingDetail { finding: Finding; evidence: Evidence[]; location?: { start: number; end: number; page?: number; slide?: number }; source_records?: Array<{ id: string; url?: string; retrieved_at?: string; published_at?: string }> }
export interface EvidenceAssessment { id: string; evidence_id: string; original_filename: string; assessment: string; explanation: string; excerpt: string | null; location?: Record<string, unknown> | null }
export interface AutomatedDecision { outcome: 'approved' | 'rejected' | 'on_hold'; risk_score: number; rationale: string; factors: Array<{ code: string; weight: number; detail: string }>; policy_version: string; created_at?: string }
export interface VisualAnalysis { status: string; results: { status?: string; message?: string; dominant_colors?: Array<{ color: string; coverage: number; nearest_approved: string; delta_e: number }>; findings?: Array<{ color: string; nearest_approved: string; delta_e: number; coverage: number }>; limitations?: string[] } }
export interface VisualAsset { id: string; brand_profile_id: string; family_id: string; version_no: number; name: string; asset_type: string; category: string; original_filename: string; mime_type: string; size_bytes: number; content_hash: string; approved: boolean; created_at: string }
export interface PaletteVersion { id: string; brand_profile_id: string; version_no: number; colors: string[]; created_at: string }
export interface MonitoredSource { id: string; brand_profile_id: string; product_id?: string | null; product_name?: string | null; url: string; label: string; interval_minutes: number; status: string; last_checked_at: string | null; next_check_at: string; failure_count: number; snapshot_count: number; open_changes: number; created_at: string }
export interface MonitoringChange { id: string; monitored_source_id: string; label: string; url: string; previous_version: number; current_version: number; change_summary: string; change_excerpt: string; status: string; created_at: string; review_status: string | null; outcome: string | null; risk_score: number | null; report: Record<string, unknown> | null }
export interface RiskQueueItem { item_type: 'finding' | 'monitoring_change'; item_id: string; source_label: string; source_id: string; title: string; explanation: string; severity: string; assessment: string | null; status: string; created_at: string; risk_score: number; automated_outcome: string | null; evidence_count: number }
export interface SubmissionDetail extends Submission { revision: Revision; findings: Finding[] | null; decisions: Decision[]; evidence: SubmissionEvidence[]; assessments: EvidenceAssessment[]; automated_decision: AutomatedDecision | null; visual_analysis: VisualAnalysis | null; product_link: { product_id: string; product_name: string; brand: string | null; manufacturer: string | null; model_number: string | null; product_category: string | null; market: string | null; identity_status: string; latest_research_run_id: string | null; research_status: string | null; coverage: Record<string, unknown> | null } | null }
export interface ProductRecord { id: string; brand_profile_id: string; product_name: string; brand: string | null; manufacturer: string | null; model_number: string | null; product_category: string | null; market: string | null; official_website: string | null; identity_status: 'confirmed' | 'ambiguous'; identity_confirmed: boolean; latest_run_id?: string | null; latest_research_status?: string | null; latest_researched_at?: string | null; latest_coverage?: Record<string, unknown> | null }
export interface SourceAssessmentSignal { status: string; reason: string; verified?: boolean; age_days?: number | null; threshold_days?: { recent: number; potentially_outdated: number } }
export interface SourceAssessment { policy_version: string; assessed_at?: string; overall_status: string; signals: Record<string, SourceAssessmentSignal>; limitations: string[] }
export interface ProductSource { id: string; title: string; url: string; domain: string; source_category: string; publisher: string | null; published_at: string | null; retrieved_at: string; access_status: string; extraction_status: string; excerpt: string; duplicate_of: string | null; cached: boolean; product_match_status: string; source_assessment?: SourceAssessment; query_ids: string[] | null }
export interface ProductCoverage { queries_executed: number; queries_failed: number; search_results_discovered: number; unique_sources: number; sources_inspected: number; sources_inaccessible: number; cached_sources_used: number; supporting_sources: number; contradicting_sources: number; claims_evaluated: number; claims_inconclusive: number; product_facts_supported?: number; profile_extraction_status?: string; profile_extraction_note?: string; categories_covered: string[]; categories_with_insufficient_information: string[]; latest_research_at: string; independent_sources_assessed: number; note: string }
export interface ProductFact { category: string; statement: string; quote: string; evidence_status: 'supported_by_source'; source_id: string; source_title: string; source_url: string; retrieved_at: string }
export interface ProductClaimEvidence { source_id: string; source_title: string; source_url: string; publisher: string | null; published_at: string | null; evidence_excerpt: string; search_query: string | null; product_research_source_id: string | null; source_assessment: SourceAssessment | null; stance: string }
export interface ProductClaim { finding_id: string; review_run_id: string; submission_title: string; claim_text: string; finding_title: string; explanation: string; verification_status: string | null; evidence: ProductClaimEvidence[] }
export interface ProductClaimCoverage { claims_evaluated: number; supporting_sources: number; contradicting_sources: number; claims_inconclusive: number }
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
