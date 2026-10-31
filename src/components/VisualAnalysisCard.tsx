import type { VisualAnalysis } from '../api/contracts/index'

export default function VisualAnalysisCard({ analysis }: { analysis: VisualAnalysis | null }) {
  if (!analysis) return null
  const results = analysis.results
  return <section className="panel"><div className="panel-heading"><div><div className="eyebrow">VISUAL BRAND CHECK</div><h2>Palette analysis · {analysis.status}</h2></div></div><p className="side-copy">{results.message ?? (results.findings?.length ? `${results.findings.length} possible palette discrepancy(s) detected.` : 'Dominant colors compared with the current approved palette.')}</p>{results.dominant_colors?.length ? <div className="color-swatches">{results.dominant_colors.map((swatch, index) => <span key={`${swatch.color}-${index}`} title={`${swatch.color}, ${Math.round(swatch.coverage * 100)}%, ΔE ${swatch.delta_e}`} style={{ backgroundColor: swatch.color }} />)}</div> : null}{results.findings?.map((finding, index) => <div className="evidence-quote" key={`${finding.color}-${index}`}><b>{finding.color}</b> covers {Math.round(finding.coverage * 100)}% · nearest approved {finding.nearest_approved} · ΔE {finding.delta_e}</div>)}{results.limitations?.map(text => <small className="visual-limit" key={text}>{text}</small>)}</section>
}
