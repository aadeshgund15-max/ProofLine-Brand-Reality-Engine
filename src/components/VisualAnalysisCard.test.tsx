// @vitest-environment jsdom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it } from 'vitest'
import type { VisualAnalysis } from '../api/contracts/index'
import VisualAnalysisCard from './VisualAnalysisCard'

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

describe('VisualAnalysisCard', () => {
  let container: HTMLDivElement | null = null
  let root: ReturnType<typeof createRoot> | null = null

  afterEach(() => {
    if (root) act(() => root?.unmount())
    container?.remove()
    root = null
    container = null
  })

  it('shows the submitted and approved logo images with location and review caveat', async () => {
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
    const analysis: VisualAnalysis = {
      status: 'partial',
      results: {
        logo_analysis: {
          status: 'partial',
          assets_examined: 1,
          matches: [{
            status: 'similar_to_approved_logo',
            review_status: 'needs_human_review',
            asset_kind: 'pptx_image',
            page_number: 3,
            reference_name: 'Primary',
            similarity: 0.95,
            perceptual_hash_distance: 3,
            issues: ['rotated_placement'],
            coordinates: { x_inches: 1.25 },
            submitted_preview: 'data:image/jpeg;base64,AA==',
            approved_preview: 'data:image/jpeg;base64,BB==',
          }],
        },
        typography_analysis: {
          status: 'partial',
          message: 'Configured font checks were applied.',
          fonts_detected: ['Arial'],
          findings: [{ kind: 'slide', page_number: 3, font: 'Arial', size_pt: 12,
            message: 'font family is not approved', coordinates: { x_inches: 1.25 } }],
        },
      },
    }
    await act(async () => root?.render(createElement(VisualAnalysisCard, { analysis })))
    expect(container.textContent).toContain('Slide 3')
    expect(container.textContent).toContain('needs human review')
    expect(container.textContent).toContain('Typography · partial')
    expect(container.textContent).toContain('Arial')
    expect(container.querySelectorAll('.logo-comparison img')).toHaveLength(2)
    expect((container.querySelector('.logo-comparison img') as HTMLImageElement).alt).toBe('Submitted logo candidate')
  })
})
