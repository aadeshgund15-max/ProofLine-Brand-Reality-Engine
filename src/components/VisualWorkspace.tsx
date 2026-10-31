import { useCallback, useEffect, useState } from 'react'
import type { Workspace } from '../api/contracts/index'
import { visualApi } from '../api/client'

export default function VisualWorkspace({ workspace }: { workspace: Workspace }) {
  const [library, setLibrary] = useState<Awaited<ReturnType<typeof visualApi.library>> | null>(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [assetName, setAssetName] = useState('')
  const [assetType, setAssetType] = useState('logo')
  const [category, setCategory] = useState('primary')
  const [file, setFile] = useState<File | null>(null)
  const [colors, setColors] = useState('')
  const [previews, setPreviews] = useState<Record<string, string>>({})
  const [previewErrors, setPreviewErrors] = useState<Record<string, string>>({})
  const refresh = useCallback(() => visualApi.library(workspace.id).then(data => { setLibrary(data); setError('') }).catch(e => setError(e instanceof Error ? e.message : 'Could not load visual references.')), [workspace.id])
  useEffect(() => { void refresh() }, [refresh])
  useEffect(() => { if (library?.palettes[0]) setColors(library.palettes[0].colors.join(', ')) }, [library])
  useEffect(() => {
    if (!library) return
    let active = true
    let urls: string[] = []
    setPreviews({})
    setPreviewErrors({})
    void Promise.all(library.assets.filter(asset => asset.approved).map(async asset => {
      const entry: { id: string; url?: string; error?: string } = { id: asset.id }
      try { entry.url = URL.createObjectURL(await visualApi.content(workspace.id, asset.id)) }
      catch (e) { entry.error = e instanceof Error ? e.message : 'Preview could not be loaded.' }
      return entry
    })).then(entries => {
      const ready = entries.flatMap(entry => entry.url ? [[entry.id, entry.url] as const] : [])
      const failed = Object.fromEntries(entries.flatMap(entry => entry.error ? [[entry.id, entry.error] as const] : []))
      const created = ready.map(([, url]) => url)
      if (active) { urls = created; setPreviews(Object.fromEntries(ready)); setPreviewErrors(failed) }
      else created.forEach(url => URL.revokeObjectURL(url))
    })
    return () => { active = false; urls.forEach(url => URL.revokeObjectURL(url)) }
  }, [library, workspace.id])
  const perform = async (fn: () => Promise<unknown>, message: string) => {
    setBusy(true); setError(''); setNotice('')
    try { await fn(); setNotice(message); await refresh() }
    catch (e) { setError(e instanceof Error ? e.message : 'The request failed.') }
    finally { setBusy(false) }
  }
  const saveAsset = () => {
    if (!library || !file || !assetName.trim()) return
    void perform(() => visualApi.upload(workspace.id, library.profileId, assetName.trim(), assetType, category.trim() || 'general', file), 'Approved visual reference saved.')
  }
  const saveColors = () => {
    if (!library) return
    const parsed = colors.split(/[\s,;]+/).map(color => color.trim()).filter(Boolean)
    void perform(() => visualApi.savePalette(workspace.id, library.profileId, parsed), 'Approved palette version saved.')
  }
  return <><div className="page-heading"><div><div className="eyebrow">VISUAL BRAND INTELLIGENCE</div><h1>Visual references</h1><p>Approved logo references and colors used by image reviews.</p></div><div className="heading-action"><span className="role-chip">Owner managed</span></div></div>
    {error && <div role="alert" className="feedback feedback-error">{error}</div>}{notice && <div role="status" className="feedback feedback-success">{notice}</div>}
    {!library && !error && <section className="panel"><p>Loading workspace visual references…</p></section>}
    {library && <div className="team-layout visual-layout"><section className="panel"><div className="panel-heading"><div><h2>Approved assets</h2><p>Private to this workspace · immutable versions</p></div><span className="panel-counter">{library.assets.length}</span></div>{library.assets.length ? <div className="fact-list">{library.assets.map(asset => <article className="fact-card" key={asset.id}>{previews[asset.id] && <img className="asset-preview" src={previews[asset.id]} alt={asset.name} />}{previewErrors[asset.id] && <p role="alert" className="feedback feedback-error">Preview unavailable: {previewErrors[asset.id]}</p>}<div className="fact-top"><div className="fact-symbol">◉</div><div className="fact-title"><span className="fact-key">{asset.asset_type.replaceAll('_', ' ')} · {asset.category}</span><h3>{asset.name}</h3><span className="fact-unit">Version {asset.version_no} · {asset.original_filename}</span></div><span className="approval-label approval-yes"><span />Approved</span></div></article>)}</div> : <div className="mini-empty">No visual references yet.</div>}</section>
      <section className="panel"><div className="form-panel-header"><span className="form-panel-icon">◈</span><div><h2>Add a reference</h2><p>Owners can upload approved PNG and JPG assets.</p></div></div>{workspace.role === 'owner' ? <div className="form-stack"><label className="field"><span>Asset name</span><input value={assetName} onChange={e => setAssetName(e.target.value)} placeholder="Primary wordmark" /></label><label className="field"><span>Type</span><select value={assetType} onChange={e => setAssetType(e.target.value)}><option value="logo">Logo</option><option value="reference_image">Reference image</option></select></label><label className="field"><span>Category</span><input value={category} onChange={e => setCategory(e.target.value)} /></label><label className="field"><span>PNG or JPG</span><input type="file" accept="image/png,image/jpeg" onChange={e => setFile(e.target.files?.[0] ?? null)} /></label><button className="button button-primary button-wide" disabled={busy || !file || !assetName.trim()} onClick={saveAsset}>{busy ? 'Saving…' : 'Save approved reference'}</button></div> : <p className="permission-note">Only a workspace owner can add approved references.</p>}</section>
      <section className="panel"><div className="form-panel-header"><span className="form-panel-icon">◌</span><div><h2>Approved color palette</h2><p>Six digit hex colors separated by commas. Each save creates a version.</p></div></div>{library.palettes.map(version => <div className="version-row" key={version.id}><b>Palette v{version.version_no}</b><div className="color-swatches">{version.colors.map(color => <span key={color} title={color} style={{ backgroundColor: color }} />)}<code>{version.colors.join(' · ')}</code></div></div>)}{workspace.role === 'owner' && <div className="form-stack"><label className="field"><span>Hex colors</span><input value={colors} onChange={e => setColors(e.target.value)} placeholder="#17324D, #FFFFFF, #D9A441" /></label><button className="button button-secondary button-small" disabled={busy || !colors.trim()} onClick={saveColors}>Save palette version</button></div>}</section>
      <section className="panel"><div className="eyebrow">CURRENT LIMITS</div><h2>Palette screening is active</h2><p className="side-copy">Image reviews compare dominant colors using CIE76 Delta E and show measured coverage. Logo matching, typography, layout, PDF pages, and slide analysis remain incomplete. Palette findings are review signals, not proof of a violation.</p></section></div>}
  </>
}
