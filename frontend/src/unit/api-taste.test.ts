import { describe, expect, it } from 'vitest'

import { createTasteApi } from '../services/api-taste'
import { createHttpClientStub } from './httpClientStub'

const client = createHttpClientStub()
const tasteApi = createTasteApi(client)

describe('tasteApi', () => {
  it('reads discoveries from the Rust-served taste discoveries endpoint', async () => {
    const payload = {
      discoveries: [
        {
          id: 7,
          signal_type: 'creator',
          external_key: 'creator:writer:dk',
          display_name: 'Donny Cates',
          prompt: 'You liked Donny Cates before. Want more?',
          evidence_count: 4,
          distinct_thread_count: 2,
        },
      ],
      generated_at: '2026-11-19T12:00:00Z',
    }
    client.get.mockResolvedValue(payload)

    await expect(tasteApi.getDiscoveries()).resolves.toEqual(payload)
    expect(client.get).toHaveBeenCalledWith('/v1/taste/discoveries')
  })

  it('dismisses discoveries through the Rust-served dismiss endpoint', async () => {
    client.post.mockResolvedValue({ dismissed: true })

    await expect(tasteApi.dismiss(7)).resolves.toEqual({ dismissed: true })
    expect(client.post).toHaveBeenCalledWith('/v1/taste/discoveries/7/dismiss')
  })

  it('submits verdicts through the taste-signals verdict endpoint', async () => {
    const payload = {
      user_id: 1,
      signal_type: 'creator',
      external_key: 'creator:writer:dk',
      display_name: 'Donny Cates',
      affinity_estimate: 0.8,
      confidence: 0.9,
      evidence_count: 4,
      distinct_thread_count: 2,
      user_verdict: 'confirmed' as const,
      verdict_at: '2026-11-19T12:00:00Z',
      first_observed_at: null,
      last_observed_at: null,
      last_prompted_at: null,
    }
    client.put.mockResolvedValue(payload)

    await expect(
      tasteApi.submitVerdict('creator', 'creator:writer:dk', 'confirmed'),
    ).resolves.toEqual(payload)
    expect(client.put).toHaveBeenCalledWith(
      '/v1/users/me/taste-signals/creator/creator%3Awriter%3Adk/verdict',
      { verdict: 'confirmed' },
    )
  })
})
