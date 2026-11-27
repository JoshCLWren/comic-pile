import { describe, expect, it } from 'vitest'

import { createTasteApi, tasteSignalName } from '../services/api-taste'
import { createHttpClientStub } from './httpClientStub'

const client = createHttpClientStub()
const tasteApi = createTasteApi(client)

describe('tasteApi', () => {
  it('reads discoveries from the canonical v2 collection (#5717)', async () => {
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
    expect(client.get).toHaveBeenCalledWith('/v2/users/me/tasteDiscoveries')
  })

  it('dismisses through the canonical v2 custom method (#5717)', async () => {
    client.post.mockResolvedValue({ dismissed: true })

    await expect(tasteApi.dismiss(7)).resolves.toEqual({ dismissed: true })
    expect(client.post).toHaveBeenCalledWith(
      '/v2/users/me/tasteDiscoveries/7:dismiss',
    )
  })

  it('patches the canonical v2 signal with an encoded composite name (#5717)', async () => {
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
    client.patch.mockResolvedValue(payload)

    await expect(
      tasteApi.submitVerdict('creator', 'creator:writer:dk', 'confirmed'),
    ).resolves.toEqual(payload)
    expect(client.patch).toHaveBeenCalledWith(
      '/v2/users/me/tasteSignals/creator%3Acreator%3Awriter%3Adk',
      { user_verdict: 'confirmed', update_mask: ['user_verdict'] },
    )
  })

  it('builds a stable colon-shaped signal name without losing the key (#5717)', () => {
    expect(tasteSignalName('creator', 'creator:writer:dk')).toBe(
      'creator:creator:writer:dk',
    )
    expect(encodeURIComponent(tasteSignalName('era', '1990s:what-if'))).toBe(
      'era%3A1990s%3Awhat-if',
    )
  })

  it('never calls the retired v1 taste paths (#5717)', () => {
    expect(client.put).not.toHaveBeenCalled()
    expect(client.get).not.toHaveBeenCalledWith('/v1/taste/discoveries')
    expect(client.post).not.toHaveBeenCalledWith(
      '/v1/taste/discoveries/7/dismiss',
    )
  })
})
