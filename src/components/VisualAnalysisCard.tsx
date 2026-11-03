import type { VisualAnalysis, VisualRuleAnalysis } from '../api/contracts/index'

function coordinatesText(coordinates?: Record<string, number> | null) {
  if (!coordinates) return null
  return Object.entries(coordinates).map(([key, value]) => `${key.replaceAll('_', ' ')} ${value}`).join(' · ')
}

function RuleAnalysis({ title, analysis }: { title: string; analysis?: VisualRuleAnalysis }) {
  if (!analysis) return null
  return <div className="visual-page-result">
    <div className="logo-result-heading"><b>{title} · {analysis.status}</b></div>
    <p>{analysis.message}</p>
    {analysis.fonts_detected?.length ? <small>Detected families: {analysis.fonts_detected.join(', ')}</small> : null}
    {analysis.findings.map((finding, index) => <div className="evidence-quote" key={`${finding.message}-${index}`}>
      <b>{finding.kind === 'slide' ? `Slide ${finding.page_number}` : finding.page_number ? `Page ${finding.page_number}` : finding.kind}</b>
      {finding.font ? ` · ${finding.font}` : ''}{finding.size_pt ? ` · ${finding.size_pt} pt` : ''} · {finding.message}
      {coordinatesText(finding.coordinates) ? <small className="visual-limit">{coordinatesText(finding.coordinates)}</small> : null}
    </div>)}
    {analysis.limitations?.map(text => <small className="visual-limit" key={text}>{text}</small>)}
  </div>
}

export default function VisualAnalysisCard({ analysis }: { analysis: VisualAnalysis | null }) {
  if (!analysis) return null
  const results = analysis.results
  const logos = results.logo_analysis
  return <section className="panel">
    <div className="panel-heading"><div><div className="eyebrow">VISUAL BRAND CHECK</div><h2>Visual analysis · {analysis.status}</h2></div></div>
    <p className="side-copy">{results.message ?? (results.findings?.length
      ? `${results.findings.length} possible palette discrepancy(s) detected.`
      : 'Results are limited to the supported checks listed below.')}</p>
    {results.delta_threshold !== undefined && <small className="visual-limit">Palette thresholds: ΔE &gt; {results.delta_threshold}, region coverage ≥ {Math.round((results.coverage_threshold ?? 0) * 100)}%.</small>}

    {results.pages?.length ? results.pages.map(page => <div className="visual-page-result" key={page.page_number}>
      <b>Page {page.page_number}</b>
      {page.dominant_colors?.length ? <div className="color-swatches">{page.dominant_colors.map((swatch, index) =>
        <span key={`${swatch.color}-${index}`} title={`${swatch.color}, ${Math.round(swatch.coverage * 100)}%, ΔE ${swatch.delta_e}`}
          style={{ backgroundColor: swatch.color }} />)}</div> : <small>No dominant colors recorded for this page.</small>}
      {page.findings?.map((finding, index) => <div className="evidence-quote" key={`${finding.color}-${index}`}>
        <b>{finding.color}</b> covers {Math.round(finding.coverage * 100)}% · nearest approved {finding.nearest_approved} · ΔE {finding.delta_e}
        {finding.coordinates && ` · area ${finding.coordinates.x_percent ?? '—'}%, ${finding.coordinates.y_percent ?? '—'}%`}
      </div>)}
    </div>) : null}
    {!results.pages?.length && results.dominant_colors?.length ? <div className="color-swatches">
      {results.dominant_colors.map((swatch, index) => <span key={`${swatch.color}-${index}`}
        title={`${swatch.color}, ${Math.round(swatch.coverage * 100)}%, ΔE ${swatch.delta_e}`}
        style={{ backgroundColor: swatch.color }} />)}
    </div> : null}
    {!results.pages?.length && results.findings?.map((finding, index) => <div className="evidence-quote" key={`${finding.color}-${index}`}>
      <b>{finding.page_number ? `Page ${finding.page_number} · ` : ''}{finding.color}</b> covers {Math.round(finding.coverage * 100)}% · nearest approved {finding.nearest_approved} · ΔE {finding.delta_e}
      {finding.coordinates && ` · area ${finding.coordinates.x_percent ?? '—'}%, ${finding.coordinates.y_percent ?? '—'}%`}
    </div>)}

    {logos && <div className="logo-analysis">
      <div className="eyebrow">APPROVED LOGO COMPARISON · {logos.status}</div>
      <p>{logos.assets_examined} embedded image asset(s) checked. Similarity results require human confirmation.</p>
      {logos.matches.length ? logos.matches.map((match, index) => <article className="logo-result" key={`${match.reference_asset_id ?? match.asset_label}-${index}`}>
        <div className="logo-result-heading"><b>{match.asset_label || 'Image asset'}{match.page_number
          ? ` · ${match.asset_kind === 'pptx_image' ? 'Slide' : 'Page'} ${match.page_number}` : ''}</b>
          <span>{match.status.replaceAll('_', ' ')} · {match.review_status.replaceAll('_', ' ')}</span></div>
        <div className="logo-comparison">
          {match.submitted_preview && <div><small>Submitted image</small><img src={match.submitted_preview} alt="Submitted logo candidate" /></div>}
          {match.approved_preview && <div><small>Approved reference · {match.reference_name}</small><img src={match.approved_preview} alt={`Approved logo reference ${match.reference_name}`} /></div>}
        </div>
        {match.similarity !== undefined && <small>Perceptual similarity {Math.round(match.similarity * 100)}% · hash distance {match.perceptual_hash_distance}/64</small>}
        {match.issues?.length ? <p className="visual-limit">Review possible {match.issues.map(issue => issue.replaceAll('_', ' ')).join(', ')}.</p> : null}
        {match.message && <p className="visual-limit">{match.message}</p>}
        {coordinatesText(match.coordinates) && <small>Location: {coordinatesText(match.coordinates)}</small>}
      </article>) : <p>No labelled or sufficiently similar embedded logo images were detected. Unlabelled unmatched images are not assumed to be logos.</p>}
      {logos.limitations?.map(text => <small className="visual-limit" key={text}>{text}</small>)}
    </div>}

    <RuleAnalysis title="Typography" analysis={results.typography_analysis} />
    <RuleAnalysis title="Layout boundaries" analysis={results.layout_analysis} />
    {results.truncated && <small className="visual-limit">Only {results.pages_analyzed ?? 0} of {results.page_count ?? 0} pages were screened.</small>}
    {results.limitations?.map(text => <small className="visual-limit" key={text}>{text}</small>)}
  </section>
}
