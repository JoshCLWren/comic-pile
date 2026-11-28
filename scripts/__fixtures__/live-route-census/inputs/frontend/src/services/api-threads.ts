import {client} from './client'

export const threadsApi = {
  listStale: () => client.get('/v1/threads/stale'),
  listV2: () => client.get('/v2/threads'),
}
