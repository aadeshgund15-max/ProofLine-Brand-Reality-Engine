// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, submissionApi } from './client'

const { mockGetSession, mockSignOut } = vi.hoisted(() => ({ mockGetSession: vi.fn(), mockSignOut: vi.fn() }))
vi.mock('./supabase', () => ({
  supabase: { auth: { getSession: mockGetSession, signOut: mockSignOut } },
  requireSupabase: vi.fn(),
}))

describe('Proofline API client', () => {
  beforeEach(() => {
    mockGetSession.mockResolvedValue({ data: { session: { access_token: 'supabase-access-token' } } })
    mockSignOut.mockReset()
    vi.stubGlobal('fetch', vi.fn())
  })
  afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals() })

  it('uses the backend /api route and forwards the Supabase bearer token', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response('[]', { status: 200, headers: { 'Content-Type': 'application/json' } }))
    await expect(submissionApi.list('workspace-1')).resolves.toEqual([])
    const [url, options] = vi.mocked(fetch).mock.calls[0]
    expect(String(url)).toMatch(/\/api\/workspaces\/workspace-1\/submissions$/)
    expect(new Headers(options?.headers).get('Authorization')).toBe('Bearer supabase-access-token')
  })

  it('surfaces network failures instead of returning fixture records', async () => {
    vi.mocked(fetch).mockRejectedValue(new TypeError('offline'))
    await expect(submissionApi.list('workspace-1')).rejects.toMatchObject({ name: 'ApiError', message: expect.stringContaining('could not be reached') })
  })

  it('clears an expired Supabase session and reports the backend error', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ detail: 'Invalid token' }), { status: 401, headers: { 'Content-Type': 'application/json' } }))
    const expired = vi.fn()
    window.addEventListener('proofline:session-expired', expired)
    await expect(submissionApi.list('workspace-1')).rejects.toBeInstanceOf(ApiError)
    expect(mockSignOut).toHaveBeenCalledOnce()
    expect(expired).toHaveBeenCalledOnce()
    window.removeEventListener('proofline:session-expired', expired)
  })

  it('downloads the persisted submission report with the current bearer token', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(new Blob(['%PDF-report']), { status: 200, headers: { 'Content-Type': 'application/pdf' } }))
    const blob = await submissionApi.report('workspace-1', 'submission-1')
    expect(blob.type).toBe('application/pdf')
    expect(blob.size).toBeGreaterThan(0)
    const [url, options] = vi.mocked(fetch).mock.calls[0]
    expect(String(url)).toMatch(/\/api\/workspaces\/workspace-1\/submissions\/submission-1\/report\.pdf$/)
    expect(new Headers(options?.headers).get('Authorization')).toBe('Bearer supabase-access-token')
  })
})
