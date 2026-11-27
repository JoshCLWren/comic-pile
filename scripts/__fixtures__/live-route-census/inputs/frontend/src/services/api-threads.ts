import {client} from './client'

export const threadsApi = {
  setPending: (id: number) => client.post(`/v1/threads/${id}/set-pending`),
  listStale: () => client.get('/v1/threads/stale'),
  listV2: () => client.get('/v2/threads'),
}
