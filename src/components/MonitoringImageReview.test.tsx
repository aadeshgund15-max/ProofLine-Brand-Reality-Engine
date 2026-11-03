// @vitest-environment jsdom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it } from 'vitest'
import type { MonitoredImageAnalysis } from '../api/contracts/index'
import { ChangedImageReview } from './MonitoringWorkspace'

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

describe('ChangedImageReview', () => {
  let container: HTMLDivElement | null = null
  let root: ReturnType<typeof createRoot> | null = null

  afterEach(() => {
    if (root) act(() => root?.unmount())
    container?.remove()
    root = null
    container = null
  })

  it('shows changed monitored and approved logo previews with a human-review label', async () => {
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
    const analysis: MonitoredImageAnalysis = {
      status: 'partial',
      assets_examined: 1,
      changed_asset_urls: ['https://example.org/logo.png'],
      matches: [{ status: 'similar_to_approved_logo', review_status: 'needs_human_review',
        asset_label: 'Logo · https://example.org/logo.png', reference_name: 'Primary',
        similarity: 0.95, perceptual_hash_distance: 3,
        submitted_preview: 'data:image/jpeg;base64,AA==', approved_preview: 'data:image/jpeg;base64,BB==' }],
    }
    await act(async () => root?.render(createElement(ChangedImageReview, { analysis })))
    expect(container.textContent).toContain('CHANGED IMAGE REVIEW')
    expect(container.textContent).toContain('needs human review')
    expect(container.querySelectorAll('.logo-comparison img')).toHaveLength(2)
  })
})
